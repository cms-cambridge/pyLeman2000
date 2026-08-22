"""Integration tests that require Docker and the Octave model image."""

from __future__ import annotations

import math

import pytest

from pyleman2000 import example_wav_path, leman2000, leman2000_batch
from pyleman2000.docker_runner import Leman2000DockerError
from tests.docker_support import docker_daemon_available

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not docker_daemon_available(),
        reason="Docker daemon not available",
    ),
]


def test_leman2000_end_to_end() -> None:
    try:
        result = leman2000(
            input_file=example_wav_path(),
            local_decay_sec=[0.1, 0.2],
            global_decay_sec=[1.0, 2.0],
            windows=[(0.0, 0.1), (0.1, 0.2), (0.2, 0.3)],
            backend="octave",
            show_progress=False,
        )
    except Leman2000DockerError as exc:
        pytest.fail(f"Octave backend failed: {exc}")

    combos = result.local_global_comparison[
        ["local_decay_sec", "global_decay_sec"]
    ].drop_duplicates()
    assert len(combos) == 4
    assert result.windowed_local_global_comparison is not None
    assert len(result.windowed_local_global_comparison) == 12
    assert math.isclose(result.audio_length_sec, 0.3707936508, rel_tol=0, abs_tol=1e-9)
    assert result.num_channels == 1
    assert result.sample_rate == 44100.0

    first_rows = result.local_global_comparison.groupby(
        ["local_decay_sec", "global_decay_sec"], sort=False
    ).first()
    assert (
        first_rows["running_correlation"].apply(lambda x: math.isclose(x, 1.0, abs_tol=1e-12))
    ).all()


def test_leman2000_batch_end_to_end() -> None:
    path = example_wav_path()
    try:
        batch = leman2000_batch(
            [path, path],
            local_decay_sec=[0.1, 0.2],
            global_decay_sec=1.0,
            workers=1,
            backend="octave",
            progress=False,
        )
    except Leman2000DockerError as exc:
        pytest.fail(f"Octave batch backend failed: {exc}")

    assert len(batch.files) == 2
    assert batch.files["status"].tolist() == ["ok", "ok"]
    assert len(batch.results) == 2
    assert all(result is not None for result in batch.results)
    assert set(batch.local_global_comparison["file_id"]) == {1, 2}
