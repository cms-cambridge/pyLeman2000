#!/usr/bin/env python3
"""Benchmark ``leman2000_batch`` worker scaling across file counts and lengths.

Answers a narrow question: does ``workers > 1`` actually beat a single warm
worker, and where is the crossover? Each condition calls
``leman2000_batch(..., workers=N)`` so all conditions get warm workers and pay
the pool startup the user would pay. Wall time includes opening the pool.

Run on a machine with Docker and the model image available. The full matrix is
large; use the CLI flags to shrink it. Example::

    python scripts/benchmark/bench_batch_scaling.py \
        --file-counts 2 8 16 --durations 5 30 --workers 1 2 4 --repeats 3

Results are written to ``artifacts/benchmark/batch_scaling.{json,md}``.
"""

from __future__ import annotations

import argparse
import json
import platform
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
import wave
from datetime import datetime, timezone
from pathlib import Path

from pyleman2000 import (
    DEFAULT_IMAGE,
    DEFAULT_MATLAB_IMAGE,
    __version__,
    example_wav_path,
    leman2000_batch,
)

ROOT = Path(__file__).resolve().parents[2]
ARTIFACT_DIR = ROOT / "artifacts" / "benchmark"

LOCAL_DECAY = [0.1, 0.5]
GLOBAL_DECAY = [1.0, 2.0]


def tile_wav(source: Path, target: Path, target_sec: float) -> Path:
    """Write ``target`` by repeating ``source`` until it lasts ``target_sec``."""
    if target.exists():
        return target
    with wave.open(str(source), "rb") as src:
        params = src.getparams()
        frames = src.readframes(params.nframes)
    repeats = max(1, round(target_sec * params.framerate / params.nframes))
    with wave.open(str(target), "wb") as dst:
        dst.setparams(params)
        dst.writeframes(frames * repeats)
    return target


def _summarize(times: list[float]) -> dict[str, float]:
    return {
        "n": len(times),
        "mean_sec": statistics.fmean(times),
        "stdev_sec": statistics.stdev(times) if len(times) > 1 else 0.0,
        "min_sec": min(times),
        "median_sec": statistics.median(times),
        "max_sec": max(times),
    }


def _docker_image_id(ref: str) -> str:
    try:
        proc = subprocess.run(
            ["docker", "image", "inspect", "--format", "{{.Id}}", ref],
            check=True,
            capture_output=True,
            text=True,
        )
        return proc.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "unknown"


def _time_batch(
    wavs: list[Path],
    *,
    workers: int,
    backend: str,
) -> float:
    """Return wall time (incl. pool startup) for one batch run."""
    t0 = time.perf_counter()
    leman2000_batch(
        wavs,
        local_decay_sec=LOCAL_DECAY,
        global_decay_sec=GLOBAL_DECAY,
        workers=workers,
        backend=backend,
        show_progress=False,
    )
    return time.perf_counter() - t0


