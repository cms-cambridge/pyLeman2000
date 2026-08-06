#!/usr/bin/env python3
"""Decompose MATLAB (leman2000R image) wall time into startup vs compute.

Uses two complementary estimates:

1. Duration scaling: T(d) ≈ overhead + k * d from short vs 5s oneshots.
2. Warm-container exec: keep one container alive and re-run the compiled
   MATLAB binary via ``docker exec`` so container create/teardown is excluded;
   residual short→5s growth is model compute.
"""

from __future__ import annotations

import json
import statistics
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ARTIFACT_DIR = ROOT / "artifacts" / "benchmark"
SHORT_WAV = ARTIFACT_DIR / "audio_short_hihat.wav"
LONG_WAV = ARTIFACT_DIR / "audio_5s_tiled_hihat.wav"
IMAGE = "ghcr.io/pmcharrison/leman_2000:latest"
LOCAL = "0.1,0.5"
GLOBAL = "1.0,2.0"
DETAIL = "5"
SHORT_DUR = 0.3707936507936508
LONG_DUR = 5.0


def _mean(xs: list[float]) -> float:
    return statistics.fmean(xs)


def _run_oneshot(wav: Path, out_dir: Path) -> float:
    out_name = f"out_{time.time_ns()}.json"
    t0 = time.perf_counter()
    subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "-v",
            f"{wav.resolve()}:/input.wav:ro",
            "-v",
            f"{out_dir.resolve()}:/output",
            IMAGE,
            "input.wav",
            f"output/{out_name}",
            LOCAL,
            GLOBAL,
            DETAIL,
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return time.perf_counter() - t0


def _empty_container_cycle() -> float:
    """Container create/start/stop with a no-op entrypoint (no MCR)."""
    t0 = time.perf_counter()
    subprocess.run(
        ["docker", "run", "--rm", "--entrypoint", "/bin/true", IMAGE],
        check=True,
        capture_output=True,
        text=True,
    )
    return time.perf_counter() - t0


