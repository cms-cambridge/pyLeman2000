#!/usr/bin/env python3
"""Run MATLAB streaming parity harnesses on musix (or locally).

Examples
--------
    python scripts/streaming/run_parity.py contextuality \\
        --host pmch2@musix.mus.cam.ac.uk
    python scripts/streaming/run_parity.py periodicity \\
        --host pmch2@musix.mus.cam.ac.uk
    python scripts/streaming/run_parity.py pipeline \\
        --host pmch2@musix.mus.cam.ac.uk
    python scripts/streaming/run_parity.py ani \\
        --host pmch2@musix.mus.cam.ac.uk
"""

from __future__ import annotations

import argparse
import os
import shlex
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REMOTE_REPO = "$HOME/git/pyLeman2000"
DEFAULT_REMOTE_IPEM = "$HOME/git/pyLeman2000/build/matlab/ipem/IPEMToolbox"
DEFAULT_MATLAB_ROOT = "$HOME/MATLAB/R2026a"

HARNESSES = {
    "ani": "run_ani_parity",
    "compute": "run_compute_spool_parity",
    "contextuality": "run_contextuality_parity",
    "periodicity": "run_periodicity_parity",
    "pipeline": "run_pipeline_parity",
}


def _expand_remote(host: str, path_expr: str) -> str:
    remote = (
        "python3 -c "
        + shlex.quote(f"import os; print(os.path.expandvars({path_expr!r}))")
    )
    return subprocess.check_output(
        ["ssh", "-o", "BatchMode=yes", host, remote],
        text=True,
    ).strip()


def run_local(args: argparse.Namespace) -> int:
    matlab_root = Path(
        os.environ.get("MATLAB_ROOT", str(Path.home() / "MATLAB" / "R2026a"))
    ).expanduser()
    matlab_bin = matlab_root / "bin" / "matlab"
    matlab_bin_s = str(matlab_bin) if matlab_bin.is_file() else "matlab"
    toolbox = str(Path(args.toolbox_dir).expanduser().resolve())
    fn = HARNESSES[args.harness]
    expr = (
        f"addpath(fullfile('{REPO_ROOT}', 'scripts', 'streaming')); "
        f"{fn}('ToolboxDir', '{toolbox}', 'AbsTol', {args.abs_tol:g});"
    )
    cmd = [matlab_bin_s, "-batch", expr]
    print(shlex.join(cmd), file=sys.stderr)
    return subprocess.call(cmd)


def run_remote(args: argparse.Namespace) -> int:
    remote_repo = _expand_remote(args.host, args.remote_repo)
    toolbox = args.toolbox_dir or DEFAULT_REMOTE_IPEM
    matlab_root = args.matlab_root
    fn = HARNESSES[args.harness]

    for rel in ("docker/matlab", "scripts/streaming"):
        cmd = [
            "rsync",
            "-az",
            f"{REPO_ROOT / rel}/",
            f"{args.host}:{remote_repo}/{rel}/",
        ]
        print(shlex.join(cmd), file=sys.stderr)
        subprocess.check_call(cmd)

    expand_ipem = shlex.quote(
        f"import os; print(os.path.expandvars({toolbox!r}))"
    )
    expand_matlab = shlex.quote(
        f"import os; print(os.path.expandvars({matlab_root!r}))"
    )
    remote_script = f"""
set -euo pipefail
REPO={shlex.quote(remote_repo)}
IPEM=$(python3 -c {expand_ipem})
MATLAB_ROOT=$(python3 -c {expand_matlab})
EXPR="addpath(fullfile('$REPO', 'scripts', 'streaming')); {fn}('ToolboxDir', '$IPEM', 'AbsTol', {args.abs_tol:g});"
"$MATLAB_ROOT/bin/matlab" -batch "$EXPR"
"""
    ssh_cmd = ["ssh", "-o", "BatchMode=yes", args.host, "bash", "-s"]
    print(shlex.join(ssh_cmd), file=sys.stderr)
    return subprocess.run(ssh_cmd, input=remote_script, text=True).returncode


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "harness",
        choices=sorted(HARNESSES),
        help="Which parity harness to run",
    )
    parser.add_argument("--host", default=None)
    parser.add_argument("--toolbox-dir", default=None)
    parser.add_argument("--remote-repo", default=DEFAULT_REMOTE_REPO)
    parser.add_argument("--matlab-root", default=DEFAULT_MATLAB_ROOT)
    parser.add_argument("--abs-tol", type=float, default=1e-12)
    args = parser.parse_args(argv)

    if args.host:
        return run_remote(args)
    if args.toolbox_dir is None:
        parser.error("--toolbox-dir is required for local runs")
    return run_local(args)


if __name__ == "__main__":
    raise SystemExit(main())