def _make_batch_dir(source: Path, count: int, dest: Path) -> list[Path]:
    dest.mkdir(parents=True, exist_ok=True)
    wavs = []
    for i in range(count):
        target = dest / f"file_{i:03d}.wav"
        shutil.copy2(source, target)
        wavs.append(target)
    return wavs


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--file-counts", type=int, nargs="+", default=[2, 4, 8, 16, 32]
    )
    parser.add_argument(
        "--durations", type=float, nargs="+", default=[0.4, 5.0, 30.0]
    )
    parser.add_argument("--workers", type=int, nargs="+", default=[1, 2, 4, 8])
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--warmup", type=int, default=1)
    parser.add_argument(
        "--backend", choices=["matlab", "octave"], default="matlab"
    )
    args = parser.parse_args()

    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    source = example_wav_path()
    image = DEFAULT_MATLAB_IMAGE if args.backend == "matlab" else DEFAULT_IMAGE

    meta = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "host": {
            "platform": platform.platform(),
            "processor": platform.processor(),
            "python": sys.version.split()[0],
        },
        "packages": {
            "pyLeman2000": __version__,
            "backend": args.backend,
            "image": image,
            "image_id": _docker_image_id(image),
        },
        "parameters": {
            "local_decay_sec": LOCAL_DECAY,
            "global_decay_sec": GLOBAL_DECAY,
            "file_counts": args.file_counts,
            "durations_sec": args.durations,
            "workers": args.workers,
            "repeats": args.repeats,
            "warmup": args.warmup,
        },
    }

    rows: list[dict] = []
    with tempfile.TemporaryDirectory(prefix="pyleman-batch-bench-") as tmp:
        tmp_path = Path(tmp)
        # Pre-tile one WAV per duration; batch dirs copy from it.
        tiled = {
            dur: tile_wav(
                source, tmp_path / f"tiled_{dur:g}s.wav", dur
            )
            for dur in args.durations
        }

        # One image warm-up so the first real timing does not pay the pull.
        warm_dir = tmp_path / "warmup"
        warm_wavs = _make_batch_dir(tiled[args.durations[0]], 1, warm_dir)
        for _ in range(args.warmup):
            _time_batch(warm_wavs, workers=1, backend=args.backend)

        for dur in args.durations:
            for count in args.file_counts:
                batch_dir = tmp_path / f"d{dur:g}_n{count}"
                wavs = _make_batch_dir(tiled[dur], count, batch_dir)
                for workers in args.workers:
                    effective = min(workers, count)
                    times: list[float] = []
                    for rep in range(args.repeats):
                        elapsed = _time_batch(
                            wavs, workers=workers, backend=args.backend
                        )
                        times.append(elapsed)
                        print(
                            f"    dur={dur:g}s files={count} "
                            f"workers={workers} (eff {effective}) "
                            f"rep={rep}: {elapsed:.2f}s",
                            flush=True,
                        )
                    summary = _summarize(times)
                    throughput = count / summary["mean_sec"]
                    rows.append(
                        {
                            "duration_sec": dur,
                            "file_count": count,
                            "workers": workers,
                            "effective_workers": effective,
                            "throughput_files_per_sec": throughput,
                            **summary,
                        }
                    )

    result = {"meta": meta, "rows": rows}
    suffix = "" if args.backend == "matlab" else f"_{args.backend}"
    json_path = ARTIFACT_DIR / f"batch_scaling{suffix}.json"
    json_path.write_text(json.dumps(result, indent=2), encoding="utf-8")

    lines = [
        "# leman2000_batch worker scaling",
        "",
        f"Collected: `{meta['timestamp_utc']}`",
        "",
        f"- Backend: {args.backend} (`{image}`)",
        f"- Host: `{meta['host']['platform']}`",
        f"- Params: local={LOCAL_DECAY}, global={GLOBAL_DECAY}, "
        f"repeats={args.repeats} (after {args.warmup} warmup)",
        "",
        "Wall time includes pool startup. `speedup` is mean time at "
        "`workers=1` divided by mean time at that worker count.",
        "",
        "| Duration | Files | Workers | Mean (s) | Throughput (files/s) | Speedup vs 1 |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    baseline = {
        (r["duration_sec"], r["file_count"]): r["mean_sec"]
        for r in rows
        if r["workers"] == 1
    }
    for r in rows:
        base = baseline.get((r["duration_sec"], r["file_count"]))
        speedup = f"{base / r['mean_sec']:.2f}x" if base else "n/a"
        lines.append(
            f"| {r['duration_sec']:g}s | {r['file_count']} | {r['workers']} "
            f"| {r['mean_sec']:.2f} | {r['throughput_files_per_sec']:.3f} "
            f"| {speedup} |"
        )
    md_path = ARTIFACT_DIR / f"batch_scaling{suffix}.md"
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"\nWrote {json_path}")
    print(f"Wrote {md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
