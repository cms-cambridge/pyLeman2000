"""Tests for leman2000_batch and combined batch results."""

from __future__ import annotations

import io
import json
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from pyleman2000 import (
    Leman2000BatchFailure,
    Leman2000BatchResult,
    example_wav_path,
    leman2000_batch,
)
from pyleman2000.progress import BatchProgress
from pyleman2000.types import Leman2000Result, combine_results

FIXTURE = Path(__file__).parent / "fixtures" / "sample_result.json"


class RecordingProgress:
    def __init__(self) -> None:
        self.starts: list[tuple[int, int]] = []
        self.updates: list[int] = []
        self.close_count = 0

    def start(self, n_files: int, n_workers: int) -> None:
        self.starts.append((n_files, n_workers))

    def update(self, completed: int) -> None:
        self.updates.append(completed)

    def close(self) -> None:
        self.close_count += 1


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
    assert batch.files["status"].tolist() == ["ok", "ok"]
    assert batch.failures == ()
    assert str(batch.files["audio_length_sec"].dtype) == "Float64"
    assert str(batch.files["num_channels"].dtype) == "Int64"
    assert str(batch.files["sample_rate"].dtype) == "Float64"


def test_combine_results_preserves_nullable_dtypes_on_failures(
    raw_result: dict, tmp_path: Path
) -> None:
    wavs = _make_wavs(tmp_path, 2)
    error = RuntimeError("kaboom")
    batch = combine_results(
        wavs,
        [_result_from_raw(raw_result), None],
        workers=1,
        errors=[None, error],
    )

    assert str(batch.files["audio_length_sec"].dtype) == "Float64"
    assert str(batch.files["num_channels"].dtype) == "Int64"
    assert str(batch.files["sample_rate"].dtype) == "Float64"
    assert batch.failures[0].exception is error


def test_combine_results_handles_all_failed_files(tmp_path: Path) -> None:
    wavs = _make_wavs(tmp_path, 2)
    errors = [RuntimeError("first"), ValueError("second")]
    batch = combine_results(
        wavs,
        [None, None],
        workers=1,
        errors=errors,
    )

    assert batch.files["status"].tolist() == ["error", "error"]
    assert str(batch.files["num_channels"].dtype) == "Int64"
    assert batch.local_global_comparison.empty
    assert [failure.exception for failure in batch.failures] == errors


def test_combine_results_requires_exactly_one_result_or_error(
    raw_result: dict, tmp_path: Path
) -> None:
    wav = _make_wavs(tmp_path, 1)
    result = _result_from_raw(raw_result)

    for results, errors in (
        ([None], None),
        ([result], [RuntimeError("kaboom")]),
    ):
        with pytest.raises(ValueError, match="exactly one result or error"):
            combine_results(wav, results, workers=1, errors=errors)


def test_combine_results_without_windows(raw_result: dict, tmp_path: Path) -> None:
    wavs = _make_wavs(tmp_path, 1)
    batch = combine_results(
        wavs, [_result_from_raw(raw_result, with_windows=False)], workers=1
    )
    assert batch.windowed_local_global_comparison is None


def test_leman2000_batch_empty() -> None:
    batch = leman2000_batch([], 0.1, 1.0, progress=False)
    assert isinstance(batch, Leman2000BatchResult)
    assert batch.files.empty
    assert batch.local_global_comparison.empty
    assert batch.results == ()


def test_leman2000_batch_rejects_bare_string_path() -> None:
    with pytest.raises(TypeError, match="sequence of paths"):
        leman2000_batch("only_one.wav", 0.1, 1.0, progress=False)


def test_leman2000_batch_rejects_non_bool_continue_on_error() -> None:
    with pytest.raises(TypeError, match="continue_on_error must be a bool"):
        leman2000_batch(
            [],
            0.1,
            1.0,
            progress=False,
            continue_on_error=1,  # type: ignore[arg-type]
        )


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
                leman2000_batch(wavs, 0.1, 1.0, workers=2, progress=True)

    # One close per pooled session (both share this mock at workers=2).
    assert runner.close.call_count == 2
    assert "4/4 files" not in stream.getvalue()


def test_leman2000_batch_continues_and_preserves_failure_alignment(
    raw_result: dict, tmp_path: Path
) -> None:
    wavs = _make_wavs(tmp_path, 4)
    runner = MagicMock()

    def run(*, input_file, **_kwargs):
        if Path(input_file).name.endswith("2.wav"):
            raise RuntimeError("kaboom")
        return raw_result

    runner.run.side_effect = run

    with patch("pyleman2000.api.MatlabWorkerRunner", return_value=runner):
        with patch("pyleman2000.api.choose_worker_count", return_value=2):
            batch = leman2000_batch(
                wavs,
                0.1,
                1.0,
                workers=2,
                progress=False,
                continue_on_error=True,
            )

    assert len(batch.results) == 4
    assert batch.results[2] is None
    assert all(
        result is not None for index, result in enumerate(batch.results) if index != 2
    )
    assert batch.files["file_id"].tolist() == [1, 2, 3, 4]
    assert batch.files["status"].tolist() == ["ok", "ok", "error", "ok"]
    assert set(batch.local_global_comparison["file_id"]) == {1, 2, 4}
    assert batch.failures == (
        Leman2000BatchFailure(
            file_id=3,
            input_file=str(wavs[2].resolve()),
            error_type="RuntimeError",
            message="kaboom",
            exception=batch.failures[0].exception,
        ),
    )
    assert isinstance(batch.failures[0].exception, RuntimeError)


