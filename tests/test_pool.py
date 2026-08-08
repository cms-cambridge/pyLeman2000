"""Tests for Leman2000Pool parallel multi-file analysis."""

from __future__ import annotations

import io
import json
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from pyleman2000 import (
    DEFAULT_MATLAB_IMAGE,
    Leman2000DockerError,
    Leman2000Pool,
    Leman2000Result,
    Leman2000WorkerError,
    example_wav_path,
)
from pyleman2000.progress import BatchProgress

FIXTURE = Path(__file__).parent / "fixtures" / "sample_result.json"


@pytest.fixture
def raw_result() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _make_wavs(tmp_path: Path, n: int) -> list[Path]:
    wavs = []
    payload = example_wav_path().read_bytes()
    for i in range(n):
        path = tmp_path / f"tone_{i}.wav"
        path.write_bytes(payload)
        wavs.append(path)
    return wavs


def test_pool_rejects_non_positive_workers() -> None:
    with pytest.raises(ValueError, match="workers"):
        Leman2000Pool(workers=0)


def test_pool_defaults_to_single_worker(raw_result: dict, tmp_path: Path) -> None:
    wavs = _make_wavs(tmp_path, 3)
    runners: list[MagicMock] = []

    def make_runner(**kwargs):
        runner = MagicMock()
        runner.run.return_value = raw_result
        runners.append(runner)
        return runner

    with patch("pyleman2000.api.MatlabWorkerRunner", side_effect=make_runner):
        with Leman2000Pool(show_progress=False) as pool:
            pool.map(wavs, 0.1, 1.0)

    assert len(runners) == 1


def test_pool_map_rejects_bare_string_path() -> None:
    with patch("pyleman2000.api.MatlabWorkerRunner"):
        with Leman2000Pool(workers=1, show_progress=False) as pool:
            with pytest.raises(TypeError, match="sequence of paths"):
                pool.map("only_one.wav", 0.1, 1.0)


def test_pool_map_failure_cleans_up_and_reports_partial_progress(
    raw_result: dict, tmp_path: Path
) -> None:
    wavs = _make_wavs(tmp_path, 4)
    runners: list[MagicMock] = []

    def make_runner(**kwargs):
        runner = MagicMock()

        def run(*, input_file, **_kwargs):
            if Path(input_file).name.endswith("2.wav"):
                raise RuntimeError("worker blew up")
            return raw_result

        runner.run.side_effect = run
        runners.append(runner)
        return runner

    stream = io.StringIO()
    progress = BatchProgress(stream, step_files=1)

    with patch("pyleman2000.api.MatlabWorkerRunner", side_effect=make_runner):
        with Leman2000Pool(workers=2, show_progress=False) as pool:
            with pytest.raises(RuntimeError, match="worker blew up"):
                pool.map(wavs, 0.1, 1.0, progress=progress)

    # Every started session is returned/closed even though a job failed.
    for runner in runners:
        runner.close.assert_called_once_with()
    # The progress line must not claim all files finished.
    assert "4/4 files" not in stream.getvalue()


class _ClosingProgress:
    """Reporter whose ``close`` always raises, to test cleanup handling."""

    def start(self, n_files: int, n_workers: int) -> None:
        pass

    def update(self, completed: int) -> None:
        pass

    def close(self) -> None:
        raise RuntimeError("close failed")


def test_pool_map_close_error_does_not_mask_primary(
    raw_result: dict, tmp_path: Path
) -> None:
    wavs = _make_wavs(tmp_path, 2)
    runner = MagicMock()
    runner.run.side_effect = RuntimeError("worker blew up")

    with patch("pyleman2000.api.MatlabWorkerRunner", return_value=runner):
        with Leman2000Pool(workers=1, show_progress=False) as pool:
            with pytest.raises(RuntimeError, match="worker blew up"):
                pool.map(wavs, 0.1, 1.0, progress=_ClosingProgress())


