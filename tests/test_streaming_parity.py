"""Optional MATLAB streaming parity checks.

Requires SSH access to a host with MATLAB + the pinned IPEM checkout.
Set ``PYLEMAN2000_MATLAB_HOST`` (e.g. ``pmch2@musix.mus.cam.ac.uk``).
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
DRIVER = REPO_ROOT / "scripts" / "streaming" / "run_parity.py"
HOST = os.environ.get("PYLEMAN2000_MATLAB_HOST", "").strip()

pytestmark = [
    pytest.mark.matlab,
    pytest.mark.skipif(
        not HOST,
        reason="Set PYLEMAN2000_MATLAB_HOST to run streaming parity on MATLAB",
    ),
]


@pytest.mark.parametrize(
    "harness",
    ["ani", "compute", "contextuality", "periodicity", "pipeline"],
)
def test_streaming_parity(harness: str) -> None:
    proc = subprocess.run(
        [sys.executable, str(DRIVER), harness, "--host", HOST],
        cwd=REPO_ROOT,
        check=False,
    )
    assert proc.returncode == 0
