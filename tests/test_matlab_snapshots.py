"""Smoke tests: compiled MATLAB backend vs archived R snapshots.

These require the published MATLAB Runtime worker image
(``ghcr.io/cms-cambridge/pyleman2000-matlab:dev`` or a local retag). They are
intentionally separate from the Octave ``integration`` marker so CI can pull
the MATLAB image without rebuilding it (MathWorks Compiler is not available
on GitHub-hosted runners).
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from pyleman2000 import Leman2000Session, example_wav_path
from tests.docker_support import docker_daemon_available

# Same tolerances as the Octave snapshot suite.
SNAPSHOT_RTOL = 1e-5
SNAPSHOT_ATOL = 1e-5

pytestmark = [
    pytest.mark.matlab,
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
def matlab_result():
    with Leman2000Session(backend="matlab", show_progress=False) as session:
        return session.run(
            input_file=example_wav_path(),
            local_decay_sec=LOCAL_DECAY,
            global_decay_sec=GLOBAL_DECAY,
            windows=WINDOWS,
        )


def test_matlab_metadata_matches_r(matlab_result) -> None:
    expected = pd.read_csv(SNAPSHOT_DIR / "r_hihat_meta.csv").iloc[0]
    assert matlab_result.audio_length_sec == pytest.approx(
        float(expected["audio_length_sec"])
    )
    assert matlab_result.num_channels == int(expected["num_channels"])
    assert matlab_result.sample_rate == pytest.approx(float(expected["sample_rate"]))


def test_matlab_local_global_comparison_matches_r(matlab_result) -> None:
    expected = pd.read_csv(SNAPSHOT_DIR / "r_hihat_local_global_comparison.csv")
    actual = matlab_result.local_global_comparison
    keys = ["local_decay_sec", "global_decay_sec", "time_sec"]

    pd.testing.assert_frame_equal(
        actual[keys + ["running_correlation"]],
        expected[keys + ["running_correlation"]],
        check_dtype=False,
        rtol=SNAPSHOT_RTOL,
        atol=SNAPSHOT_ATOL,
    )


def test_matlab_windowed_comparison_matches_r(matlab_result) -> None:
    expected = pd.read_csv(
        SNAPSHOT_DIR / "r_hihat_windowed_local_global_comparison.csv"
    )
    actual = matlab_result.windowed_local_global_comparison
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
