#!/usr/bin/env python3
"""Time the Octave Docker backend, for comparison with the compiled MATLAB spike.

Measures a cold ``docker run`` per analysis and a warm ``docker exec`` into a
long-lived container, which is what ``Leman2000Session`` does. Run on the same
machine as ``drive_matlab_worker.py`` so the two sets of numbers are comparable.
"""

from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import time
import uuid
from pathlib import Path

IMAGE = "ghcr.io/cms-cambridge/pyleman2000-octave:dev"
ENTRYPOINT = "/leman_2000_docker.sh"
LOCAL_DECAY = "0.1,0.2"
GLOBAL_DECAY = "1.0,2.0"
DETAIL = "0"


def run(cmd: list[str]) -> float:
    start = time.monotonic()
    completed = subprocess.run(cmd, capture_output=True, text=True)
    elapsed = time.monotonic() - start
    if completed.returncode != 0:
        raise RuntimeError(f"command failed: {' '.join(cmd)}\n{completed.stderr}")
    return elapsed


def oneshot(data_dir: Path, wav_name: str, out_name: str) -> float:
    return run(
        [
            "docker", "run", "--rm",
            "-v", f"{data_dir}:/data",
            IMAGE,
            f"/data/{wav_name}", f"/data/{out_name}",
            LOCAL_DECAY, GLOBAL_DECAY, DETAIL,
        ]
    )


def warm(container: str, wav_name: str, out_name: str) -> float:
    return run(
        [
            "docker", "exec", container,
            ENTRYPOINT,
            f"/data/{wav_name}", f"/data/{out_name}",
            LOCAL_DECAY, GLOBAL_DECAY, DETAIL,
        ]
    )


def summarise(times: list[float]) -> dict:
    return {
        "n": len(times),
        "mean": statistics.fmean(times),
        "median": statistics.median(times),
        "min": min(times),
        "max": max(times),
    }


def main() -> None:
    spike_dir = Path.home() / "matlab-compiler-spike"
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spike-dir", type=Path, default=spike_dir)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--out", type=Path, default=spike_dir / "octave_timings.json")
    args = parser.parse_args()

    data_dir = args.spike_dir / "octave-data"
    data_dir.mkdir(parents=True, exist_ok=True)
    audio = {"short_0.37s": "hihat.wav", "long_5s": "hihat_5s.wav"}
    for name in audio.values():
        target = data_dir / name
        if not target.exists():
            target.write_bytes((args.spike_dir / name).read_bytes())

    results: dict[str, object] = {"repeats": args.repeats, "image": IMAGE}

    # One warm-up run so the comparison is not paying image-layer cache costs.
    oneshot(data_dir, audio["short_0.37s"], "warmup.json")

    for label, wav_name in audio.items():
        times = [
            oneshot(data_dir, wav_name, f"oneshot-{label}-{i}.json")
            for i in range(args.repeats)
        ]
        results[f"oneshot_{label}"] = summarise(times)

    container = f"leman-bench-{uuid.uuid4().hex[:8]}"
    subprocess.run(
        [
            "docker", "run", "-d", "--name", container,
            "-v", f"{data_dir}:/data",
            "--entrypoint", "sleep", IMAGE, "infinity",
        ],
        check=True,
        capture_output=True,
    )
    try:
        for label, wav_name in audio.items():
            times = [
                warm(container, wav_name, f"warm-{label}-{i}.json")
                for i in range(args.repeats)
            ]
            results[f"warm_{label}"] = summarise(times)
    finally:
        subprocess.run(["docker", "rm", "-f", container], capture_output=True)

    args.out.write_text(json.dumps(results, indent=2))
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