def test_leman2000_batch_counts_failures_as_completed_progress(
    raw_result: dict, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    wavs = _make_wavs(tmp_path, 2)
    runner = MagicMock()
    runner.run.side_effect = [RuntimeError("kaboom"), raw_result]
    stream = io.StringIO()
    monkeypatch.setattr(
        "pyleman2000.api.BatchProgress",
        lambda *a, **k: BatchProgress(stream, step_files=1),
    )

    with patch("pyleman2000.api.MatlabWorkerRunner", return_value=runner):
        with patch("pyleman2000.api.choose_worker_count", return_value=1):
            leman2000_batch(
                wavs,
                0.1,
                1.0,
                workers=1,
                progress=True,
                continue_on_error=True,
            )

    assert stream.getvalue().splitlines()[-1] == (
        "Leman (2000) batch: 2/2 files (1 workers)"
    )


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
                progress=False,
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
            leman2000_batch(wavs, 0.1, 1.0, workers=1, progress=True)

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
            leman2000_batch(wavs, 0.1, 1.0, progress=False)

    captured = capsys.readouterr()
    assert captured.err == ""
    assert captured.out == ""


def test_leman2000_batch_uses_custom_progress_and_preserves_order(
    raw_result: dict, tmp_path: Path
) -> None:
    wavs = _make_wavs(tmp_path, 4)
    reporter = RecordingProgress()

    def make_runner(**_kwargs):
        runner = MagicMock()

        def run(*, input_file, **_run_kwargs):
            index = int(Path(input_file).stem.rsplit("_", 1)[1])
            time.sleep(0.03 if index == 0 else 0.001)
            return {**raw_result, "audio_length_sec": float(index)}

        runner.run.side_effect = run
        return runner

    with patch("pyleman2000.api.MatlabWorkerRunner", side_effect=make_runner):
        with patch("pyleman2000.api.choose_worker_count", return_value=2):
            batch = leman2000_batch(
                wavs,
                0.1,
                1.0,
                workers=2,
                progress=reporter,
            )

    assert reporter.starts == [(4, 2)]
    assert reporter.updates == [1, 2, 3, 4]
    assert reporter.close_count == 1
    assert [result.audio_length_sec for result in batch.results] == [
        0.0,
        1.0,
        2.0,
        3.0,
    ]


def test_leman2000_batch_closes_custom_progress_after_failure(
    raw_result: dict, tmp_path: Path
) -> None:
    wavs = _make_wavs(tmp_path, 3)
    runner = MagicMock()
    runner.run.side_effect = RuntimeError("kaboom")
    reporter = RecordingProgress()

    with patch("pyleman2000.api.MatlabWorkerRunner", return_value=runner):
        with patch("pyleman2000.api.choose_worker_count", return_value=1):
            with pytest.raises(RuntimeError, match="kaboom"):
                leman2000_batch(wavs, 0.1, 1.0, progress=reporter)

    assert reporter.starts == [(3, 1)]
    assert reporter.updates == []
    assert reporter.close_count == 1


def test_leman2000_batch_rejects_none_progress(tmp_path: Path) -> None:
    wavs = _make_wavs(tmp_path, 1)

    with patch("pyleman2000.api.choose_worker_count", return_value=1):
        with pytest.raises(TypeError, match="progress must be"):
            leman2000_batch(wavs, 0.1, 1.0, progress=None)  # type: ignore[arg-type]


def test_leman2000_batch_prints_failure_summary_when_continuing(
    raw_result: dict, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    wavs = _make_wavs(tmp_path, 3)
    runner = MagicMock()

    def run(*, input_file, **_kwargs):
        if Path(input_file).name.endswith("1.wav"):
            raise RuntimeError("kaboom")
        return raw_result

    runner.run.side_effect = run
    reporter = RecordingProgress()

    with patch("pyleman2000.api.MatlabWorkerRunner", return_value=runner):
        with patch("pyleman2000.api.choose_worker_count", return_value=1):
            batch = leman2000_batch(
                wavs,
                0.1,
                1.0,
                progress=reporter,
                continue_on_error=True,
            )

    assert len(batch.failures) == 1
    err = capsys.readouterr().err
    assert "Leman (2000) batch: 1 file failed" in err
    assert "file_id 2" in err
    assert "RuntimeError: kaboom" in err


def test_leman2000_batch_no_failure_summary_when_disabled(
    raw_result: dict, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    wavs = _make_wavs(tmp_path, 2)
    runner = MagicMock()
    runner.run.side_effect = [RuntimeError("kaboom"), raw_result]

    with patch("pyleman2000.api.MatlabWorkerRunner", return_value=runner):
        with patch("pyleman2000.api.choose_worker_count", return_value=1):
            batch = leman2000_batch(
                wavs,
                0.1,
                1.0,
                progress=False,
                continue_on_error=True,
            )

    assert len(batch.failures) == 1
    captured = capsys.readouterr()
    assert captured.err == ""
    assert captured.out == ""
