"""Integration tests that require Docker."""

from __future__ import annotations

import pytest

from pyleman2000 import example_wav_path, leman2000
from pyleman2000.docker_runner import DEFAULT_IMAGE

pytestmark = pytest.mark.integration


def test_leman2000_end_to_end() -> None:
    result = leman2000(
        input_file=example_wav_path(),
        local_decay_sec=[0.1, 0.2],
        global_decay_sec=[1.0, 2.0],
        windows=[(0.0, 0.1), (0.1, 0.2), (0.2, 0.3)],
        docker_image=DEFAULT_IMAGE,
    )

    combos = result.local_global_comparison[
        ["local_decay_sec", "global_decay_sec"]
    ].drop_duplicates()
    assert len(combos) == 4
    assert result.windowed_local_global_comparison is not None
    assert len(result.windowed_local_global_comparison) == 12
