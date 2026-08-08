"""Parity across backends and analysis detail levels.

Verifies that ``local_global_comparison`` is stable for:

- ``detail=0`` (disk-spool / default) vs ``detail=3`` (classic full-matrix)
  within each backend
- MATLAB vs Octave at the default ``detail=0`` path

These exercise the production Docker entrypoints (not the musix helper
harnesses). Cross-backend tolerance matches the R-snapshot budget; within-
backend detail switches stay near floating-point noise.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from pyleman2000 import DEFAULT_IMAGE, DEFAULT_MATLAB_IMAGE, example_wav_path
from pyleman2000.docker_runner import WarmModelRunner
from pyleman2000.formatters import format_local_global_comparison
from pyleman2000.matlab_worker import MatlabWorkerRunner
from tests.docker_support import docker_daemon_available
from tests.snapshot_support import (
    GLOBAL_DECAY,
    LOCAL_DECAY,
    SNAPSHOT_ATOL,
    SNAPSHOT_RTOL,
)

# Within one backend, spool vs classic should be near-exact.
DETAIL_RTOL = 1e-12
DETAIL_ATOL = 1e-12

COMPARISON_KEYS = ["local_decay_sec", "global_decay_sec", "time_sec"]
COMPARISON_COLS = COMPARISON_KEYS + ["running_correlation"]


def _image_present(image: str) -> bool:
    try:
        import docker
        from docker.errors import ImageNotFound
    except ImportError:
        return False
    client = docker.from_env()
    try:
        client.images.get(image)
        return True
    except ImageNotFound:
        return False
    except Exception:
        return False
    finally:
        try:
            client.close()
        except Exception:
            pass


def _run_comparison(
    *,
    backend: str,
    detail: int,
    image: str,
) -> pd.DataFrame:
    """Return formatted local/global correlations for one backend/detail."""
    path = Path(example_wav_path())
    if backend == "matlab":
        with MatlabWorkerRunner(
            image=image, show_progress=False
        ) as runner:
            raw = runner.run(
                path,
                LOCAL_DECAY,
                GLOBAL_DECAY,
                detail=detail,
            )
    elif backend == "octave":
        with WarmModelRunner(image=image, show_progress=False) as runner:
            raw = runner.run(
                path,
                LOCAL_DECAY,
                GLOBAL_DECAY,
                detail=detail,
            )
    else:
        raise ValueError(f"Unknown backend {backend!r}")

    assert isinstance(raw, dict)
    return format_local_global_comparison(
        raw["local_global_comparison"],
        float(raw["audio_length_sec"]),
    )


def _assert_comparisons_equal(
    left: pd.DataFrame,
    right: pd.DataFrame,
    *,
    rtol: float,
    atol: float,
) -> None:
    pd.testing.assert_frame_equal(
        left[COMPARISON_COLS].reset_index(drop=True),
        right[COMPARISON_COLS].reset_index(drop=True),
        check_dtype=False,
        rtol=rtol,
        atol=atol,
    )


@pytest.mark.integration
@pytest.mark.skipif(
    not docker_daemon_available(),
    reason="Docker daemon not available",
)
@pytest.mark.skipif(
    not _image_present(DEFAULT_IMAGE),
    reason=f"Octave image {DEFAULT_IMAGE!r} not present locally",
)
def test_octave_detail0_matches_detail3() -> None:
    detail0 = _run_comparison(
        backend="octave", detail=0, image=DEFAULT_IMAGE
    )
    detail3 = _run_comparison(
        backend="octave", detail=3, image=DEFAULT_IMAGE
    )
    _assert_comparisons_equal(
        detail0, detail3, rtol=DETAIL_RTOL, atol=DETAIL_ATOL
    )


@pytest.mark.matlab
@pytest.mark.skipif(
    not docker_daemon_available(),
    reason="Docker daemon not available",
)
@pytest.mark.skipif(
    not _image_present(DEFAULT_MATLAB_IMAGE),
    reason=f"MATLAB image {DEFAULT_MATLAB_IMAGE!r} not present locally",
)
def test_matlab_detail0_matches_detail3() -> None:
    detail0 = _run_comparison(
        backend="matlab", detail=0, image=DEFAULT_MATLAB_IMAGE
    )
    detail3 = _run_comparison(
        backend="matlab", detail=3, image=DEFAULT_MATLAB_IMAGE
    )
    _assert_comparisons_equal(
        detail0, detail3, rtol=DETAIL_RTOL, atol=DETAIL_ATOL
    )


@pytest.mark.integration
@pytest.mark.matlab
@pytest.mark.skipif(
    not docker_daemon_available(),
    reason="Docker daemon not available",
)
@pytest.mark.skipif(
    not _image_present(DEFAULT_MATLAB_IMAGE),
    reason=f"MATLAB image {DEFAULT_MATLAB_IMAGE!r} not present locally",
)
@pytest.mark.skipif(
    not _image_present(DEFAULT_IMAGE),
    reason=f"Octave image {DEFAULT_IMAGE!r} not present locally",
)
def test_matlab_matches_octave_at_detail0() -> None:
    matlab = _run_comparison(
        backend="matlab", detail=0, image=DEFAULT_MATLAB_IMAGE
    )
    octave = _run_comparison(
        backend="octave", detail=0, image=DEFAULT_IMAGE
    )
    _assert_comparisons_equal(
        matlab, octave, rtol=SNAPSHOT_RTOL, atol=SNAPSHOT_ATOL
    )


@pytest.mark.integration
@pytest.mark.matlab
@pytest.mark.skipif(
    not docker_daemon_available(),
    reason="Docker daemon not available",
)
@pytest.mark.skipif(
    not _image_present(DEFAULT_MATLAB_IMAGE),
    reason=f"MATLAB image {DEFAULT_MATLAB_IMAGE!r} not present locally",
)
@pytest.mark.skipif(
    not _image_present(DEFAULT_IMAGE),
    reason=f"Octave image {DEFAULT_IMAGE!r} not present locally",
)
def test_matlab_matches_octave_at_detail3() -> None:
    matlab = _run_comparison(
        backend="matlab", detail=3, image=DEFAULT_MATLAB_IMAGE
    )
    octave = _run_comparison(
        backend="octave", detail=3, image=DEFAULT_IMAGE
    )
    _assert_comparisons_equal(
        matlab, octave, rtol=SNAPSHOT_RTOL, atol=SNAPSHOT_ATOL
    )
