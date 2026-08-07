"""Tests for the compiled MATLAB worker file-queue backend."""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from pyleman2000 import example_wav_path
from pyleman2000.docker_runner import Leman2000DockerError
from pyleman2000.matlab_worker import (
    CONTAINER_DATA_DIR,
    CONTAINER_WORK_DIR,
    DEFAULT_MATLAB_IMAGE,
    MatlabWorkerRunner,
    publish_request,
    wait_for_path,
)

PAYLOAD = {
    "audio_length_sec": 0.37,
    "num_channels": 1,
    "sample_rate": 44100.0,
    "local_global_comparison": [
        {
            "local_decay_sec": 0.1,
            "global_decay_sec": 1.0,
            "running_correlation": [1.0, 0.99],
        }
    ],
}


def test_publish_request_is_atomic(tmp_path: Path) -> None:
    publish_request(tmp_path, "abc", {"detail": 0})
    assert (tmp_path / "req-abc.json").is_file()
    assert not (tmp_path / "tmp-req-abc.json").exists()
    assert json.loads((tmp_path / "req-abc.json").read_text()) == {"detail": 0}


def test_wait_for_path_times_out(tmp_path: Path) -> None:
    with pytest.raises(Leman2000DockerError, match="Timed out"):
        wait_for_path(tmp_path / "missing", timeout_sec=0.05)


def test_wait_for_path_detects_dead_worker(tmp_path: Path) -> None:
    with pytest.raises(Leman2000DockerError, match="exited before"):
        wait_for_path(
            tmp_path / "missing",
            timeout_sec=1.0,
            is_alive=lambda: False,
        )


def _publish_atomically(path: Path, payload: dict) -> None:
    """Write JSON the way the worker does, so readers never see a partial file."""
    tmp_path = path.with_name(f"tmp-{path.name}")
    tmp_path.write_text(json.dumps(payload))
    os.replace(tmp_path, path)


def _fake_worker(
    work_dir: Path, data_dir: Path, stop: threading.Event, response: dict
) -> None:
    """Simulate the compiled MATLAB worker against a host bind-mount layout."""
    (work_dir / "ready").touch()
    while not stop.is_set():
        if (work_dir / "stop").exists():
            return
        for req in sorted(work_dir.glob("req-*.json")):
            request_id = req.name[len("req-") : -len(".json")]
            payload = json.loads(req.read_text())
            req.unlink()
            if response["status"] == "ok":
                # Map container paths back onto the host data dir.
                _publish_atomically(
                    data_dir / Path(payload["out_file"]).name, PAYLOAD
                )
            _publish_atomically(work_dir / f"res-{request_id}.json", response)
        time.sleep(0.005)


def _client_with_simulated_worker(
    response: dict | None = None,
) -> MagicMock:
    """Mock Docker client whose start() launches a host-side fake worker."""
    client = MagicMock()
    client.images.get.return_value = MagicMock()
    container = client.containers.create.return_value
    container.status = "running"
    state = {"stop": threading.Event(), "thread": None, "work": None, "data": None}

    def create(**kwargs):
        volumes = kwargs["volumes"]
        work_binds = [
            host for host, cfg in volumes.items() if cfg["bind"] == CONTAINER_WORK_DIR
        ]
        data_binds = [
            host for host, cfg in volumes.items() if cfg["bind"] == CONTAINER_DATA_DIR
        ]
        assert len(work_binds) == 1 and len(data_binds) == 1
        state["work"] = Path(work_binds[0])
        state["data"] = Path(data_binds[0])
        assert kwargs["command"] == [CONTAINER_WORK_DIR]
        assert kwargs["image"] == DEFAULT_MATLAB_IMAGE
        assert kwargs["environment"]["AGREE_TO_MATLAB_RUNTIME_LICENSE"] == "yes"
        return container

    client.containers.create.side_effect = create

    def start() -> None:
        stop = threading.Event()
        state["stop"] = stop
        thread = threading.Thread(
            target=_fake_worker,
            args=(
                state["work"],
                state["data"],
                stop,
                response or {"status": "ok"},
            ),
            daemon=True,
        )
        state["thread"] = thread
        thread.start()

    def reload() -> None:
        # The real worker exits once it sees the stop file, which is what lets
        # close() finish without waiting out its force-remove grace period.
        thread = state["thread"]
        if state["stop"].is_set() or (thread is not None and not thread.is_alive()):
            container.status = "exited"

    def remove(*, force: bool = False) -> None:
        state["stop"].set()
        thread = state["thread"]
        if thread is not None:
            thread.join(timeout=2.0)

    container.start.side_effect = start
    container.reload.side_effect = reload
    container.remove.side_effect = remove
    return client


def test_matlab_worker_runner_round_trip() -> None:
    client = _client_with_simulated_worker()
    with MatlabWorkerRunner(
        client=client, show_progress=False, ready_timeout_sec=2.0
    ) as runner:
        result = runner.run(
            example_wav_path(),
            local_decay_sec=[0.1],
            global_decay_sec=[1.0],
            detail=0,
        )
    assert result == PAYLOAD
    client.containers.create.assert_called_once()
    container = client.containers.create.return_value
    # remove is MagicMock with side_effect; assert it was invoked on close
    assert container.remove.called


def test_matlab_worker_surfaces_error_status() -> None:
    client = _client_with_simulated_worker(
        response={"status": "error", "message": "boom"}
    )
    with MatlabWorkerRunner(
        client=client, show_progress=False, ready_timeout_sec=2.0
    ) as runner:
        with pytest.raises(Leman2000DockerError, match="boom"):
            runner.run(
                example_wav_path(),
                local_decay_sec=[0.1],
                global_decay_sec=[1.0],
            )
