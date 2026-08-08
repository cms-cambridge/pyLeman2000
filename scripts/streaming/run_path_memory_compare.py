#!/usr/bin/env python3
"""Compare peak memory for batch vs spool ANI→PP→contextuality paths.

Runs each (duration, mode) in a fresh MATLAB process.
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
HIHAT = REPO_ROOT / "src" / "pyleman2000" / "data" / "hihat.wav"


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


def run_one(
    *,
    host: str,
    remote_repo: str,
    toolbox: str,
    matlab_root: str,
    wav_name: str,
    local_wav: Path,
    mode: str,
    chunk_len: int,
) -> dict:
    remote_wav = f"{remote_repo}/artifacts/benchmark/{wav_name}"
    remote_out = f"{remote_repo}/artifacts/benchmark/_pathmem_{mode}_{wav_name}.json"
    subprocess.check_call(
        ["rsync", "-az", str(local_wav), f"{host}:{remote_wav}"]
    )
    expr = (
        f"addpath(fullfile('{remote_repo}','scripts','streaming')); "
        f"profile_path_memory('ToolboxDir','{toolbox}',"
        f"'InputFile','{remote_wav}','Mode','{mode}',"
        f"'ChunkLen',{chunk_len},'OutFile','{remote_out}');"
    )
    remote_script = f"""
set -euo pipefail
mkdir -p {shlex.quote(remote_repo + "/artifacts/benchmark")}
"{matlab_root}/bin/matlab" -batch {shlex.quote(expr)}
"""
    print(f"==> {mode} {wav_name}", flush=True)
    proc = subprocess.run(
        ["ssh", "-o", "BatchMode=yes", host, "bash", "-s"],
        input=remote_script,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"{mode} {wav_name} failed with {proc.returncode}")

    local_tmp = ARTIFACT_DIR / f"_pathmem_{mode}_{wav_name}.json"
    subprocess.check_call(["scp", "-q", f"{host}:{remote_out}", str(local_tmp)])
    report = json.loads(local_tmp.read_text())
    local_tmp.unlink(missing_ok=True)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", required=True)
    parser.add_argument("--durations", type=float, nargs="+", default=[30.0, 120.0])
    parser.add_argument("--chunk-len", type=int, default=1024)
    parser.add_argument("--remote-repo", default=DEFAULT_REMOTE_REPO)
    parser.add_argument("--toolbox-dir", default=DEFAULT_REMOTE_IPEM)
    parser.add_argument("--matlab-root", default=DEFAULT_MATLAB_ROOT)
    parser.add_argument("--hihat", type=Path, default=HIHAT)
    args = parser.parse_args(argv)

    if not args.hihat.is_file():
        # Fall back to any short wav under tests
        candidates = list((REPO_ROOT / "tests").rglob("*.wav"))
        if not candidates:
            raise SystemExit(f"No hihat wav at {args.hihat}")
        args.hihat = candidates[0]

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
        print(shlex.join(cmd), flush=True)
        subprocess.check_call(cmd)

    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    cases = []
    for dur in args.durations:
        wav_name = f"profile_{int(dur)}s_tiled_hihat.wav"
        local_wav = ARTIFACT_DIR / wav_name
        tile_wav(args.hihat, local_wav, dur)
        row = {"duration_sec_target": dur, "wav": wav_name, "modes": {}}
        for mode in ("batch", "spool"):
            report = run_one(
                host=args.host,
                remote_repo=remote_repo,
                toolbox=toolbox,
                matlab_root=matlab_root,
                wav_name=wav_name,
                local_wav=local_wav,
                mode=mode,
                chunk_len=args.chunk_len,
            )
            row["modes"][mode] = report
            row["audio_length_sec"] = report["audio_length_sec"]
        cases.append(row)

    summary = {
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "host": args.host,
        "chunk_len": args.chunk_len,
        "cases": cases,
    }
    json_path = ARTIFACT_DIR / "path_memory_compare.json"
    md_path = ARTIFACT_DIR / "path_memory_compare.md"
    json_path.write_text(json.dumps(summary, indent=2) + "\n")

    lines = [
        "# Batch vs spool path memory",
        "",
        f"Collected: `{summary['collected_at']}`",
        "",
        f"- Host: `{args.host}`",
        f"- ChunkLen: `{args.chunk_len}`",
        "- Each mode runs in a fresh MATLAB process",
        "",
        "## Peak PSS",
        "",
        "| Audio | Batch peak PSS | Spool peak PSS | Δ (spool − batch) | Batch Δ vs baseline | Spool Δ vs baseline |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for case in cases:
        b = case["modes"]["batch"]
        s = case["modes"]["spool"]
        lines.append(
            "| {audio:.1f} s | {bp:.0f} MB | {sp:.0f} MB | {d:+.0f} MB | "
            "{bd:.0f} MB | {sd:.0f} MB |".format(
                audio=case["audio_length_sec"],
                bp=b["peak_pss_mb"],
                sp=s["peak_pss_mb"],
                d=s["peak_pss_mb"] - b["peak_pss_mb"],
                bd=b["delta_peak_pss_mb"],
                sd=s["delta_peak_pss_mb"],
            )
        )

    lines.extend(["", "## Stages (PSS, MB)", ""])
    for case in cases:
        audio = case["audio_length_sec"]
        lines.append(f"### {audio:.1f} s")
        lines.append("")
        lines.append("| Stage | Batch | Spool |")
        lines.append("| --- | ---: | ---: |")
        b_stages = {st["name"]: st["pss_mb"] for st in case["modes"]["batch"]["stages"]}
        s_stages = {st["name"]: st["pss_mb"] for st in case["modes"]["spool"]["stages"]}
        names = []
        for st in case["modes"]["batch"]["stages"]:
            names.append(st["name"])
        for st in case["modes"]["spool"]["stages"]:
            if st["name"] not in names:
                names.append(st["name"])
        for name in names:
            bv = b_stages.get(name)
            sv = s_stages.get(name)
            btxt = f"{bv:.0f}" if bv is not None else "—"
            stxt = f"{sv:.0f}" if sv is not None else "—"
            lines.append(f"| {name} | {btxt} | {stxt} |")
        lines.append("")

    lines.extend(
        [
            "## Notes",
            "",
            "- PSS from `/proc/self/smaps_rollup` at stage boundaries.",
            "- Spool path never `textread`s the full `.ani`; PP uses chunked FANI.",
            "- MATLAB may retain freed heap; prefer peak and Δ-vs-baseline.",
            "",
        ]
    )
    md_path.write_text("\n".join(lines))
    print(md_path.read_text())
    print(f"Wrote {json_path} and {md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
