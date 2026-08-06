#!/usr/bin/env python3
"""Time the compiled MATLAB Leman worker against the compiled one-shot app.

Intended to run on the machine that has MATLAB R2026a and the compiled spike
builds. Startup cost (MATLAB Runtime load plus IPEMSetup) is paid once by the
worker, so comparing worker request latency with one-shot wall time shows how
much a persistent session buys us.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import time
import wave
from pathlib import Path

READY_TIMEOUT_SEC = 300.0
REQUEST_TIMEOUT_SEC = 600.0
LOCAL_DECAY = "0.1,0.2"
GLOBAL_DECAY = "1.0,2.0"


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


def wait_for_file(path: Path, timeout_sec: float, process: subprocess.Popen) -> None:
    deadline = time.monotonic() + timeout_sec
    while not path.exists():
        if process.poll() is not None:
            raise RuntimeError(f"worker exited early with code {process.returncode}")
        if time.monotonic() > deadline:
            raise TimeoutError(f"timed out waiting for {path}")
        time.sleep(0.002)


def publish_request(work_dir: Path, request_id: str, payload: dict) -> None:
    tmp_path = work_dir / f"tmp-req-{request_id}.json"
    tmp_path.write_text(json.dumps(payload))
    os.replace(tmp_path, work_dir / f"req-{request_id}.json")


def worker_request(
    work_dir: Path,
    process: subprocess.Popen,
    request_id: str,
    wav: Path,
    out_file: Path,
) -> float:
    payload = {
        "in_file": str(wav),
        "out_file": str(out_file),
        "local_decay_sec": [float(x) for x in LOCAL_DECAY.split(",")],
        "global_decay_sec": [float(x) for x in GLOBAL_DECAY.split(",")],
        "detail": 0,
    }
    response_path = work_dir / f"res-{request_id}.json"
    start = time.monotonic()
    publish_request(work_dir, request_id, payload)
    wait_for_file(response_path, REQUEST_TIMEOUT_SEC, process)
    elapsed = time.monotonic() - start
    response = json.loads(response_path.read_text())
    if response.get("status") != "ok":
        raise RuntimeError(f"worker error: {response.get('message')}")
    return elapsed


def oneshot_run(runner: Path, mcr_root: Path, wav: Path, out_file: Path) -> float:
    start = time.monotonic()
    completed = subprocess.run(
        [
            str(runner),
            str(mcr_root),
            str(wav),
            str(out_file),
            LOCAL_DECAY,
            GLOBAL_DECAY,
            "0",
        ],
        capture_output=True,
        text=True,
    )
    elapsed = time.monotonic() - start
    if completed.returncode != 0:
        raise RuntimeError(f"one-shot app failed:\n{completed.stdout}\n{completed.stderr}")
    return elapsed


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
    parser.add_argument("--mcr-root", type=Path, default=Path.home() / "MATLAB/R2026a")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--out", type=Path, default=spike_dir / "worker_timings.json")
    args = parser.parse_args()

    spike_dir = args.spike_dir
    work_dir = spike_dir / "worker-queue"
    work_dir.mkdir(parents=True, exist_ok=True)
    for stale in work_dir.iterdir():
        stale.unlink()

    audio = {
        "short_0.37s": spike_dir / "hihat.wav",
        "long_5s": tile_wav(spike_dir / "hihat.wav", spike_dir / "hihat_5s.wav", 5.0),
    }

    worker_runner = spike_dir / "build-worker" / "run_leman_2000_worker.sh"
    oneshot_runner = spike_dir / "build-leman" / "run_leman_2000.sh"
    log_path = spike_dir / "worker-run.log"

    results: dict[str, object] = {"repeats": args.repeats}
    with log_path.open("w") as log:
        start = time.monotonic()
        process = subprocess.Popen(
            [str(worker_runner), str(args.mcr_root), str(work_dir)],
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        try:
            wait_for_file(work_dir / "ready", READY_TIMEOUT_SEC, process)
            results["worker_startup_sec"] = time.monotonic() - start

            for label, wav in audio.items():
                times = [
                    worker_request(
                        work_dir,
                        process,
                        f"{label}-{i}",
                        wav,
                        spike_dir / f"worker-{label}-{i}.json",
                    )
                    for i in range(args.repeats)
                ]
                results[f"worker_{label}"] = summarise(times)
        finally:
            (work_dir / "stop").touch()
            try:
                process.wait(timeout=60)
            except subprocess.TimeoutExpired:
                process.kill()

    for label, wav in audio.items():
        times = [
            oneshot_run(
                oneshot_runner,
                args.mcr_root,
                wav,
                spike_dir / f"oneshot-{label}-{i}.json",
            )
            for i in range(args.repeats)
        ]
        results[f"oneshot_{label}"] = summarise(times)

    args.out.write_text(json.dumps(results, indent=2))
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
