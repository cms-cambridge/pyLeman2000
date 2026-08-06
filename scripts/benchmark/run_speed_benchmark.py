#!/usr/bin/env python3
"""Benchmark pyLeman2000 against leman2000R for short and 5s audio.

Compares wall-clock time for equivalent API calls on the same WAV files.
Primary comparison uses each package's default API. An optional matched-
detail Python condition uses keep_periodicity_pitch=True so Octave emits
detail=5 like leman2000R (which always requests detail=5).
"""

from __future__ import annotations

import argparse
import json
import platform
import statistics
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from pyleman2000 import DEFAULT_IMAGE, Leman2000Session, __version__, leman2000

ROOT = Path(__file__).resolve().parents[2]
ARTIFACT_DIR = ROOT / "artifacts" / "benchmark"
SHORT_WAV = ARTIFACT_DIR / "audio_short_hihat.wav"
LONG_WAV = ARTIFACT_DIR / "audio_5s_tiled_hihat.wav"

LOCAL_DECAY = [0.1, 0.5]
GLOBAL_DECAY = [1.0, 2.0]
WINDOWS_SHORT = [(0.0, 0.1), (0.1, 0.2)]
WINDOWS_LONG = [(0.0, 1.0), (2.0, 3.0), (4.0, 5.0)]


def _percentile(values: list[float], p: float) -> float:
    if not values:
        return float("nan")
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * (p / 100.0)
    low = int(rank)
    high = min(low + 1, len(ordered) - 1)
    frac = rank - low
    return ordered[low] * (1.0 - frac) + ordered[high] * frac


def _summarize(times: list[float]) -> dict[str, float]:
    return {
        "n": len(times),
        "mean_sec": statistics.fmean(times),
        "stdev_sec": statistics.stdev(times) if len(times) > 1 else 0.0,
        "min_sec": min(times),
        "median_sec": statistics.median(times),
        "p90_sec": _percentile(times, 90),
        "max_sec": max(times),
    }


def _run_python_oneshot(
    wav: Path,
    *,
    windows: list[tuple[float, float]],
    keep_periodicity_pitch: bool,
) -> float:
    t0 = time.perf_counter()
    leman2000(
        input_file=wav,
        local_decay_sec=LOCAL_DECAY,
        global_decay_sec=GLOBAL_DECAY,
        windows=windows,
        keep_periodicity_pitch=keep_periodicity_pitch,
        show_progress=False,
    )
    return time.perf_counter() - t0


def _run_python_session(
    session: Leman2000Session,
    wav: Path,
    *,
    windows: list[tuple[float, float]],
    keep_periodicity_pitch: bool,
) -> float:
    t0 = time.perf_counter()
    session.run(
        input_file=wav,
        local_decay_sec=LOCAL_DECAY,
        global_decay_sec=GLOBAL_DECAY,
        windows=windows,
        keep_periodicity_pitch=keep_periodicity_pitch,
    )
    return time.perf_counter() - t0


def _run_r(wav: Path, *, windows: list[tuple[float, float]]) -> float:
    windows_r = ", ".join(f"c({start}, {end})" for start, end in windows)
    script = f"""
user_lib <- Sys.getenv("R_LIBS_USER")
if (!nzchar(user_lib)) user_lib <- path.expand("~/R/library")
.libPaths(c(user_lib, .libPaths()))
suppressPackageStartupMessages(library(leman2000R))
t0 <- proc.time()[["elapsed"]]
invisible(leman2000(
  input_file = "{wav}",
  local_decay_sec = c({", ".join(str(v) for v in LOCAL_DECAY)}),
  global_decay_sec = c({", ".join(str(v) for v in GLOBAL_DECAY)}),
  windows = list({windows_r})
))
elapsed <- proc.time()[["elapsed"]] - t0
cat(sprintf("BENCH_ELAPSED_SEC=%.6f\\n", elapsed))
"""
    proc = subprocess.run(
        ["Rscript", "-e", script],
        check=True,
        capture_output=True,
        text=True,
    )
    for line in proc.stdout.splitlines():
        if line.startswith("BENCH_ELAPSED_SEC="):
            return float(line.split("=", 1)[1])
    raise RuntimeError(
        "Could not parse R benchmark timing.\n"
        f"stdout:\n{proc.stdout[-2000:]}\n"
        f"stderr:\n{proc.stderr[-2000:]}"
    )


def _docker_info_field(format_str: str) -> str:
    proc = subprocess.run(
        ["docker", "info", "--format", format_str],
        check=True,
        capture_output=True,
        text=True,
    )
    return proc.stdout.strip()


def _docker_image_id(ref: str) -> str:
    proc = subprocess.run(
        ["docker", "image", "inspect", "--format", "{{.Id}}", ref],
        check=True,
        capture_output=True,
        text=True,
    )
    return proc.stdout.strip()


