#!/usr/bin/env python3
"""Benchmark old MATLAB MCR image vs new compiled MATLAB worker.

Old image: ``ghcr.io/pmcharrison/leman_2000:latest`` (CLI oneshot / warm exec).
New image: ``pyleman2000-matlab-worker:latest`` (persistent file-queue worker).

Run on the same Linux host that has both images (e.g. musix).
"""

from __future__ import annotations

import json
import os
import statistics
import subprocess
import time
import uuid
import wave
from pathlib import Path

OLD_IMAGE = "ghcr.io/pmcharrison/leman_2000:latest"
NEW_IMAGE = "pyleman2000-matlab-worker:latest"
LOCAL = "0.1,0.2"
GLOBAL = "1.0,2.0"
DETAIL = "0"
READY_TIMEOUT_SEC = 180.0
REQUEST_TIMEOUT_SEC = 600.0


def summarise(times: list[float]) -> dict:
    return {
        "n": len(times),
        "mean": statistics.fmean(times),
        "median": statistics.median(times),
        "min": min(times),
        "max": max(times),
    }


def tile_wav(source: Path, target: Path, target_sec: float) -> Path:
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


def old_oneshot(data_dir: Path, wav_name: str, out_name: str) -> float:
    t0 = time.perf_counter()
    completed = subprocess.run(
        [
            "docker", "run", "--rm",
            "-v", f"{data_dir}:/data",
            OLD_IMAGE,
            f"/data/{wav_name}",
            f"/data/{out_name}",
            LOCAL,
            GLOBAL,
            DETAIL,
        ],
        capture_output=True,
        text=True,
    )
    elapsed = time.perf_counter() - t0
    if completed.returncode != 0:
        raise RuntimeError(
            f"old oneshot failed:\n{completed.stdout[-2000:]}\n{completed.stderr[-2000:]}"
        )
    return elapsed


def old_warm(container: str, wav_name: str, out_name: str) -> float:
    cmd = (
        f"cp /data/{wav_name} /input.wav && "
        f"/leman_2000_docker.sh /input.wav /data/{out_name} "
        f"{LOCAL} {GLOBAL} {DETAIL}"
    )
    t0 = time.perf_counter()
    completed = subprocess.run(
        ["docker", "exec", container, "/bin/sh", "-c", cmd],
        capture_output=True,
        text=True,
    )
    elapsed = time.perf_counter() - t0
    if completed.returncode != 0:
        raise RuntimeError(
            f"old warm failed:\n{completed.stdout[-2000:]}\n{completed.stderr[-2000:]}"
        )
    return elapsed


def wait_for(path: Path, timeout_sec: float, container: str) -> None:
    deadline = time.monotonic() + timeout_sec
    while not path.exists():
        status = subprocess.run(
            ["docker", "inspect", "-f", "{{.State.Running}}", container],
            capture_output=True,
            text=True,
        )
        if status.stdout.strip() != "true":
            logs = subprocess.run(
                ["docker", "logs", container], capture_output=True, text=True
            )
            raise RuntimeError(
                f"container {container} died before {path.name}\n{logs.stderr}\n{logs.stdout}"
            )
        if time.monotonic() > deadline:
            raise TimeoutError(f"timed out waiting for {path}")
        time.sleep(0.005)


def publish_request(work_dir: Path, request_id: str, payload: dict) -> None:
    tmp = work_dir / f"tmp-req-{request_id}.json"
    tmp.write_text(json.dumps(payload))
    os.replace(tmp, work_dir / f"req-{request_id}.json")


def new_worker_request(
    work_dir: Path,
    data_dir: Path,
    container: str,
    request_id: str,
    wav_name: str,
    out_name: str,
) -> float:
    payload = {
        "in_file": f"/data/{wav_name}",
        "out_file": f"/data/{out_name}",
        "local_decay_sec": [float(x) for x in LOCAL.split(",")],
        "global_decay_sec": [float(x) for x in GLOBAL.split(",")],
        "detail": int(DETAIL),
    }
    response = work_dir / f"res-{request_id}.json"
    t0 = time.perf_counter()
    publish_request(work_dir, request_id, payload)
    wait_for(response, REQUEST_TIMEOUT_SEC, container)
    elapsed = time.perf_counter() - t0
    status = json.loads(response.read_text())
    if status.get("status") != "ok":
        raise RuntimeError(f"new worker error: {status}")
    return elapsed


