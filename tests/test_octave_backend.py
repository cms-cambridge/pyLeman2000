"""Octave-backend integration checks (license-free Docker image)."""

from __future__ import annotations

import math

import pytest

from pyleman2000 import DEFAULT_OCTAVE_IMAGE, example_wav_path, leman2000
from pyleman2000.docker_runner import Leman2000DockerError


pytestmark = pytest.mark.integration


def _octave_image_available() -> bool:
    try:
        import docker

        client = docker.from_env()
        try:
            client.images.get(DEFAULT_OCTAVE_IMAGE)
            return True
        except Exception:
            return False
        finally:
            client.close()
    except Exception:
        return False


@pytest.mark.skipif(
    not _octave_image_available(),
    reason=f"Octave image {DEFAULT_OCTAVE_IMAGE!r} not built "
    "(run scripts/build_octave_image.sh)",
)
def test_octave_backend_end_to_end() -> None:
    try:
        result = leman2000(
            input_file=example_wav_path(),
            local_decay_sec=[0.1, 0.2],
            global_decay_sec=[1.0, 2.0],
            windows=[(0.0, 0.1), (0.1, 0.2), (0.2, 0.3)],
            docker_image=DEFAULT_OCTAVE_IMAGE,
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

    # First correlation should be exactly 1.0 for each combo.
    first_rows = result.local_global_comparison.groupby(
        ["local_decay_sec", "global_decay_sec"], sort=False
    ).first()
    assert (first_rows["running_correlation"] == 1.0).all()