def _r_package_info() -> dict[str, str]:
    script = """
user_lib <- Sys.getenv("R_LIBS_USER")
if (!nzchar(user_lib)) user_lib <- path.expand("~/R/library")
.libPaths(c(user_lib, .libPaths()))
desc <- packageDescription("leman2000R")
cat(paste0(
  "Version=", desc$Version, "\\n",
  "RemoteSha=", if (is.null(desc$RemoteSha)) "" else desc$RemoteSha, "\\n",
  "RemoteUrl=", if (is.null(desc$RemoteUrl)) "" else desc$RemoteUrl, "\\n"
))
"""
    proc = subprocess.run(
        ["Rscript", "-e", script],
        check=True,
        capture_output=True,
        text=True,
    )
    info: dict[str, str] = {}
    for line in proc.stdout.splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            info[key] = value
    return info


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--warmup", type=int, default=1)
    parser.add_argument(
        "--skip-matched-detail",
        action="store_true",
        help="Skip Python detail=5 matched condition",
    )
    parser.add_argument(
        "--skip-session",
        action="store_true",
        help="Skip Python warm-session condition",
    )
    args = parser.parse_args()

    if not SHORT_WAV.is_file() or not LONG_WAV.is_file():
        raise SystemExit(f"Missing benchmark WAVs under {ARTIFACT_DIR}")

    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    r_info = _r_package_info()
    meta = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "host": {
            "platform": platform.platform(),
            "processor": platform.processor(),
            "python": sys.version.split()[0],
            "r": subprocess.check_output(
                ["Rscript", "-e", "cat(as.character(getRversion()))"],
                text=True,
            ).strip(),
        },
        "packages": {
            "pyLeman2000": __version__,
            "py_default_image": DEFAULT_IMAGE,
            "py_image_id": _docker_image_id(DEFAULT_IMAGE),
            "leman2000R": r_info,
            "r_image": "ghcr.io/pmcharrison/leman_2000:latest",
            "r_image_id": _docker_image_id("ghcr.io/pmcharrison/leman_2000:latest"),
        },
        "parameters": {
            "local_decay_sec": LOCAL_DECAY,
            "global_decay_sec": GLOBAL_DECAY,
            "windows_short": WINDOWS_SHORT,
            "windows_long": WINDOWS_LONG,
            "repeats": args.repeats,
            "warmup": args.warmup,
        },
        "audio": {
            "short": {
                "path": str(SHORT_WAV),
                "duration_sec": 0.3707936507936508,
                "note": "packaged hihat.wav",
            },
            "long": {
                "path": str(LONG_WAV),
                "duration_sec": 5.0,
                "note": "hihat.wav tiled to 5.0 s, mono 16-bit 44.1 kHz",
            },
        },
        "results": [],
    }

    cases = [
        ("short", SHORT_WAV, WINDOWS_SHORT),
        ("5s", LONG_WAV, WINDOWS_LONG),
    ]

    for audio_label, wav, windows in cases:
        print(f"\n=== audio={audio_label} ({wav.name}) ===", flush=True)
        # Interleave implementations so Docker/OS cache warm-up affects both
        # similarly, rather than finishing all R runs before Python.
        conditions: list[tuple[str, str, object]] = [
            (
                "leman2000R",
                "oneshot_default",
                lambda w=wav, win=windows: _run_r(w, windows=win),
            ),
            (
                "pyLeman2000",
                "oneshot_default",
                lambda w=wav, win=windows: _run_python_oneshot(
                    w, windows=win, keep_periodicity_pitch=False
                ),
            ),
        ]
        if not args.skip_matched_detail:
            conditions.append(
                (
                    "pyLeman2000",
                    "oneshot_detail5",
                    lambda w=wav, win=windows: _run_python_oneshot(
                        w, windows=win, keep_periodicity_pitch=True
                    ),
                )
            )

        print(
            f"  interleaved oneshot warmup={args.warmup}, repeats={args.repeats}",
            flush=True,
        )
        buckets: dict[tuple[str, str], list[float]] = {
            (impl, mode): [] for impl, mode, _ in conditions
        }
        for phase, n in (("warmup", args.warmup), ("run", args.repeats)):
            for i in range(n):
                for impl, mode, fn in conditions:
                    sec = fn()
                    if phase == "run":
                        buckets[(impl, mode)].append(sec)
                    print(
                        f"    {phase}[{i}] {impl}/{mode}: {sec:.3f}s",
                        flush=True,
                    )

        for impl, mode, _ in conditions:
            times = buckets[(impl, mode)]
            row = {
                "audio": audio_label,
                "implementation": impl,
                "mode": mode,
                "label": f"{impl} {mode} ({audio_label})",
                "times_sec": times,
                **_summarize(times),
            }
            if mode == "oneshot_detail5":
                row["note"] = (
                    "keep_periodicity_pitch=True forces detail=5 like R"
                )
            meta["results"].append(row)

        if not args.skip_session:
            print(f"  Python warm session ({audio_label})", flush=True)
            with Leman2000Session(show_progress=False) as session:
                for i in range(args.warmup):
                    sec = _run_python_session(
                        session,
                        wav,
                        windows=windows,
                        keep_periodicity_pitch=False,
                    )
                    print(f"    warmup[{i}] {sec:.3f}s", flush=True)
                times = []
                for i in range(args.repeats):
                    sec = _run_python_session(
                        session,
                        wav,
                        windows=windows,
                        keep_periodicity_pitch=False,
                    )
                    times.append(sec)
                    print(f"    run[{i}] {sec:.3f}s", flush=True)
            meta["results"].append(
                {
                    "audio": audio_label,
                    "implementation": "pyLeman2000",
                    "mode": "session_default",
                    "label": f"Python session default ({audio_label})",
                    "times_sec": times,
                    **_summarize(times),
                }
            )

    out_json = ARTIFACT_DIR / "speed_benchmark.json"
    out_md = ARTIFACT_DIR / "speed_benchmark.md"
    out_json.write_text(json.dumps(meta, indent=2) + "\n")
    out_md.write_text(_render_markdown(meta))
    print(f"\nWrote {out_json}")
    print(f"Wrote {out_md}")
    return 0


