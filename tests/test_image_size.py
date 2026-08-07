"""Tests that published Docker images stay within size and memory budgets."""

from __future__ import annotations

import pytest

from pyleman2000 import DEFAULT_IMAGE, DEFAULT_MATLAB_IMAGE, example_wav_path
from pyleman2000.docker_runner import WarmModelRunner
from pyleman2000.matlab_worker import MatlabWorkerRunner
from pyleman2000.progress import format_bytes
from pyleman2000.worker_sizing import (
    MATLAB_IMAGE_SIZE_MAX_BYTES,
    MATLAB_IMAGE_SIZE_MIN_BYTES,
    MATLAB_RAM_PER_WORKER_BYTES,
    MATLAB_WARM_RSS_MIN_BYTES,
    OCTAVE_IMAGE_SIZE_MAX_BYTES,
    OCTAVE_IMAGE_SIZE_MIN_BYTES,
    OCTAVE_RAM_PER_WORKER_BYTES,
    OCTAVE_WARM_RSS_MIN_BYTES,
)
from tests.docker_support import (
    container_memory_usage_bytes,
    docker_daemon_available,
    docker_image_size_bytes,
    image_size_bytes,
)


def test_image_size_bytes_reads_inspect_payload() -> None:
    assert image_size_bytes({"Size": 3_800_000_000}) == 3_800_000_000


def test_image_size_bytes_rejects_negative() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        image_size_bytes({"Size": -1})


def test_container_memory_usage_subtracts_cgroup_v1_cache() -> None:
    stats = {
        "memory_stats": {
            "usage": 1_000_000_000,
            "stats": {"cache": 200_000_000},
        }
    }
    assert container_memory_usage_bytes(stats) == 800_000_000


def test_container_memory_usage_prefers_cgroup_v2_inactive_file() -> None:
    stats = {
        "memory_stats": {
            "usage": 1_000_000_000,
            "stats": {"inactive_file": 150_000_000, "cache": 999_000_000},
        }
    }
    assert container_memory_usage_bytes(stats) == 850_000_000


def test_container_memory_usage_falls_back_to_raw_usage() -> None:
    assert container_memory_usage_bytes({"memory_stats": {"usage": 42}}) == 42


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


@pytest.mark.matlab
@pytest.mark.skipif(
    not docker_daemon_available(),
    reason="Docker daemon not available",
)
def test_matlab_warm_container_rss_within_budget() -> None:
    """A ready MATLAB worker must fit under the per-worker RSS budget."""
    with MatlabWorkerRunner(
        image=DEFAULT_MATLAB_IMAGE, show_progress=False
    ) as runner:
        runner.run(
            example_wav_path(),
            local_decay_sec=[0.1],
            global_decay_sec=[1.0],
            detail=0,
        )
        assert runner._container is not None
        stats = runner._container.stats(stream=False)
        usage = container_memory_usage_bytes(stats)

    assert MATLAB_WARM_RSS_MIN_BYTES <= usage <= MATLAB_RAM_PER_WORKER_BYTES, (
        f"MATLAB warm worker used {format_bytes(usage)}; expected between "
        f"{format_bytes(MATLAB_WARM_RSS_MIN_BYTES)} and "
        f"{format_bytes(MATLAB_RAM_PER_WORKER_BYTES)}"
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


@pytest.mark.integration
@pytest.mark.skipif(
    not docker_daemon_available(),
    reason="Docker daemon not available",
)
def test_octave_warm_container_rss_within_budget() -> None:
    """Peak Octave memory during a run must fit the per-worker RSS budget.

    Octave exits after each ``docker exec``, so we sample stats while the
    analysis is in flight rather than after it returns.
    """
    import threading
    import time

    peak = 0
    stop = threading.Event()

    with WarmModelRunner(image=DEFAULT_IMAGE, show_progress=False) as runner:
        assert runner._container is not None
        container = runner._container

        def _watch() -> None:
            nonlocal peak
            while not stop.is_set():
                try:
                    usage = container_memory_usage_bytes(
                        container.stats(stream=False)
                    )
                except Exception:
                    time.sleep(0.2)
                    continue
                peak = max(peak, usage)
                time.sleep(0.2)

        watcher = threading.Thread(target=_watch, daemon=True)
        watcher.start()
        try:
            runner.run(
                example_wav_path(),
                local_decay_sec=[0.1],
                global_decay_sec=[1.0],
                detail=0,
            )
            # One more sample after completion in case the peak was brief.
            time.sleep(0.3)
        finally:
            stop.set()
            watcher.join(timeout=5.0)

    assert OCTAVE_WARM_RSS_MIN_BYTES <= peak <= OCTAVE_RAM_PER_WORKER_BYTES, (
        f"Octave warm container peak was {format_bytes(peak)}; expected "
        f"between {format_bytes(OCTAVE_WARM_RSS_MIN_BYTES)} and "
        f"{format_bytes(OCTAVE_RAM_PER_WORKER_BYTES)}"
    )
