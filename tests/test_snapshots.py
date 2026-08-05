"""Snapshot tests comparing Octave output to archived R/MATLAB snapshots."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from pyleman2000 import example_wav_path, leman2000
from tests.docker_support import docker_daemon_available

# Octave agrees with the archived MATLAB/R snapshots to roughly 3e-6 on
# 44.1 kHz input; keep a little headroom for CI/platform variation.
SNAPSHOT_RTOL = 1e-5
SNAPSHOT_ATOL = 1e-5

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not docker_daemon_available(),
        reason="Docker daemon not available",
    ),
]

SNAPSHOT_DIR = Path(__file__).parent / "snapshots"

LOCAL_DECAY = [0.1, 0.2]
GLOBAL_DECAY = [1.0, 2.0]
WINDOWS = [(0.0, 0.1), (0.1, 0.2), (0.2, 0.3)]


@pytest.fixture(scope="module")
def python_result():
    return leman2000(
        input_file=example_wav_path(),
        local_decay_sec=LOCAL_DECAY,
        global_decay_sec=GLOBAL_DECAY,
        windows=WINDOWS,
        show_progress=False,
    )


@pytest.fixture(scope="module")
def detailed_python_result():
    return leman2000(
        input_file=example_wav_path(),
        local_decay_sec=LOCAL_DECAY,
        global_decay_sec=GLOBAL_DECAY,
        keep_auditory_nerve=True,
        show_progress=False,
    )


def test_metadata_matches_r(python_result) -> None:
    expected = pd.read_csv(SNAPSHOT_DIR / "r_hihat_meta.csv").iloc[0]
    assert python_result.audio_length_sec == pytest.approx(
        float(expected["audio_length_sec"])
    )
    assert python_result.num_channels == int(expected["num_channels"])
    assert python_result.sample_rate == pytest.approx(float(expected["sample_rate"]))


def test_local_global_comparison_matches_r(python_result) -> None:
    expected = pd.read_csv(SNAPSHOT_DIR / "r_hihat_local_global_comparison.csv")
    actual = python_result.local_global_comparison

    keys = ["local_decay_sec", "global_decay_sec", "time_sec"]

    pd.testing.assert_frame_equal(
        actual[keys + ["running_correlation"]],
        expected[keys + ["running_correlation"]],
        check_dtype=False,
        rtol=SNAPSHOT_RTOL,
        atol=SNAPSHOT_ATOL,
    )


def test_windowed_comparison_matches_r(python_result) -> None:
    # Values match for this fixture because no sample lands exactly on a
    # window boundary; Python closed intervals otherwise diverge from R.
    expected = pd.read_csv(
        SNAPSHOT_DIR / "r_hihat_windowed_local_global_comparison.csv"
    )
    actual = python_result.windowed_local_global_comparison
    assert actual is not None

    keys = ["local_decay_sec", "global_decay_sec", "window_id"]
    cols = keys + ["window_start", "window_end", "local_global_correlation"]

    pd.testing.assert_frame_equal(
        actual[cols],
        expected[cols],
        check_dtype=False,
        rtol=SNAPSHOT_RTOL,
        atol=SNAPSHOT_ATOL,
    )


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
        show_progress=False,
    )
    assert result.periodicity_pitch is not None
    assert isinstance(result.periodicity_pitch, dict)
    assert result.periodicity_pitch
