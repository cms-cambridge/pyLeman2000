#!/usr/bin/env python3
"""Compare leman2000_batch vs sequential one-shot and warm-session baselines.

Runs the same WAV paths through:

1. sequential ``leman2000`` oneshots (fresh container each file)
2. sequential ``Leman2000Session`` (one warm worker)
3. ``leman2000_batch`` with an explicit worker count

Usage::

    python3 scripts/benchmark/bench_batch_vs_sequential.py
    python3 scripts/benchmark/bench_batch_vs_sequential.py --n-files 8 --workers 4
"""

from __future__ import annotations

import argparse
import json
import platform
import shutil
import statistics
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

from pyleman2000 import (
    Leman2000Session,
    __version__,
    example_wav_path,
    leman2000,
    leman2000_batch,
)
from pyleman2000.worker_sizing import (
    MATLAB_RAM_PER_WORKER_BYTES,
    choose_worker_count,
)

ROOT = Path(__file__).resolve().parents[2]
ARTIFACT_DIR = ROOT / "artifacts" / "benchmark"
LOCAL = [0.1, 0.2]
GLOBAL = [1.0, 2.0]


def _mean(xs: list[float]) -> float:
    return statistics.fmean(xs) if xs else float("nan")


def _summarize(times: list[float]) -> dict[str, float]:
    return {
        "n": len(times),
        "mean_sec": _mean(times),
        "stdev_sec": statistics.stdev(times) if len(times) > 1 else 0.0,
        "min_sec": min(times) if times else float("nan"),
        "median_sec": statistics.median(times) if times else float("nan"),
        "max_sec": max(times) if times else float("nan"),
    }


def _make_paths(n_files: int, work: Path) -> list[Path]:
    src = example_wav_path().read_bytes()
    paths: list[Path] = []
    for i in range(n_files):
        path = work / f"file_{i:02d}.wav"
        path.write_bytes(src)
        paths.append(path)
    return paths


def _time_oneshots(paths: list[Path]) -> float:
    t0 = time.perf_counter()
    for path in paths:
        leman2000(
            path,
            local_decay_sec=LOCAL,
            global_decay_sec=GLOBAL,
            show_progress=False,
        )
    return time.perf_counter() - t0


def _time_session(paths: list[Path]) -> float:
    t0 = time.perf_counter()
    with Leman2000Session(show_progress=False) as session:
        for path in paths:
            session.run(
                path,
                local_decay_sec=LOCAL,
                global_decay_sec=GLOBAL,
            )
    return time.perf_counter() - t0


def _time_batch(paths: list[Path], workers: int) -> float:
    t0 = time.perf_counter()
    leman2000_batch(
        paths,
        local_decay_sec=LOCAL,
        global_decay_sec=GLOBAL,
        workers=workers,
        show_progress=False,
    )
    return time.perf_counter() - t0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--n-files", type=int, default=6)
    parser.add_argument(
        "--workers",
        type=int,
        default=None,
        help="Batch worker count (default: auto-sized, then reported)",
    )
    parser.add_argument("--repeats", type=int, default=2)
    parser.add_argument("--warmup", type=int, default=1)
    args = parser.parse_args()

    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    auto_workers = choose_worker_count(args.n_files, backend="matlab")
    workers = args.workers if args.workers is not None else auto_workers

    print("=== batch vs sequential ===", flush=True)
    print(f"pyLeman2000 {__version__}", flush=True)
    print(f"host={platform.platform()}", flush=True)
    print(
        f"n_files={args.n_files} workers={workers} "
        f"(auto={auto_workers}) "
        f"matlab_ram_budget={MATLAB_RAM_PER_WORKER_BYTES / 1024**3:.0f}GiB",
        flush=True,
    )
    print(f"params local={LOCAL} global={GLOBAL}", flush=True)

    with tempfile.TemporaryDirectory(prefix="pyleman-batch-bench-") as tmp:
        paths = _make_paths(args.n_files, Path(tmp))

        print("\nWarmup", flush=True)
        for i in range(args.warmup):
            sec = _time_batch(paths[: max(1, min(2, args.n_files))], workers=1)
            print(f"  warmup[{i}] batch(workers=1, n<=2): {sec:.3f}s", flush=True)

        results: dict[str, list[float]] = {
            "oneshot_sequential": [],
            "session_sequential": [],
            "batch_parallel": [],
        }

        print("\nTimed repeats", flush=True)
        for i in range(args.repeats):
            for name, fn in (
                ("oneshot_sequential", lambda: _time_oneshots(paths)),
                ("session_sequential", lambda: _time_session(paths)),
                ("batch_parallel", lambda: _time_batch(paths, workers)),
            ):
                sec = fn()
                results[name].append(sec)
                print(f"  repeat[{i}] {name}: {sec:.3f}s", flush=True)

    summary = {name: _summarize(times) for name, times in results.items()}
    batch_mean = summary["batch_parallel"]["mean_sec"]
    session_mean = summary["session_sequential"]["mean_sec"]
    oneshot_mean = summary["oneshot_sequential"]["mean_sec"]

    payload = {
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "version": __version__,
        "host": platform.platform(),
        "n_files": args.n_files,
        "workers": workers,
        "auto_workers": auto_workers,
        "local_decay_sec": LOCAL,
        "global_decay_sec": GLOBAL,
        "repeats": args.repeats,
        "warmup": args.warmup,
        "results": results,
        "summary": summary,
        "speedup_vs_session": (
            session_mean / batch_mean if batch_mean > 0 else float("nan")
        ),
        "speedup_vs_oneshot": (
            oneshot_mean / batch_mean if batch_mean > 0 else float("nan")
        ),
    }

    out_json = ARTIFACT_DIR / "batch_vs_sequential.json"
    out_md = ARTIFACT_DIR / "batch_vs_sequential.md"
    out_json.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    lines = [
        "# Batch vs sequential",
        "",
        f"Collected: `{payload['collected_at']}`",
        "",
        f"- Host: `{payload['host']}`",
        f"- pyLeman2000 `{payload['version']}`",
        f"- Files: {args.n_files}, workers: {workers} (auto would choose {auto_workers})",
        f"- Params: local={LOCAL}, global={GLOBAL}, repeats={args.repeats}",
        "",
        "## Mean wall clock (seconds)",
        "",
        "| Mode | Mean | Median | Min | Max |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for name, label in (
        ("oneshot_sequential", "oneshot sequential"),
        ("session_sequential", "session sequential"),
        ("batch_parallel", f"batch parallel (workers={workers})"),
    ):
        s = summary[name]
        lines.append(
            f"| {label} | {s['mean_sec']:.3f} | {s['median_sec']:.3f} | "
            f"{s['min_sec']:.3f} | {s['max_sec']:.3f} |"
        )
    lines.extend(
        [
            "",
            "## Relative speed (mean)",
            "",
            f"- batch vs session: **{payload['speedup_vs_session']:.2f}×**",
            f"- batch vs oneshot: **{payload['speedup_vs_oneshot']:.2f}×**",
            "",
        ]
    )
    out_md.write_text("\n".join(lines), encoding="utf-8")
    print("\n" + "\n".join(lines), flush=True)
    print(f"Wrote {out_json}", flush=True)
    print(f"Wrote {out_md}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
