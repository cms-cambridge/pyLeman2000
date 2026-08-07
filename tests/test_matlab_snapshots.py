"""Smoke tests: compiled MATLAB backend vs archived R snapshots.

These require the published MATLAB Runtime worker image (digest-pinned as
``DEFAULT_MATLAB_IMAGE``, also tagged ``:0.1.0`` / ``:dev``). They are
intentionally separate from the Octave ``integration`` marker so CI can pull
the MATLAB image without rebuilding it (MathWorks Compiler is not available
on GitHub-hosted runners).
"""

from __future__ import annotations

import pytest

from pyleman2000 import Leman2000Session, example_wav_path
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
    pytest.mark.matlab,
    pytest.mark.skipif(
        not docker_daemon_available(),
        reason="Docker daemon not available",
    ),
]


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
    assert_metadata_matches_r(matlab_result)


def test_matlab_local_global_comparison_matches_r(matlab_result) -> None:
    assert_local_global_comparison_matches_r(matlab_result)


def test_matlab_windowed_comparison_matches_r(matlab_result) -> None:
    assert_windowed_comparison_matches_r(matlab_result)