def new_oneshot(work_root: Path, wav: Path, out_name: str) -> float:
    """Start worker, one request, stop — full cold cost of new backend."""
    session = work_root / f"oneshot-{uuid.uuid4().hex[:8]}"
    work = session / "work"
    data = session / "data"
    work.mkdir(parents=True)
    data.mkdir()
    wav_name = wav.name
    (data / wav_name).write_bytes(wav.read_bytes())
    name = f"matlab-new-{uuid.uuid4().hex[:8]}"
    t0 = time.perf_counter()
    subprocess.run(
        [
            "docker", "run", "-d", "--name", name,
            "-e", "AGREE_TO_MATLAB_RUNTIME_LICENSE=yes",
            "-e", "MLM_LICENSE_FILE=/definitely/not/a/license.lic",
            "-v", f"{work}:/work",
            "-v", f"{data}:/data",
            NEW_IMAGE,
            "/work",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    try:
        wait_for(work / "ready", READY_TIMEOUT_SEC, name)
        new_worker_request(work, data, name, "1", wav_name, out_name)
        (work / "stop").touch()
        subprocess.run(["docker", "wait", name], capture_output=True, timeout=30)
    finally:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True)
    return time.perf_counter() - t0


def main() -> None:
    spike = Path.home() / "matlab-compiler-spike"
    data_dir = spike / "old-vs-new-bench"
    data_dir.mkdir(parents=True, exist_ok=True)
    short = spike / "hihat.wav"
    long = tile_wav(short, spike / "hihat_5s.wav", 5.0)
    audio = {"short_0.37s": short, "long_5s": long}
    for label, wav in audio.items():
        (data_dir / wav.name).write_bytes(wav.read_bytes())

    repeats = 3
    results: dict[str, object] = {
        "repeats": repeats,
        "old_image": OLD_IMAGE,
        "new_image": NEW_IMAGE,
        "local_decay_sec": LOCAL,
        "global_decay_sec": GLOBAL,
        "detail": DETAIL,
    }

    # Warmup both images once.
    print("warmup old oneshot...", flush=True)
    old_oneshot(data_dir, short.name, "warmup_old.json")
    print("warmup new oneshot...", flush=True)
    new_oneshot(data_dir, short, "warmup_new.json")

    for label, wav in audio.items():
        print(f"old oneshot {label}...", flush=True)
        times = [
            old_oneshot(data_dir, wav.name, f"old-oneshot-{label}-{i}.json")
            for i in range(repeats)
        ]
        results[f"old_oneshot_{label}"] = summarise(times)
        print(f"  {summarise(times)}", flush=True)

    for label, wav in audio.items():
        print(f"new oneshot {label}...", flush=True)
        times = [
            new_oneshot(data_dir, wav, f"new-oneshot-{label}-{i}.json")
            for i in range(repeats)
        ]
        results[f"new_oneshot_{label}"] = summarise(times)
        print(f"  {summarise(times)}", flush=True)

    # Warm old: long-lived container + docker exec (same as prior decomposition).
    old_name = f"old-warm-{uuid.uuid4().hex[:8]}"
    subprocess.run(
        [
            "docker", "run", "-d", "--name", old_name,
            "--entrypoint", "/bin/sleep",
            "-v", f"{data_dir}:/data",
            OLD_IMAGE,
            "infinity",
        ],
        check=True,
        capture_output=True,
    )
    try:
        for label, wav in audio.items():
            print(f"old warm {label}...", flush=True)
            # one warmup exec
            old_warm(old_name, wav.name, f"old-warm-warmup-{label}.json")
            times = [
                old_warm(old_name, wav.name, f"old-warm-{label}-{i}.json")
                for i in range(repeats)
            ]
            results[f"old_warm_{label}"] = summarise(times)
            print(f"  {summarise(times)}", flush=True)
    finally:
        subprocess.run(["docker", "rm", "-f", old_name], capture_output=True)

    # Warm new: one worker, many requests.
    session = data_dir / "new-warm-session"
    work = session / "work"
    data = session / "data"
    if session.exists():
        for child in session.rglob("*"):
            if child.is_file():
                child.unlink()
    work.mkdir(parents=True, exist_ok=True)
    data.mkdir(parents=True, exist_ok=True)
    for wav in audio.values():
        (data / wav.name).write_bytes(wav.read_bytes())
    new_name = f"new-warm-{uuid.uuid4().hex[:8]}"
    t_start = time.perf_counter()
    subprocess.run(
        [
            "docker", "run", "-d", "--name", new_name,
            "-e", "AGREE_TO_MATLAB_RUNTIME_LICENSE=yes",
            "-e", "MLM_LICENSE_FILE=/definitely/not/a/license.lic",
            "-v", f"{work}:/work",
            "-v", f"{data}:/data",
            NEW_IMAGE,
            "/work",
        ],
        check=True,
        capture_output=True,
    )
    try:
        wait_for(work / "ready", READY_TIMEOUT_SEC, new_name)
        results["new_worker_startup_sec"] = time.perf_counter() - t_start
        for label, wav in audio.items():
            print(f"new warm {label}...", flush=True)
            times = [
                new_worker_request(
                    work,
                    data,
                    new_name,
                    f"{label}-{i}",
                    wav.name,
                    f"new-warm-{label}-{i}.json",
                )
                for i in range(repeats)
            ]
            results[f"new_warm_{label}"] = summarise(times)
            print(f"  {summarise(times)}", flush=True)
    finally:
        (work / "stop").touch()
        subprocess.run(["docker", "rm", "-f", new_name], capture_output=True)

    out = spike / "old_vs_new_matlab_timings.json"
    out.write_text(json.dumps(results, indent=2))
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
