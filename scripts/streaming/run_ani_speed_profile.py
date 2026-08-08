#!/usr/bin/env python3
"""Time batch IPEMCalcANI vs disk-spool streaming ANI/PP on musix."""

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REMOTE_REPO = "$HOME/git/pyLeman2000"
DEFAULT_REMOTE_IPEM = "$HOME/git/pyLeman2000/build/matlab/ipem/IPEMToolbox"
DEFAULT_MATLAB_ROOT = "$HOME/MATLAB/R2026a"
ARTIFACT_DIR = REPO_ROOT / "artifacts" / "benchmark"


def _expand_remote(host: str, path_expr: str) -> str:
    remote = (
        "python3 -c "
        + shlex.quote(f"import os; print(os.path.expandvars({path_expr!r}))")
    )
    return subprocess.check_output(
        ["ssh", "-o", "BatchMode=yes", host, remote],
        text=True,
    ).strip()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", required=True)
    parser.add_argument("--durations", type=float, nargs="+", default=[5.0, 30.0])
    parser.add_argument("--chunk-len", type=int, default=1024)
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--remote-repo", default=DEFAULT_REMOTE_REPO)
    parser.add_argument("--toolbox-dir", default=DEFAULT_REMOTE_IPEM)
    parser.add_argument("--matlab-root", default=DEFAULT_MATLAB_ROOT)
    args = parser.parse_args(argv)

    remote_repo = _expand_remote(args.host, args.remote_repo)
    toolbox = _expand_remote(args.host, args.toolbox_dir)
    matlab_root = _expand_remote(args.host, args.matlab_root)

    for rel in ("docker/matlab", "scripts/streaming"):
        cmd = [
            "rsync",
            "-az",
            f"{REPO_ROOT / rel}/",
            f"{args.host}:{remote_repo}/{rel}/",
        ]
        print(shlex.join(cmd), file=sys.stderr)
        subprocess.check_call(cmd)

    dur_matlab = "[" + " ".join(str(d) for d in args.durations) + "]"
    remote_out = "/tmp/pyleman_ani_speed.json"
    local_tmp = ARTIFACT_DIR / "ani_speed_profile.remote.json"
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    expr = (
        f"addpath(fullfile('{remote_repo}','scripts','streaming')); "
        f"profile_ani_speed('ToolboxDir','{toolbox}',"
        f"'Durations',{dur_matlab},"
        f"'ChunkLen',{args.chunk_len},"
        f"'Repeats',{args.repeats},"
        f"'OutFile','{remote_out}');"
    )
    remote_script = f"""
set -euo pipefail
"{matlab_root}/bin/matlab" -batch {shlex.quote(expr)}
"""
    ssh_cmd = ["ssh", "-o", "BatchMode=yes", args.host, "bash", "-s"]
    print(shlex.join(ssh_cmd), file=sys.stderr)
    proc = subprocess.run(ssh_cmd, input=remote_script, text=True, check=False)
    if proc.returncode != 0:
        return proc.returncode

    subprocess.check_call(
        ["scp", "-q", f"{args.host}:{remote_out}", str(local_tmp)]
    )
    report = json.loads(local_tmp.read_text())
    local_tmp.unlink(missing_ok=True)
    report["collected_at"] = datetime.now(timezone.utc).isoformat()
    report["host"] = args.host

    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    json_path = ARTIFACT_DIR / "ani_speed_profile.json"
    md_path = ARTIFACT_DIR / "ani_speed_profile.md"
    json_path.write_text(json.dumps(report, indent=2) + "\n")

    lines = [
        "# ANI batch vs spool speed",
        "",
        f"Collected: `{report['collected_at']}`",
        "",
        f"- Host: `{args.host}`",
        f"- ChunkLen: `{report.get('chunk_len')}`",
        f"- Repeats: `{report.get('repeats')}`",
        "",
        "| Audio | Batch ANI | Spool+read ANI | ANI × | Batch ANI+PP | Spool→PP | ANI+PP × |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for case in report["cases"]:
        lines.append(
            "| {duration_sec:.1f} s | {batch_ani_sec:.3f} s | {stream_ani_sec:.3f} s | "
            "{ani_speedup:.2f}× | {batch_ani_pp_sec:.3f} s | {stream_ani_pp_sec:.3f} s | "
            "{ani_pp_speedup:.2f}× |".format(**case)
        )
    lines.extend(
        [
            "",
            "## Notes",
            "",
            "- Speedup > 1 means spool path is faster.",
            "- Spool path was built for memory, not wall-clock; expect similar or slower.",
            "",
        ]
    )
    md_path.write_text("\n".join(lines))
    print(md_path.read_text())
    print(f"Wrote {json_path} and {md_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