def _render_markdown(meta: dict) -> str:
    lines = [
        "# pyLeman2000 vs leman2000R speed benchmark",
        "",
        f"Collected: `{meta['timestamp_utc']}`",
        "",
        "## Setup",
        "",
        f"- Host: `{meta['host']['platform']}`",
        f"- Python: `{meta['host']['python']}`, pyLeman2000 `{meta['packages']['pyLeman2000']}`",
        f"- R: `{meta['host']['r']}`, leman2000R `{meta['packages']['leman2000R'].get('Version', '?')}`"
        f" (`{meta['packages']['leman2000R'].get('RemoteSha', '')[:12]}`)",
        f"- Python image: `{meta['packages']['py_default_image']}`",
        f"- R image: `{meta['packages']['r_image']}`",
        f"- Parameters: local={meta['parameters']['local_decay_sec']},"
        f" global={meta['parameters']['global_decay_sec']},"
        f" repeats={meta['parameters']['repeats']},"
        f" warmup={meta['parameters']['warmup']}",
        "",
        "Audio:",
        f"- short: packaged `hihat.wav` ({meta['audio']['short']['duration_sec']:.3f}s)",
        f"- 5s: tiled hihat ({meta['audio']['long']['duration_sec']:.1f}s)",
        "",
        "Notes:",
        "- Oneshot conditions are interleaved (R, Python default, Python detail5)",
        "  within each repeat so Docker/OS cache effects are shared more evenly.",
        "- `leman2000R` always requests model `detail=5`.",
        "- pyLeman2000 default uses `detail=0` unless intermediate outputs are kept.",
        "- `oneshot_detail5` sets `keep_periodicity_pitch=True` so Python also uses detail=5.",
        "- `session_default` reuses one warm Docker container via `Leman2000Session`.",
        "",
        "## Results (wall clock, seconds)",
        "",
        "| Audio | Implementation | Mode | Mean | Median | Min | Max |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: |",
    ]
    for row in meta["results"]:
        lines.append(
            f"| {row['audio']} | {row['implementation']} | `{row['mode']}` |"
            f" {row['mean_sec']:.3f} | {row['median_sec']:.3f} |"
            f" {row['min_sec']:.3f} | {row['max_sec']:.3f} |"
        )

    lines.extend(["", "## Relative speed (mean)", ""])
    by_key = {(r["audio"], r["implementation"], r["mode"]): r for r in meta["results"]}
    for audio in ("short", "5s"):
        r_base = by_key.get((audio, "leman2000R", "oneshot_default"))
        if not r_base:
            continue
        lines.append(f"### {audio}")
        lines.append("")
        for mode in ("oneshot_default", "oneshot_detail5", "session_default"):
            py = by_key.get((audio, "pyLeman2000", mode))
            if not py:
                continue
            ratio = r_base["mean_sec"] / py["mean_sec"]
            if ratio >= 1:
                verdict = f"Python **{ratio:.2f}× faster** than R"
            else:
                verdict = f"Python **{1/ratio:.2f}× slower** than R"
            lines.append(f"- `{mode}`: {verdict} (R {r_base['mean_sec']:.3f}s vs Python {py['mean_sec']:.3f}s)")
        lines.append("")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
