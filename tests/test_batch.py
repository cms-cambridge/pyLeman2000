"""Tests for leman2000_batch and combined batch results."""

from __future__ import annotations

import io
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from pyleman2000 import (
    Leman2000BatchResult,
    example_wav_path,
    leman2000_batch,
)
from pyleman2000.progress import BatchProgress
from pyleman2000.types import Leman2000Result, combine_results

FIXTURE = Path(__file__).parent / "fixtures" / "sample_result.json"


@pytest.fixture
def raw_result() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _result_from_raw(raw: dict, *, with_windows: bool = False) -> Leman2000Result:
    from pyleman2000.formatters import (
        format_local_global_comparison,
        window_local_global_comparison,
    )

    local = format_local_global_comparison(
        raw["local_global_comparison"],
        float(raw["audio_length_sec"]),
    )
    windowed = None
    if with_windows:
        windowed = window_local_global_comparison(
            local, [(0.0, 0.1), (0.1, 0.2)]
        )
    return Leman2000Result(
        audio_length_sec=float(raw["audio_length_sec"]),
        num_channels=int(raw["num_channels"]),
        sample_rate=float(raw["sample_rate"]),
        local_global_comparison=local,
        windowed_local_global_comparison=windowed,
    )


def _make_wavs(tmp_path: Path, n: int) -> list[Path]:
    payload = example_wav_path().read_bytes()
    wavs = []
    for i in range(n):
        path = tmp_path / f"tone_{i}.wav"
        path.write_bytes(payload)
        wavs.append(path)
    return wavs


def test_combine_results_stacks_frames(raw_result: dict, tmp_path: Path) -> None:
    wavs = _make_wavs(tmp_path, 2)
    results = [
        _result_from_raw(raw_result, with_windows=True),
        _result_from_raw(raw_result, with_windows=True),
    ]
    batch = combine_results(wavs, results, workers=2)

    assert isinstance(batch, Leman2000BatchResult)
    assert batch.workers == 2
    assert list(batch.files["file_id"]) == [1, 2]
    assert batch.files["input_file"].tolist() == [str(p.resolve()) for p in wavs]
    assert set(batch.local_global_comparison["file_id"]) == {1, 2}
    assert batch.windowed_local_global_comparison is not None
    assert "input_file" in batch.windowed_local_global_comparison.columns
    assert len(batch.results) == 2


def test_combine_results_without_windows(raw_result: dict, tmp_path: Path) -> None:
    wavs = _make_wavs(tmp_path, 1)
    batch = combine_results(
        wavs, [_result_from_raw(raw_result, with_windows=False)], workers=1
    )
    assert batch.windowed_local_global_comparison is None


def test_leman2000_batch_empty() -> None:
    batch = leman2000_batch([], 0.1, 1.0, show_progress=False)
    assert isinstance(batch, Leman2000BatchResult)
    assert batch.files.empty
    assert batch.local_global_comparison.empty
    assert batch.results == ()


def test_leman2000_batch_rejects_bare_string_path() -> None:
    with pytest.raises(TypeError, match="sequence of paths"):
        leman2000_batch("only_one.wav", 0.1, 1.0, show_progress=False)


def test_leman2000_batch_reports_partial_progress_on_failure(
    raw_result: dict, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    wavs = _make_wavs(tmp_path, 4)
    runner = MagicMock()

    def run(*, input_file, **_kwargs):
        if Path(input_file).name.endswith("2.wav"):
            raise RuntimeError("kaboom")
        return raw_result

    runner.run.side_effect = run
    stream = io.StringIO()
    monkeypatch.setattr(
        "pyleman2000.api.BatchProgress",
        lambda *a, **k: BatchProgress(stream, step_files=1),
    )

    with patch("pyleman2000.api.MatlabWorkerRunner", return_value=runner):
        with patch("pyleman2000.api.choose_worker_count", return_value=2):
            with pytest.raises(RuntimeError, match="kaboom"):
                leman2000_batch(wavs, 0.1, 1.0, workers=2, show_progress=True)

    # One close per pooled session (both share this mock at workers=2).
    assert runner.close.call_count == 2
    assert "4/4 files" not in stream.getvalue()


def test_leman2000_batch_uses_pool_and_combines(
    raw_result: dict, tmp_path: Path
) -> None:
    wavs = _make_wavs(tmp_path, 3)
    runner = MagicMock()
    runner.run.return_value = raw_result

    with patch("pyleman2000.api.MatlabWorkerRunner", return_value=runner):
        with patch(
            "pyleman2000.api.choose_worker_count", return_value=2
        ) as choose:
            batch = leman2000_batch(
                wavs,
                local_decay_sec=0.1,
                global_decay_sec=1.0,
                windows=[(0.0, 0.1)],
                workers=2,
                show_progress=False,
            )

    choose.assert_called_once()
    assert choose.call_args.args[0] == 3
    assert choose.call_args.kwargs["workers"] == 2
    assert runner.open.call_count == 2
    assert runner.run.call_count == 3
    assert isinstance(batch, Leman2000BatchResult)
    assert batch.workers == 2
    assert len(batch.files) == 3
    assert len(batch.results) == 3
    assert batch.windowed_local_global_comparison is not None
    counts = batch.local_global_comparison.groupby("file_id").size()
    assert list(counts.index) == [1, 2, 3]


def test_leman2000_batch_reports_progress(
    raw_result: dict, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    wavs = _make_wavs(tmp_path, 2)
    runner = MagicMock()
    runner.run.return_value = raw_result
    stream = io.StringIO()

    def fake_batch_progress(*_args, **_kwargs):
        return BatchProgress(stream, step_files=1)

    monkeypatch.setattr("pyleman2000.api.BatchProgress", fake_batch_progress)

    with patch("pyleman2000.api.MatlabWorkerRunner", return_value=runner):
        with patch("pyleman2000.api.choose_worker_count", return_value=1):
            leman2000_batch(wavs, 0.1, 1.0, workers=1, show_progress=True)

    lines = stream.getvalue().splitlines()
    assert lines[0] == "Leman (2000) batch: 0/2 files (1 workers)"
    assert lines[-1] == "Leman (2000) batch: 2/2 files (1 workers)"


def test_leman2000_batch_quiet_when_progress_disabled(
    raw_result: dict, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    wavs = _make_wavs(tmp_path, 1)
    runner = MagicMock()
    runner.run.return_value = raw_result

    with patch("pyleman2000.api.MatlabWorkerRunner", return_value=runner):
        with patch("pyleman2000.api.choose_worker_count", return_value=1):
            leman2000_batch(wavs, 0.1, 1.0, show_progress=False)

    captured = capsys.readouterr()
    assert captured.err == ""
    assert captured.out == ""