def test_pool_map_close_error_propagates_on_success(
    raw_result: dict, tmp_path: Path
) -> None:
    wavs = _make_wavs(tmp_path, 1)
    runner = MagicMock()
    runner.run.return_value = raw_result

    with patch("pyleman2000.api.MatlabWorkerRunner", return_value=runner):
        with Leman2000Pool(workers=1, show_progress=False) as pool:
            with pytest.raises(RuntimeError, match="close failed"):
                pool.map(wavs, 0.1, 1.0, progress=_ClosingProgress())


def test_pool_map_empty_returns_empty() -> None:
    with patch("pyleman2000.api.MatlabWorkerRunner") as ctor:
        with Leman2000Pool(workers=2, show_progress=False) as pool:
            assert pool.map([], 0.1, 1.0) == []
    ctor.assert_called()


def test_pool_opens_one_runner_per_worker(raw_result: dict, tmp_path: Path) -> None:
    wavs = _make_wavs(tmp_path, 3)
    runners: list[MagicMock] = []

    def make_runner(**kwargs):
        runner = MagicMock()
        runner.run.return_value = raw_result
        runners.append(runner)
        return runner

    with patch("pyleman2000.api.MatlabWorkerRunner", side_effect=make_runner):
        with Leman2000Pool(workers=2, show_progress=False) as pool:
            results = pool.map(
                wavs,
                local_decay_sec=0.1,
                global_decay_sec=1.0,
            )

    assert len(runners) == 2
    for runner in runners:
        runner.open.assert_called_once_with()
        runner.close.assert_called_once_with()
    assert len(results) == 3
    assert all(isinstance(r, Leman2000Result) for r in results)
    assert sum(r.run.call_count for r in runners) == 3


def test_pool_map_preserves_input_order(raw_result: dict, tmp_path: Path) -> None:
    wavs = _make_wavs(tmp_path, 4)
    lock = threading.Lock()
    call_order: list[str] = []

    def make_runner(**kwargs):
        runner = MagicMock()

        def run(*, input_file, **_kwargs):
            name = Path(input_file).name
            # Reverse-ish completion: later files finish first when possible.
            delay = 0.05 if name.endswith("0.wav") else 0.001
            time.sleep(delay)
            with lock:
                call_order.append(name)
            return {
                **raw_result,
                "audio_length_sec": float(name.split("_")[1][0]),
            }

        runner.run.side_effect = run
        return runner

    with patch("pyleman2000.api.MatlabWorkerRunner", side_effect=make_runner):
        with Leman2000Pool(workers=2, show_progress=False) as pool:
            results = pool.map(wavs, 0.1, 1.0)

    assert [r.audio_length_sec for r in results] == [0.0, 1.0, 2.0, 3.0]
    assert sorted(call_order) == sorted(p.name for p in wavs)


def test_pool_map_with_errors_returns_aligned_outcomes(
    raw_result: dict, tmp_path: Path
) -> None:
    wavs = _make_wavs(tmp_path, 3)
    runner = MagicMock()
    error = RuntimeError("bad file")
    runner.run.side_effect = [raw_result, error, raw_result]

    with patch("pyleman2000.api.MatlabWorkerRunner", return_value=runner):
        with Leman2000Pool(workers=1, show_progress=False) as pool:
            results, errors = pool.map_with_errors(wavs, 0.1, 1.0)

    assert results[0] is not None
    assert results[1] is None
    assert results[2] is not None
    assert errors == [None, error, None]


def test_pool_recovers_docker_worker_after_continued_error(
    raw_result: dict, tmp_path: Path
) -> None:
    wavs = _make_wavs(tmp_path, 2)
    runner = MagicMock()
    error = Leman2000WorkerError("worker died")
    runner.run.side_effect = [error, raw_result]

    with patch("pyleman2000.api.MatlabWorkerRunner", return_value=runner):
        with Leman2000Pool(workers=1, show_progress=False) as pool:
            results, errors = pool.map_with_errors(wavs, 0.1, 1.0)

    assert results[1] is not None
    assert errors == [error, None]
    # Initial open, recovery open; recovery close, context-manager close.
    assert runner.open.call_count == 2
    assert runner.close.call_count == 2


