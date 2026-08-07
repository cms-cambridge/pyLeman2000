"""Tests that published Docker images stay within size budgets."""

from __future__ import annotations

import pytest

from pyleman2000 import DEFAULT_IMAGE, DEFAULT_MATLAB_IMAGE
from pyleman2000.progress import format_bytes
from pyleman2000.worker_sizing import (
    MATLAB_IMAGE_SIZE_MAX_BYTES,
    MATLAB_IMAGE_SIZE_MIN_BYTES,
    OCTAVE_IMAGE_SIZE_MAX_BYTES,
    OCTAVE_IMAGE_SIZE_MIN_BYTES,
)
from tests.docker_support import (
    docker_daemon_available,
    docker_image_size_bytes,
    image_size_bytes,
)


def test_image_size_bytes_reads_inspect_payload() -> None:
    assert image_size_bytes({"Size": 3_800_000_000}) == 3_800_000_000


def test_image_size_bytes_rejects_negative() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        image_size_bytes({"Size": -1})


@pytest.mark.matlab
@pytest.mark.skipif(
    not docker_daemon_available(),
    reason="Docker daemon not available",
)
def test_matlab_image_size_within_budget() -> None:
    """DEFAULT_MATLAB_IMAGE must stay near the ~3.8 GiB packaging size.

    Auto-sizing assumes a multi-GB but bounded MATLAB Runtime footprint. If
    packaging accidentally pulls in the full ~7.7 GiB Runtime, this fails.
    """
    size = docker_image_size_bytes(DEFAULT_MATLAB_IMAGE)
    assert MATLAB_IMAGE_SIZE_MIN_BYTES <= size <= MATLAB_IMAGE_SIZE_MAX_BYTES, (
        f"MATLAB image {DEFAULT_MATLAB_IMAGE!r} is {format_bytes(size)}; "
        f"expected between {format_bytes(MATLAB_IMAGE_SIZE_MIN_BYTES)} and "
        f"{format_bytes(MATLAB_IMAGE_SIZE_MAX_BYTES)}"
    )


@pytest.mark.integration
@pytest.mark.skipif(
    not docker_daemon_available(),
    reason="Docker daemon not available",
)
def test_octave_image_size_within_budget() -> None:
    """DEFAULT_IMAGE (Octave) must stay near the ~4.4 GiB packaging size."""
    size = docker_image_size_bytes(DEFAULT_IMAGE)
    assert OCTAVE_IMAGE_SIZE_MIN_BYTES <= size <= OCTAVE_IMAGE_SIZE_MAX_BYTES, (
        f"Octave image {DEFAULT_IMAGE!r} is {format_bytes(size)}; "
        f"expected between {format_bytes(OCTAVE_IMAGE_SIZE_MIN_BYTES)} and "
        f"{format_bytes(OCTAVE_IMAGE_SIZE_MAX_BYTES)}"
    )
