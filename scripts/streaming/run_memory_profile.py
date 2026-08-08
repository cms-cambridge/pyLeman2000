#!/usr/bin/env python3
"""Profile per-stage MATLAB memory for tiled hi-hat WAVs on musix.

Example::

    python scripts/streaming/run_memory_profile.py \\
        --host pmch2@musix.mus.cam.ac.uk \\
        --durations 5 30 60
"""

from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import wave
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


def tile_wav(source: Path, target: Path, target_sec: float) -> Path:
    if target.exists():
        return target
    with wave.open(str(source), "rb") as src:
        params = src.getparams()
        frames = src.readframes(params.nframes)
    repeats = max(1, round(target_sec * params.framerate / params.nframes))
    target.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(target), "wb") as dst:
        dst.setparams(params)
        dst.writeframes(frames * repeats)
    return target


def sync_sources(host: str, remote_repo: str) -> None:
    for rel in ("docker/matlab", "scripts/streaming"):
        cmd = [
            "rsync",
            "-az",
            f"{REPO_ROOT / rel}/",
            f"{host}:{remote_repo}/{rel}/",
        ]
        print(shlex.join(cmd), flush=True)
        subprocess.check_call(cmd)


def run_one(
    *,
    host: str,
    remote_repo: str,
    toolbox: str,
    matlab_root: str,
    wav_name: str,
    local_wav: Path,
    abs_tol_unused: float = 0.0,
) -> dict:
    del abs_tol_unused
    remote_wav = f"{remote_repo}/artifacts/benchmark/{wav_name}"
    remote_out = f"{remote_repo}/artifacts/benchmark/_profile_{wav_name}.json"
    subprocess.check_call(
        [
            "rsync",
            "-az",
            str(local_wav),
            f"{host}:{remote_repo}/artifacts/benchmark/{wav_name}",
        ]
    )

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
WAV={shlex.quote(remote_wav)}
OUT={shlex.quote(remote_out)}
mkdir -p "$REPO/artifacts/benchmark"
EXPR="addpath(fullfile('$REPO', 'scripts', 'streaming')); profile_stage_memory('ToolboxDir', '$IPEM', 'InputFile', '$WAV', 'OutFile', '$OUT');"
"$MATLAB_ROOT/bin/matlab" -batch "$EXPR"
"""
    subprocess.run(
        ["ssh", "-o", "BatchMode=yes", host, "bash", "-s"],
        input=remote_script,
        text=True,
        check=True,
    )
    payload = subprocess.check_output(
        ["ssh", "-o", "BatchMode=yes", host, f"cat {shlex.quote(remote_out)}"],
        text=True,
    )
    return json.loads(payload)


def to_markdown(summary: dict) -> str:
    lines = [
        "# Stage memory profile",
        "",
        f"Collected: `{summary['collected_at']}`",
        "",
        f"- Host: `{summary['host']}`",
        f"- MATLAB source mode against pinned IPEM",
        f"- Params: local={summary['local_decay_sec']}, "
        f"global={summary['global_decay_sec']}",
        "",
        "## Peak by audio length",
        "",
        "| Audio | Peak RSS | Peak PSS |",
        "| --- | ---: | ---: |",
    ]
    for run in summary["runs"]:
        lines.append(
            f"| {run['audio_length_sec']:.1f} s | "
            f"{run['peak_rss_mb']:.0f} MB | {run['peak_pss_mb']:.0f} MB |"
        )

    lines.extend(["", "## Stages (PSS, MB)", ""])
    stage_names = []
    for run in summary["runs"]:
        for stage in run["stages"]:
            if stage["name"] not in stage_names:
                stage_names.append(stage["name"])
    header = "| Stage | " + " | ".join(
        f"{run['audio_length_sec']:.0f}s" for run in summary["runs"]
    ) + " |"
    sep = "| --- | " + " | ".join("---:" for _ in summary["runs"]) + " |"
    lines.extend([header, sep])
    for name in stage_names:
        row = [name]
        for run in summary["runs"]:
            match = next((s for s in run["stages"] if s["name"] == name), None)
            row.append(f"{match['pss_mb']:.0f}" if match else "—")
        lines.append("| " + " | ".join(row) + " |")

    lines.extend(
        [
            "",
            "## Notes",
            "",
            "- RSS/PSS are sampled from `/proc/self` inside the MATLAB process.",
            "- `after_calc_ani` is the first point where the full ANI matrix exists.",
            "- `after_stream_*` runs streamed PP/contextuality while ANI is still held.",
            "- `after_periodicity_pitch` is the classic full-matrix PP path.",
            "",
        ]
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", required=True)
    parser.add_argument("--durations", type=float, nargs="+", default=[5, 30, 60])
    parser.add_argument("--remote-repo", default=DEFAULT_REMOTE_REPO)
    parser.add_argument("--toolbox-dir", default=DEFAULT_REMOTE_IPEM)
    parser.add_argument("--matlab-root", default=DEFAULT_MATLAB_ROOT)
    parser.add_argument("--local-decay-sec", type=float, default=0.1)
    parser.add_argument("--global-decay-sec", type=float, default=1.0)
    args = parser.parse_args(argv)

    remote_repo = _expand_remote(args.host, args.remote_repo)
    sync_sources(args.host, remote_repo)

    source = REPO_ROOT / "src" / "pyleman2000" / "data" / "hihat.wav"
    runs = []
    for dur in args.durations:
        wav_name = f"profile_{int(dur)}s_tiled_hihat.wav"
        local_wav = ARTIFACT_DIR / wav_name
        tile_wav(source, local_wav, dur)
        print(f"==> profiling {dur}s", flush=True)
        report = run_one(
            host=args.host,
            remote_repo=remote_repo,
            toolbox=args.toolbox_dir,
            matlab_root=args.matlab_root,
            wav_name=wav_name,
            local_wav=local_wav,
        )
        runs.append(report)

    summary = {
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "host": args.host,
        "local_decay_sec": args.local_decay_sec,
        "global_decay_sec": args.global_decay_sec,
        "runs": runs,
    }
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    json_path = ARTIFACT_DIR / "stage_memory_profile.json"
    md_path = ARTIFACT_DIR / "stage_memory_profile.md"
    json_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    md_path.write_text(to_markdown(summary), encoding="utf-8")
    print(md_path.read_text(encoding="utf-8"))
    print(f"Wrote {json_path} and {md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
