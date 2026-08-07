"""Compiled MATLAB worker backend via a Docker file-queue protocol.

The worker image entrypoint is a long-lived compiled MATLAB process that:

1. Writes ``<work_dir>/ready`` once ``IPEMSetup`` has finished.
2. Polls for ``req-<id>.json`` request files (published atomically).
3. Writes model JSON to the path in the request, then ``res-<id>.json``.
4. Exits when ``<work_dir>/stop`` appears.

This is the path that reuses MATLAB Runtime state across analyses. The Octave
backend in :mod:`pyleman2000.docker_runner` stays the default; select this
backend with ``backend="matlab"``.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import time
import uuid
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import docker
from docker.errors import APIError, DockerException, ImageNotFound
from docker.models.containers import Container

from pyleman2000.docker_runner import (
    DEFAULT_TIMEOUT_SEC,
    Leman2000DockerError,
    _ensure_image,
    _validate_timeout_sec,
    _with_platform,
)
from pyleman2000.progress import RunProgress

# Published MATLAB worker (built on a Compiler host via
# ./scripts/build_matlab_image.sh --push). Until the first push, builds are
# local-only as pyleman2000-matlab:dev.
DEFAULT_MATLAB_IMAGE = "ghcr.io/cms-cambridge/pyleman2000-matlab:dev"
LOCAL_MATLAB_DEV_IMAGE = "pyleman2000-matlab:dev"
CONTAINER_WORK_DIR = "/work"
CONTAINER_DATA_DIR = "/data"
READY_TIMEOUT_SEC = 300.0
POLL_INTERVAL_SEC = 0.005


def publish_request(work_dir: Path, request_id: str, payload: dict[str, Any]) -> None:
    """Atomically publish a worker request as ``req-<id>.json``."""
    tmp_path = work_dir / f"tmp-req-{request_id}.json"
    final_path = work_dir / f"req-{request_id}.json"
    tmp_path.write_text(json.dumps(payload), encoding="utf-8")
    os.replace(tmp_path, final_path)


def wait_for_path(
    path: Path,
    timeout_sec: float,
    *,
    is_alive: Callable[[], bool] | None = None,
    poll_interval_sec: float = POLL_INTERVAL_SEC,
) -> None:
    """Block until ``path`` exists, or raise on timeout / worker death."""
    deadline = time.monotonic() + timeout_sec
    while not path.exists():
        if is_alive is not None and not is_alive():
            raise Leman2000DockerError(
                "The MATLAB worker container exited before "
                f"{path.name!r} appeared."
            )
        if time.monotonic() > deadline:
            raise Leman2000DockerError(
                f"Timed out after {timeout_sec:g} seconds waiting for "
                f"{path.name!r}."
            )
        time.sleep(poll_interval_sec)


def _container_alive(container: Container) -> bool:
    try:
        container.reload()
    except DockerException:
        return False
    return container.status == "running"


class MatlabWorkerRunner:
    """Drive a persistent compiled MATLAB worker container.

    Host layout (bind-mounted into the container)::

        <session>/work/   -> /work   (ready, req-*, res-*, stop)
        <session>/data/   -> /data   (input WAVs and output JSON)
    """

    def __init__(
        self,
        *,
        image: str = DEFAULT_MATLAB_IMAGE,
        client: docker.DockerClient | None = None,
        timeout_sec: float | None = DEFAULT_TIMEOUT_SEC,
        show_progress: bool = True,
        ready_timeout_sec: float = READY_TIMEOUT_SEC,
    ) -> None:
        self._image = image
        self._client_arg = client
        self._timeout_sec = _validate_timeout_sec(timeout_sec)
        self._show_progress = show_progress
        self._ready_timeout_sec = float(ready_timeout_sec)
        self._client: docker.DockerClient | None = None
        self._owns_client = False
        self._container: Container | None = None
        self._session_dir: Path | None = None
        self._work_dir: Path | None = None
        self._data_dir: Path | None = None

    def open(self) -> MatlabWorkerRunner:
        """Start the worker container and wait until it is ready."""
        if self._container is not None:
            return self

        if self._client_arg is not None:
            self._client = self._client_arg
            self._owns_client = False
        else:
            try:
                self._client = docker.from_env()
            except DockerException as exc:
                raise Leman2000DockerError(
                    "pyLeman2000 could not connect to Docker. Install Docker "
                    "Desktop or the Docker Engine, start the daemon, and "
                    "verify that `docker info` succeeds."
                ) from exc
            self._owns_client = True

        session = Path(tempfile.mkdtemp(prefix="pyleman2000-matlab-"))
        work_dir = session / "work"
        data_dir = session / "data"
        work_dir.mkdir()
        data_dir.mkdir()
        self._session_dir = session
        self._work_dir = work_dir
        self._data_dir = data_dir

        try:
            _ensure_image(
                self._client, self._image, show_progress=self._show_progress
            )
        except Leman2000DockerError:
            self.close()
            raise
        except DockerException as exc:
            self.close()
            raise Leman2000DockerError(
                f"Failed to prepare Docker image {self._image!r}. "
                f"Underlying error: {exc}"
            ) from exc

        progress = RunProgress() if self._show_progress else None
        try:
            if progress is not None:
                progress.preparing()
            self._container = self._client.containers.create(
                **_with_platform(
                    {
                        "image": self._image,
                        "command": [CONTAINER_WORK_DIR],
                        "volumes": {
                            str(work_dir): {
                                "bind": CONTAINER_WORK_DIR,
                                "mode": "rw",
                            },
                            str(data_dir): {
                                "bind": CONTAINER_DATA_DIR,
                                "mode": "rw",
                            },
                        },
                        "environment": {
                            "AGREE_TO_MATLAB_RUNTIME_LICENSE": "yes",
                            # Force license-free Runtime use even if a
                            # network license is configured on the host.
                            "MLM_LICENSE_FILE": "/definitely/not/a/license.lic",
                        },
                    }
                )
            )
            self._container.start()
            wait_for_path(
                work_dir / "ready",
                self._ready_timeout_sec,
                is_alive=lambda: _container_alive(self._container),
            )
        except ImageNotFound as exc:
            self.close()
            raise Leman2000DockerError(
                f"Docker image not found: {self._image!r}"
            ) from exc
        except APIError as exc:
            self.close()
            raise Leman2000DockerError(
                f"Docker API error while starting MATLAB worker for "
                f"{self._image!r}: {exc}"
            ) from exc
        except Leman2000DockerError:
            self.close()
            raise
        finally:
            if progress is not None:
                progress.close()
        return self

    def close(self) -> None:
        """Ask the worker to stop, then remove the container and session dir."""
        work_dir = self._work_dir
        container = self._container
        self._container = None
        self._work_dir = None
        self._data_dir = None

        if work_dir is not None and container is not None:
            try:
                (work_dir / "stop").touch()
            except OSError:
                pass
            # Give the worker a moment to exit cleanly before force-remove.
            deadline = time.monotonic() + 5.0
            while time.monotonic() < deadline and _container_alive(container):
                time.sleep(0.05)

        if container is not None:
            try:
                container.remove(force=True)
            except DockerException:
                pass

        if self._session_dir is not None:
            shutil.rmtree(self._session_dir, ignore_errors=True)
            self._session_dir = None

        if self._owns_client and self._client is not None:
            try:
                self._client.close()
            except DockerException:
                pass
        self._client = None
        self._owns_client = False

    def __enter__(self) -> MatlabWorkerRunner:
        return self.open()

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def run(
        self,
        input_file: Path,
        local_decay_sec: Sequence[float],
        global_decay_sec: Sequence[float],
        *,
        detail: int = 0,
    ) -> dict[str, Any]:
        """Publish one analysis request and return the parsed model JSON."""
        if (
            self._container is None
            or self._work_dir is None
            or self._data_dir is None
        ):
            raise Leman2000DockerError(
                "MatlabWorkerRunner is not open. Use it as a context manager "
                "or call open() before run()."
            )

        input_file = Path(input_file).resolve()
        if not input_file.is_file():
            raise FileNotFoundError(f"Input file not found: {input_file}")

        request_id = uuid.uuid4().hex
        host_wav = self._data_dir / f"{request_id}.wav"
        host_out = self._data_dir / f"{request_id}.json"
        shutil.copy2(input_file, host_wav)

        payload = {
            "in_file": f"{CONTAINER_DATA_DIR}/{request_id}.wav",
            "out_file": f"{CONTAINER_DATA_DIR}/{request_id}.json",
            "local_decay_sec": [float(v) for v in local_decay_sec],
            "global_decay_sec": [float(v) for v in global_decay_sec],
            "detail": int(detail),
        }
        response_path = self._work_dir / f"res-{request_id}.json"
        timeout = self._timeout_sec if self._timeout_sec is not None else 1e9

        progress = RunProgress() if self._show_progress else None
        try:
            if progress is not None:
                progress.running(0.0)
            publish_request(self._work_dir, request_id, payload)
            wait_for_path(
                response_path,
                timeout,
                is_alive=lambda: _container_alive(self._container),
            )
            response = json.loads(response_path.read_text(encoding="utf-8"))
            if response.get("status") != "ok":
                message = response.get("message", "unknown worker error")
                raise Leman2000DockerError(
                    f"MATLAB worker request failed: {message}"
                )
            if progress is not None:
                progress.reading()
            if not host_out.is_file():
                raise Leman2000DockerError(
                    "MATLAB worker reported success but did not write "
                    f"output file {host_out.name!r}."
                )
            return json.loads(host_out.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise Leman2000DockerError(
                f"Failed to read MATLAB worker response: {exc}"
            ) from exc
        finally:
            if progress is not None:
                progress.close()


def run_model_matlab(
    input_file: Path,
    local_decay_sec: Sequence[float],
    global_decay_sec: Sequence[float],
    *,
    detail: int = 0,
    image: str = DEFAULT_MATLAB_IMAGE,
    client: docker.DockerClient | None = None,
    timeout_sec: float | None = DEFAULT_TIMEOUT_SEC,
    show_progress: bool = True,
) -> dict[str, Any]:
    """Run one analysis via a short-lived MATLAB worker container."""
    with MatlabWorkerRunner(
        image=image,
        client=client,
        timeout_sec=timeout_sec,
        show_progress=show_progress,
    ) as runner:
        return runner.run(
            input_file,
            local_decay_sec,
            global_decay_sec,
            detail=detail,
        )