def test_pool_keeps_healthy_worker_after_request_error(
    raw_result: dict, tmp_path: Path
) -> None:
    wavs = _make_wavs(tmp_path, 2)
    runner = MagicMock()
    error = Leman2000DockerError("MATLAB worker request failed: bad file")
    runner.run.side_effect = [error, raw_result]

    with patch("pyleman2000.api.MatlabWorkerRunner", return_value=runner):
        with Leman2000Pool(workers=1, show_progress=False) as pool:
            results, errors = pool.map_with_errors(wavs, 0.1, 1.0)

    assert results[1] is not None
    assert errors == [error, None]
    assert runner.open.call_count == 1
    assert runner.close.call_count == 1


def test_pool_never_runs_two_jobs_on_same_session(
    raw_result: dict, tmp_path: Path
) -> None:
    wavs = _make_wavs(tmp_path, 6)
    active_per_runner: dict[int, int] = {}
    max_per_runner: dict[int, int] = {}
    lock = threading.Lock()
    peak_total = 0
    current_total = 0

    def make_runner(**kwargs):
        runner = MagicMock()
        runner_id = id(runner)
        with lock:
            active_per_runner[runner_id] = 0
            max_per_runner[runner_id] = 0

        def run(**_kwargs):
            nonlocal peak_total, current_total
            with lock:
                active_per_runner[runner_id] += 1
                current_total += 1
                max_per_runner[runner_id] = max(
                    max_per_runner[runner_id], active_per_runner[runner_id]
                )
                peak_total = max(peak_total, current_total)
            try:
                time.sleep(0.02)
                return raw_result
            finally:
                with lock:
                    active_per_runner[runner_id] -= 1
                    current_total -= 1

        runner.run.side_effect = run
        return runner

    with patch("pyleman2000.api.MatlabWorkerRunner", side_effect=make_runner):
        with Leman2000Pool(workers=3, show_progress=False) as pool:
            pool.map(wavs, 0.1, 1.0)

    assert max(max_per_runner.values()) == 1
    assert peak_total >= 2


def test_pool_default_backend_is_matlab(raw_result: dict, tmp_path: Path) -> None:
    wavs = _make_wavs(tmp_path, 1)
    runner = MagicMock()
    runner.run.return_value = raw_result

    with patch("pyleman2000.api.MatlabWorkerRunner", return_value=runner) as ctor:
        with patch("pyleman2000.api.WarmModelRunner") as octave_ctor:
            with Leman2000Pool(workers=1, show_progress=False) as pool:
                pool.map(wavs, 0.1, 1.0)

    octave_ctor.assert_not_called()
    assert ctor.call_args.kwargs["image"] == DEFAULT_MATLAB_IMAGE


def test_pool_octave_backend_uses_warm_runner(
    raw_result: dict, tmp_path: Path
) -> None:
    wavs = _make_wavs(tmp_path, 1)
    runner = MagicMock()
    runner.run.return_value = raw_result

    with patch("pyleman2000.api.WarmModelRunner", return_value=runner) as ctor:
        with patch("pyleman2000.api.MatlabWorkerRunner") as matlab_ctor:
            with Leman2000Pool(
                workers=1, backend="octave", show_progress=False
            ) as pool:
                pool.map(wavs, local_decay_sec=[0.1, 0.5], global_decay_sec=1.0)

    matlab_ctor.assert_not_called()
    ctor.assert_called_once()
    assert runner.run.call_args.kwargs["local_decay_sec"] == [0.1, 0.5]


def test_pool_closes_sessions_if_open_fails() -> None:
    opened: list[MagicMock] = []

    def make_runner(**kwargs):
        runner = MagicMock()
        if len(opened) == 1:
            runner.open.side_effect = RuntimeError("boom")
        opened.append(runner)
        return runner

    with (
        patch("pyleman2000.api.MatlabWorkerRunner", side_effect=make_runner),
        pytest.raises(RuntimeError, match="boom"),
    ):
        with Leman2000Pool(workers=2, show_progress=False):
            pass

    assert opened[0].close.call_count == 1


def test_pool_map_requires_open(raw_result: dict, tmp_path: Path) -> None:
    wavs = _make_wavs(tmp_path, 1)
    pool = Leman2000Pool(workers=1, show_progress=False)
    with pytest.raises(RuntimeError, match="not open"):
        pool.map(wavs, 0.1, 1.0)
