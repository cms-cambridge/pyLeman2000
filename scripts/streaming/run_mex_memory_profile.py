#!/usr/bin/env python3
"""Measure peak RSS/PSS during IPEMProcessAuditoryModelSafe (no textread).

Polls /proc/<matlab-pid>/smaps_rollup while the mex runs.

Example::

    python scripts/streaming/run_mex_memory_profile.py \\
        --host pmch2@musix.mus.cam.ac.uk \\
        --durations 30 120
"""

from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import time
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
) -> dict:
    remote_wav = f"{remote_repo}/artifacts/benchmark/{wav_name}"
    remote_out = f"{remote_repo}/artifacts/benchmark/_mex_profile_{wav_name}.json"
    work = f"/tmp/pyleman_mex_profile_{wav_name}"
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
WORK={shlex.quote(work)}
rm -rf "$WORK"
mkdir -p "$WORK" "$REPO/artifacts/benchmark"
PID_FILE="$WORK/pid"
GO_FILE="$WORK/go"
STATUS_FILE="$WORK/status"
SAMPLE_FILE="$WORK/samples.jsonl"
rm -f "$PID_FILE" "$GO_FILE" "$STATUS_FILE" "$SAMPLE_FILE"

EXPR="addpath(fullfile('$REPO', 'scripts', 'streaming')); profile_mex_memory('ToolboxDir', '$IPEM', 'InputFile', '$WAV', 'OutFile', '$OUT', 'PidFile', '$PID_FILE', 'GoFile', '$GO_FILE', 'StatusFile', '$STATUS_FILE');"
"$MATLAB_ROOT/bin/matlab" -batch "$EXPR" >"$WORK/matlab.log" 2>&1 &
MPID=$!

# Wait until MATLAB publishes its worker PID and ready status.
deadline=$((SECONDS+180))
while [[ ! -f "$PID_FILE" || ! -f "$STATUS_FILE" ]]; do
  if ! kill -0 "$MPID" 2>/dev/null; then
    echo "MATLAB exited before ready" >&2
    cat "$WORK/matlab.log" >&2 || true
    exit 1
  fi
  if (( SECONDS > deadline )); then
    echo "timed out waiting for ready" >&2
    cat "$WORK/matlab.log" >&2 || true
    exit 1
  fi
  sleep 0.05
done
status=$(cat "$STATUS_FILE")
if [[ "$status" != "ready_for_mex" ]]; then
  echo "unexpected status before go: $status" >&2
  exit 1
fi
WPID=$(tr -d '[:space:]' < "$PID_FILE")

# Sample PSS/RSS while mex runs.
python3 - "$WPID" "$SAMPLE_FILE" "$STATUS_FILE" "$GO_FILE" <<'PY' &
import os, sys, time
pid, sample_file, status_file, go_file = sys.argv[1:]
open(go_file, "w").write("go\\n")
peak = {{"rss_kb": 0.0, "pss_kb": 0.0, "n": 0}}
with open(sample_file, "w", encoding="utf-8") as out:
    while True:
        if os.path.exists(status_file):
            status = open(status_file, encoding="utf-8").read().strip()
            if status == "mex_done":
                break
        rss = pss = None
        try:
            for line in open(f"/proc/{{pid}}/status", encoding="utf-8"):
                if line.startswith("VmRSS:"):
                    rss = float(line.split()[1])
                    break
        except FileNotFoundError:
            break
        try:
            for line in open(f"/proc/{{pid}}/smaps_rollup", encoding="utf-8"):
                if line.startswith("Pss:"):
                    pss = float(line.split()[1])
                    break
        except FileNotFoundError:
            pass
        if rss is not None:
            peak["rss_kb"] = max(peak["rss_kb"], rss)
            peak["n"] += 1
            if pss is not None:
                peak["pss_kb"] = max(peak["pss_kb"], pss)
            out.write(f"{{rss}},{{pss if pss is not None else ''}}\\n")
            out.flush()
        time.sleep(0.05)
open(sample_file + ".peak", "w", encoding="utf-8").write(
    f"{{peak['rss_kb']/1024}},{{peak['pss_kb']/1024}},{{peak['n']}}\\n"
)
PY
SAMPLER=$!

wait "$MPID"
MATLAB_RC=$?
wait "$SAMPLER" || true
if [[ "$MATLAB_RC" -ne 0 ]]; then
  echo "MATLAB failed" >&2
  cat "$WORK/matlab.log" >&2 || true
  exit "$MATLAB_RC"
fi

