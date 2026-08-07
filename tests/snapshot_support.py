"""Shared R-snapshot fixtures and assertions for Octave and MATLAB backends."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from pyleman2000 import Leman2000Result

# Backends agree with the archived MATLAB/R snapshots to roughly 3e-6 on
# 44.1 kHz input; keep a little headroom for CI/platform variation.
SNAPSHOT_RTOL = 1e-5
SNAPSHOT_ATOL = 1e-5

SNAPSHOT_DIR = Path(__file__).parent / "snapshots"

LOCAL_DECAY = [0.1, 0.2]
GLOBAL_DECAY = [1.0, 2.0]
WINDOWS = [(0.0, 0.1), (0.1, 0.2), (0.2, 0.3)]


def assert_metadata_matches_r(result: Leman2000Result) -> None:
    expected = pd.read_csv(SNAPSHOT_DIR / "r_hihat_meta.csv").iloc[0]
    assert result.audio_length_sec == pytest.approx(float(expected["audio_length_sec"]))
    assert result.num_channels == int(expected["num_channels"])
    assert result.sample_rate == pytest.approx(float(expected["sample_rate"]))


def assert_local_global_comparison_matches_r(result: Leman2000Result) -> None:
    expected = pd.read_csv(SNAPSHOT_DIR / "r_hihat_local_global_comparison.csv")
    keys = ["local_decay_sec", "global_decay_sec", "time_sec"]
    pd.testing.assert_frame_equal(
        result.local_global_comparison[keys + ["running_correlation"]],
        expected[keys + ["running_correlation"]],
        check_dtype=False,
        rtol=SNAPSHOT_RTOL,
        atol=SNAPSHOT_ATOL,
    )


def assert_windowed_comparison_matches_r(result: Leman2000Result) -> None:
    # Values match for this fixture because no sample lands exactly on a
    # window boundary; Python closed intervals otherwise diverge from R.
    expected = pd.read_csv(
        SNAPSHOT_DIR / "r_hihat_windowed_local_global_comparison.csv"
    )
    actual = result.windowed_local_global_comparison
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
