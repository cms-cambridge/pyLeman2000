"""Snapshot tests comparing Octave output to archived R/MATLAB snapshots."""

from __future__ import annotations

import pandas as pd
import pytest

from pyleman2000 import example_wav_path, leman2000
from tests.docker_support import docker_daemon_available
from tests.snapshot_support import (
    GLOBAL_DECAY,
    LOCAL_DECAY,
    WINDOWS,
    assert_local_global_comparison_matches_r,
    assert_metadata_matches_r,
    assert_windowed_comparison_matches_r,
)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not docker_daemon_available(),
        reason="Docker daemon not available",
    ),
]


@pytest.fixture(scope="module")
def python_result():
    return leman2000(
        input_file=example_wav_path(),
        local_decay_sec=LOCAL_DECAY,
        global_decay_sec=GLOBAL_DECAY,
        windows=WINDOWS,
        backend="octave",
        show_progress=False,
    )


@pytest.fixture(scope="module")
def detailed_python_result():
    return leman2000(
        input_file=example_wav_path(),
        local_decay_sec=LOCAL_DECAY,
        global_decay_sec=GLOBAL_DECAY,
        keep_auditory_nerve=True,
        backend="octave",
        show_progress=False,
    )


def test_metadata_matches_r(python_result) -> None:
    assert_metadata_matches_r(python_result)


def test_local_global_comparison_matches_r(python_result) -> None:
    assert_local_global_comparison_matches_r(python_result)


def test_windowed_comparison_matches_r(python_result) -> None:
    assert_windowed_comparison_matches_r(python_result)


def test_detail_level_does_not_change_correlations(
    python_result, detailed_python_result
) -> None:
    pd.testing.assert_frame_equal(
        python_result.local_global_comparison,
        detailed_python_result.local_global_comparison,
        check_dtype=False,
        rtol=1e-12,
        atol=1e-12,
    )
    assert detailed_python_result.auditory_nerve is not None
    assert isinstance(detailed_python_result.auditory_nerve, dict)
    assert detailed_python_result.auditory_nerve


def test_periodicity_pitch_can_be_requested() -> None:
    result = leman2000(
        input_file=example_wav_path(),
        local_decay_sec=0.1,
        global_decay_sec=1.0,
        keep_periodicity_pitch=True,
        backend="octave",
        show_progress=False,
    )
    assert result.periodicity_pitch is not None
    assert isinstance(result.periodicity_pitch, dict)
    assert result.periodicity_pitch
