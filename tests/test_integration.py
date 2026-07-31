"""Optional integration tests that require Docker."""

from __future__ import annotations

import pytest

docker = pytest.importorskip("docker")

from pyleman2000 import leman2000
from pyleman2000.api import example_wav_path
from pyleman2000.docker_runner import DEFAULT_IMAGE, Leman2000DockerError


def _docker_available() -> bool:
    try:
        client = docker.from_env()
        client.ping()
        client.close()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.integration


@pytest.mark.skipif(not _docker_available(), reason="Docker daemon not available")
def test_leman2000_end_to_end() -> None:
    try:
        result = leman2000(
            input_file=example_wav_path(),
            local_decay_sec=[0.1, 0.2],
            global_decay_sec=[1.0, 2.0],
            windows=[(0.0, 0.1), (0.1, 0.2), (0.2, 0.3)],
            docker_image=DEFAULT_IMAGE,
        )
    except Leman2000DockerError as exc:
        pytest.skip(f"Docker model unavailable: {exc}")

    combos = result.local_global_comparison[
        ["local_decay_sec", "global_decay_sec"]
    ].drop_duplicates()
    assert len(combos) == 4
    assert result.windowed_local_global_comparison is not None
    assert len(result.windowed_local_global_comparison) == 12
