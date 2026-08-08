#!/usr/bin/env python3
"""Backward-compatible wrapper; prefer scripts/streaming/run_parity.py. """

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from run_parity import main  # noqa: E402


if __name__ == "__main__":
    argv = ["contextuality", *sys.argv[1:]]
    raise SystemExit(main(argv))