python3 - "$OUT" "$SAMPLE_FILE.peak" "$SAMPLE_FILE" <<'PY'
import json, sys
out_path, peak_path, samples_path = sys.argv[1:]
report = json.loads(open(out_path, encoding="utf-8").read())
rss_mb, pss_mb, n = open(peak_path, encoding="utf-8").read().strip().split(",")
report["polled_peak_rss_mb"] = float(rss_mb)
report["polled_peak_pss_mb"] = float(pss_mb)
report["poll_samples"] = int(n)
report["poll_sample_file"] = samples_path
json.dump(report, open(out_path, "w", encoding="utf-8"), indent=2)
print(
    f"POLLED_PEAK rss={{report['polled_peak_rss_mb']:.1f}}MB "
    f"pss={{report['polled_peak_pss_mb']:.1f}}MB samples={{report['poll_samples']}}"
)
PY
cat "$OUT"
"""
    proc = subprocess.run(
        ["ssh", "-o", "BatchMode=yes", host, "bash", "-s"],
        input=remote_script,
        text=True,
        check=True,
        capture_output=True,
    )
    print(proc.stderr, file=__import__("sys").stderr, end="")
    # Last JSON object in stdout is the report; matlab logs went to a file.
    text = proc.stdout.strip()
    # Find the final JSON document.
    start = text.rfind("{")
    if start < 0:
        raise RuntimeError(f"no JSON report in remote output:\n{text}")
    # Walk backward to the report beginning by brace matching from last '{'?
    # Simpler: remote script cats OUT at end; find first line starting with {
    lines = text.splitlines()
    json_start = next(i for i, line in enumerate(lines) if line.startswith("{"))
    return json.loads("\n".join(lines[json_start:]))


def to_markdown(summary: dict) -> str:
    lines = [
        "# Mex-only memory profile",
        "",
        f"Collected: `{summary['collected_at']}`",
        "",
        f"- Host: `{summary['host']}`",
        "- Measures `IPEMProcessAuditoryModelSafe` without loading `.ani`",
        "- External `/proc` poll every 50 ms during the mex call",
        "",
        "| Audio | Before mex PSS | After mex PSS | Polled peak PSS | ANI file |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for run in summary["runs"]:
        stages = {s["name"]: s for s in run["stages"]}
        before = stages["before_mex"]["pss_mb"]
        after = stages["after_mex_before_textread"]["pss_mb"]
        ani_mb = (run.get("ani_file_bytes") or 0) / 1024 / 1024
        lines.append(
            f"| {run['audio_length_sec']:.1f} s | {before:.0f} MB | "
            f"{after:.0f} MB | {run['polled_peak_pss_mb']:.0f} MB | "
            f"{ani_mb:.0f} MB |"
        )
    lines.extend(
        [
            "",
            "## Notes",
            "",
            "- If polled peak ≈ before/after mex, the mex itself is not the RAM hog.",
            "- Large `.ani` on disk with flat PSS supports disk-spooling.",
            "",
        ]
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", required=True)
    parser.add_argument("--durations", type=float, nargs="+", default=[30, 120])
    parser.add_argument("--remote-repo", default=DEFAULT_REMOTE_REPO)
    parser.add_argument("--toolbox-dir", default=DEFAULT_REMOTE_IPEM)
    parser.add_argument("--matlab-root", default=DEFAULT_MATLAB_ROOT)
    args = parser.parse_args(argv)

    remote_repo = _expand_remote(args.host, args.remote_repo)
    sync_sources(args.host, remote_repo)
    source = REPO_ROOT / "src" / "pyleman2000" / "data" / "hihat.wav"

    runs = []
    for dur in args.durations:
        wav_name = f"profile_{int(dur)}s_tiled_hihat.wav"
        local_wav = ARTIFACT_DIR / wav_name
        tile_wav(source, local_wav, dur)
        print(f"==> mex-profiling {dur}s", flush=True)
        report = run_one(
            host=args.host,
            remote_repo=remote_repo,
            toolbox=args.toolbox_dir,
            matlab_root=args.matlab_root,
            wav_name=wav_name,
            local_wav=local_wav,
        )
        runs.append(report)
        print(
            f"audio={report['audio_length_sec']:.1f}s "
            f"polled_pss={report['polled_peak_pss_mb']:.1f}MB "
            f"ani_file={(report.get('ani_file_bytes') or 0)/1024/1024:.1f}MB",
            flush=True,
        )

    summary = {
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "host": args.host,
        "runs": runs,
    }
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    json_path = ARTIFACT_DIR / "mex_memory_profile.json"
    md_path = ARTIFACT_DIR / "mex_memory_profile.md"
    json_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    md_path.write_text(to_markdown(summary), encoding="utf-8")
    print(md_path.read_text(encoding="utf-8"))
    print(f"Wrote {json_path} and {md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