def _warm_exec_times(wav: Path, *, repeats: int, warmup: int) -> list[float]:
    """Run the compiled binary repeatedly inside one long-lived container."""
    with tempfile.TemporaryDirectory(prefix="matlab-warm-") as tmp:
        tmp_path = Path(tmp)
        work = tmp_path / "work"
        work.mkdir()
        input_host = work / "input.wav"
        input_host.write_bytes(wav.read_bytes())
        # Start idle container with workdir mounted.
        name = f"matlab-warm-{time.time_ns()}"
        subprocess.run(
            [
                "docker",
                "run",
                "-d",
                "--name",
                name,
                "--entrypoint",
                "/bin/sleep",
                "-v",
                f"{work.resolve()}:/work",
                IMAGE,
                "infinity",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        try:
            times: list[float] = []
            for phase, n in (("warmup", warmup), ("run", repeats)):
                for i in range(n):
                    out_name = f"out_{phase}_{i}.json"
                    cmd = (
                        "cp /work/input.wav /input.wav && "
                        "/leman_2000_docker.sh /input.wav "
                        f"/work/{out_name} {LOCAL} {GLOBAL} {DETAIL}"
                    )
                    t0 = time.perf_counter()
                    proc = subprocess.run(
                        ["docker", "exec", name, "/bin/sh", "-c", cmd],
                        capture_output=True,
                        text=True,
                    )
                    elapsed = time.perf_counter() - t0
                    if proc.returncode != 0:
                        raise RuntimeError(
                            f"warm exec failed ({proc.returncode}):\n"
                            f"{proc.stdout[-1500:]}\n{proc.stderr[-1500:]}"
                        )
                    if phase == "run":
                        times.append(elapsed)
                    print(f"    warm {phase}[{i}] {wav.name}: {elapsed:.3f}s", flush=True)
            return times
        finally:
            subprocess.run(
                ["docker", "rm", "-f", name],
                check=False,
                capture_output=True,
                text=True,
            )


def main() -> int:
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    repeats = 3
    warmup = 1
    print("=== MATLAB startup vs compute decomposition ===", flush=True)

    print("\n1) Empty container cycle (no MCR / no model)", flush=True)
    empty = []
    for i in range(warmup):
        sec = _empty_container_cycle()
        print(f"    warmup[{i}] {sec:.3f}s", flush=True)
    for i in range(repeats):
        sec = _empty_container_cycle()
        empty.append(sec)
        print(f"    run[{i}] {sec:.3f}s", flush=True)

    print("\n2) Full oneshot docker run (as leman2000R does)", flush=True)
    with tempfile.TemporaryDirectory(prefix="matlab-oneshot-") as tmp:
        out_dir = Path(tmp)
        short_oneshot: list[float] = []
        long_oneshot: list[float] = []
        for phase, n in (("warmup", warmup), ("run", repeats)):
            for i in range(n):
                s = _run_oneshot(SHORT_WAV, out_dir)
                l = _run_oneshot(LONG_WAV, out_dir)
                if phase == "run":
                    short_oneshot.append(s)
                    long_oneshot.append(l)
                print(
                    f"    {phase}[{i}] short={s:.3f}s  5s={l:.3f}s  delta={l-s:.3f}s",
                    flush=True,
                )

    print("\n3) Warm-container docker exec (excludes create/teardown)", flush=True)
    print("  short:", flush=True)
    short_warm = _warm_exec_times(SHORT_WAV, repeats=repeats, warmup=warmup)
    print("  5s:", flush=True)
    long_warm = _warm_exec_times(LONG_WAV, repeats=repeats, warmup=warmup)

    # Linear model from oneshots: T = overhead + k * duration
    ds = LONG_DUR - SHORT_DUR
    k_oneshot = (_mean(long_oneshot) - _mean(short_oneshot)) / ds
    overhead_oneshot = _mean(short_oneshot) - k_oneshot * SHORT_DUR
    compute_5s_oneshot = k_oneshot * LONG_DUR
    frac_overhead_5s = overhead_oneshot / _mean(long_oneshot)

    k_warm = (_mean(long_warm) - _mean(short_warm)) / ds
    overhead_warm = _mean(short_warm) - k_warm * SHORT_DUR
    compute_5s_warm = k_warm * LONG_DUR
    frac_overhead_5s_warm = overhead_warm / _mean(long_warm)

    meta = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "image": IMAGE,
        "parameters": {"local": LOCAL, "global": GLOBAL, "detail": DETAIL},
        "audio_durations_sec": {"short": SHORT_DUR, "long": LONG_DUR},
        "empty_container_cycle_sec": empty,
        "oneshot": {"short_sec": short_oneshot, "long_sec": long_oneshot},
        "warm_exec": {"short_sec": short_warm, "long_sec": long_warm},
        "decomposition_oneshot": {
            "mean_short_sec": _mean(short_oneshot),
            "mean_long_sec": _mean(long_oneshot),
            "delta_sec": _mean(long_oneshot) - _mean(short_oneshot),
            "sec_per_audio_sec": k_oneshot,
            "estimated_fixed_overhead_sec": overhead_oneshot,
            "estimated_compute_5s_sec": compute_5s_oneshot,
            "overhead_fraction_of_5s": frac_overhead_5s,
        },
        "decomposition_warm_exec": {
            "mean_short_sec": _mean(short_warm),
            "mean_long_sec": _mean(long_warm),
            "delta_sec": _mean(long_warm) - _mean(short_warm),
            "sec_per_audio_sec": k_warm,
            "estimated_fixed_overhead_sec": overhead_warm,
            "estimated_compute_5s_sec": compute_5s_warm,
            "overhead_fraction_of_5s": frac_overhead_5s_warm,
            "note": (
                "Fixed overhead here is mostly MATLAB Runtime startup per exec; "
                "container create/teardown already excluded."
            ),
        },
    }

    out_json = ARTIFACT_DIR / "matlab_overhead_decomposition.json"
    out_md = ARTIFACT_DIR / "matlab_overhead_decomposition.md"
    out_json.write_text(json.dumps(meta, indent=2) + "\n")

    d = meta["decomposition_oneshot"]
    w = meta["decomposition_warm_exec"]
    md = f"""# MATLAB startup vs compute (5s)

Collected: `{meta['timestamp_utc']}`

Image: `{IMAGE}`  
Params: local=`{LOCAL}`, global=`{GLOBAL}`, detail=`{DETAIL}`  
Repeats: {repeats} (after {warmup} warmup), interleaved short/5s oneshots.

## Raw means

| Condition | short (0.37s) | 5s | delta |
| --- | ---: | ---: | ---: |
| Empty container cycle (`docker run --entrypoint /bin/true`) | {_mean(empty):.3f}s | — | — |
| Full oneshot (`docker run`, as leman2000R) | {d['mean_short_sec']:.3f}s | {d['mean_long_sec']:.3f}s | {d['delta_sec']:.3f}s |
| Warm container + `docker exec` | {w['mean_short_sec']:.3f}s | {w['mean_long_sec']:.3f}s | {w['delta_sec']:.3f}s |

## Linear decomposition `T ≈ overhead + k · duration`

### Oneshot (includes container create/teardown + MCR + model)

- k ≈ **{d['sec_per_audio_sec']:.3f} s per audio-second**
- fixed overhead ≈ **{d['estimated_fixed_overhead_sec']:.3f} s**
- estimated compute for 5s ≈ **{d['estimated_compute_5s_sec']:.3f} s**
- overhead share of 5s oneshot ≈ **{100 * d['overhead_fraction_of_5s']:.1f}%**

### Warm exec (excludes container create/teardown; still pays MCR each exec)

- k ≈ **{w['sec_per_audio_sec']:.3f} s per audio-second**
- fixed overhead (mostly MCR startup) ≈ **{w['estimated_fixed_overhead_sec']:.3f} s**
- estimated compute for 5s ≈ **{w['estimated_compute_5s_sec']:.3f} s**
- overhead share of 5s warm exec ≈ **{100 * w['overhead_fraction_of_5s']:.1f}%**

## Verdict

If overhead share of the 5s oneshot is ≳50%, the earlier claim holds: even a 5s
MATLAB analysis is still dominated by startup/fixed cost, not audio-length
compute.
"""
    out_md.write_text(md)
    print("\n" + md)
    print(f"Wrote {out_json}")
    print(f"Wrote {out_md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
