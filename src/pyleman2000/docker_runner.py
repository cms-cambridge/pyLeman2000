"""Docker client helpers for running the Leman (2000) Octave model."""

from __future__ import annotations

import json
import math
import os
import tarfile
import tempfile
import threading
import time
import uuid
from collections.abc import Iterator, Sequence
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeout
from contextlib import contextmanager
from pathlib import Path
from typing import Any, BinaryIO

import docker
from docker.errors import APIError, DockerException, ImageNotFound, NotFound
from docker.models.containers import Container
from docker.utils import parse_repository_tag
from requests.exceptions import Timeout

from pyleman2000.progress import PullProgress, RunProgress

# linux/amd64 image published by .github/workflows/docker-publish.yml.
# Branch pushes refresh :dev; workflow_dispatch publishes :0.1.0 (+ :latest).
# The package default is pinned to a digest for reproducibility.
# Apple Silicon runs via Docker Desktop Rosetta/QEMU.
DEFAULT_IMAGE = (
    "ghcr.io/cms-cambridge/pyleman2000-octave"
    "@sha256:5883205b24d085ad4c03b46735ac849105109138f4aec9213ee8d8f3c05b4575"
)
# Local contributor tag from ./scripts/build_octave_image.sh
LOCAL_DEV_IMAGE = "pyleman2000-octave:dev"
CONTAINER_INPUT_PATH = "/input.wav"
CONTAINER_OUTPUT_DIR = "/output"
CONTAINER_PLATFORM = "linux/amd64"
CONTAINER_ENTRYPOINT = "/leman_2000_docker.sh"
WARM_KEEPALIVE_COMMAND = ["sleep", "infinity"]
DEFAULT_TIMEOUT_SEC = 600.0
_PLATFORM_ENV = "PYLEMAN2000_DOCKER_PLATFORM"
_BUILD_IMAGE_HINT = (
    "Build it from this repository with:\n"
    "  ./scripts/build_octave_image.sh\n"
    "See docker/octave/ and the README for details."
)
_MATLAB_BUILD_HINT = (
    "Build the compiled MATLAB worker on a Linux host with MATLAB Compiler:\n"
    "  ./scripts/build_matlab_image.sh\n"
    "See docker/matlab/README.md. Published images live at\n"
    "  ghcr.io/cms-cambridge/pyleman2000-matlab"
)


class Leman2000DockerError(RuntimeError):
    """Raised when the Docker-backed model fails to run."""


class Leman2000WorkerError(Leman2000DockerError):
    """Raised when a warm worker is unsafe to reuse."""


def _platform_override() -> str:
    """Return the container platform (default ``linux/amd64``).

    Override with ``PYLEMAN2000_DOCKER_PLATFORM`` if needed. The published
    image is amd64-only; on Apple Silicon Docker Desktop uses Rosetta/QEMU.
    """
    value = os.environ.get(_PLATFORM_ENV, "").strip()
    return value or CONTAINER_PLATFORM


def _with_platform(kwargs: dict[str, Any]) -> dict[str, Any]:
    return {**kwargs, "platform": _platform_override()}


def _validate_timeout_sec(timeout_sec: float | None) -> float | None:
    if timeout_sec is None:
        return None
    timeout_sec = float(timeout_sec)
    if not math.isfinite(timeout_sec) or timeout_sec <= 0:
        raise ValueError("timeout_sec must be a finite positive number or None")
    return timeout_sec


def _model_command(
    output_path: str,
    local_decay_sec: Sequence[float],
    global_decay_sec: Sequence[float],
    detail: int,
) -> list[str]:
    return [
        CONTAINER_INPUT_PATH,
        output_path,
        _format_decay_list(local_decay_sec),
        _format_decay_list(global_decay_sec),
        str(int(detail)),
    ]


def _format_decay_list(values: Sequence[float]) -> str:
    return ",".join(str(float(v)) for v in values)


def _is_local_build_image(image: str) -> bool:
    """Return True for images that must be built locally, not pulled."""
    name = image.split("@", 1)[0]
    repository, _tag = parse_repository_tag(name)
    # Bare local tags (no registry). Published GHCR images remain pullable.
    return repository in {
        "pyleman2000-octave",
        "pyleman2000-matlab",
        "pyleman2000-matlab-worker",
        "pyleman2000-matlab-runtime",
    }


def _missing_local_image_error(image: str) -> Leman2000DockerError:
    name = image.split("@", 1)[0]
    repository, _tag = parse_repository_tag(name)
    if repository in {
        "pyleman2000-matlab",
        "pyleman2000-matlab-worker",
        "pyleman2000-matlab-runtime",
    }:
        hint = _MATLAB_BUILD_HINT
    else:
        hint = _BUILD_IMAGE_HINT
    return Leman2000DockerError(
        f"Docker image {image!r} is not available locally. {hint}"
    )


def _pull_error(image: str, detail: object) -> Leman2000DockerError:
    return Leman2000DockerError(
        f"Failed to pull Docker image {image!r}. "
        f"Underlying error: {detail}"
    )


def _repository_and_ref(image: str) -> tuple[str, str]:
    if "@" in image:
        repository, digest = image.split("@", 1)
        return repository, digest
    repository, tag = parse_repository_tag(image)
    return repository, tag or "latest"


def _pull_image(
    client: docker.DockerClient, image: str, *, show_progress: bool
) -> None:
    pull_kwargs = _with_platform({})
    if not show_progress:
        client.images.pull(image, **pull_kwargs)
        return

    repository, ref = _repository_and_ref(image)
    events = client.api.pull(
        repository,
        tag=ref,
        stream=True,
        decode=True,
        **pull_kwargs,
    )
    progress = PullProgress(image)
    try:
        for event in events:
            if isinstance(event, dict) and event.get("error"):
                raise _pull_error(image, event["error"])
            progress.update(event)
    finally:
        progress.close()


def _ensure_image(
    client: docker.DockerClient, image: str, *, show_progress: bool
) -> None:
    try:
        client.images.get(image)
        return
    except ImageNotFound:
        pass
    except DockerException as exc:
        raise Leman2000DockerError(
            f"Failed to inspect Docker image {image!r}: {exc}"
        ) from exc

    if _is_local_build_image(image):
        raise _missing_local_image_error(image)

    try:
        _pull_image(client, image, show_progress=show_progress)
    except APIError as exc:
        raise _pull_error(image, exc) from exc


@contextmanager
def _docker_client(
    client: docker.DockerClient | None,
) -> Iterator[docker.DockerClient]:
    """Yield a Docker client, closing one created for this call."""
    if client is not None:
        yield client
        return

    try:
        owned = docker.from_env()
    except DockerException as exc:
        raise Leman2000DockerError(
            "pyLeman2000 could not connect to Docker. Install Docker "
            "Desktop or the Docker Engine, start the daemon, and "
            "verify that `docker info` succeeds. See the README "
            "Docker setup notes for platform-specific guidance "
            "(including Apple Silicon)."
        ) from exc

    try:
        yield owned
    finally:
        try:
            owned.close()
        except DockerException:
            pass


def _build_input_archive(input_file: Path) -> BinaryIO:
    """Build a tar archive holding the input file and an empty output directory.

    The archive is copied into the container rather than bind-mounted, because
    bind mounts fail whenever the host path lies outside the directories the
    Docker daemon is allowed to share (for example a WAV file inside
    ``site-packages`` on macOS, or any host path with a remote daemon).
    """
    archive = tempfile.TemporaryFile()
    try:
        with tarfile.open(fileobj=archive, mode="w") as tar:
            entry = tar.gettarinfo(
                str(input_file), arcname=CONTAINER_INPUT_PATH.lstrip("/")
            )
            entry.mode = 0o644
            entry.uid = entry.gid = 0
            entry.uname = entry.gname = ""
            with input_file.open("rb") as source:
                tar.addfile(entry, source)

            output_dir = tarfile.TarInfo(CONTAINER_OUTPUT_DIR.lstrip("/"))
            output_dir.type = tarfile.DIRTYPE
            output_dir.mode = 0o777
            tar.addfile(output_dir)
        archive.seek(0)
        return archive
    except BaseException:
        archive.close()
        raise


def _heartbeat_during_wait(
    progress: RunProgress, stop: threading.Event, started_at: float
) -> None:
    """Update ``progress`` with elapsed runtime until ``stop`` is set."""
    while not stop.wait(1.0):
        progress.running(time.monotonic() - started_at)


def _wait_for_container(
    container: Container,
    timeout_sec: float | None,
    *,
    progress: RunProgress | None = None,
) -> None:
    """Block until ``container`` exits successfully.

    Raises
    ------
    Leman2000DockerError
        If the wait times out or the container exits with a non-zero status.
    """
    stop = threading.Event()
    heartbeat: threading.Thread | None = None
    if progress is not None:
        started_at = time.monotonic()
        progress.running(0.0)
        heartbeat = threading.Thread(
            target=_heartbeat_during_wait,
            args=(progress, stop, started_at),
            daemon=True,
        )
        heartbeat.start()

    try:
        try:
            wait_result = (
                container.wait()
                if timeout_sec is None
                else container.wait(timeout=timeout_sec)
            )
        except Timeout as exc:
            duration = (
                f" after {timeout_sec:g} seconds"
                if timeout_sec is not None
                else ""
            )
            raise Leman2000DockerError(
                f"The Leman (2000) Docker container timed out{duration}."
            ) from exc
    finally:
        stop.set()
        if heartbeat is not None:
            heartbeat.join(timeout=2.0)

    exit_status = int(wait_result.get("StatusCode", -1))
    if exit_status == 0:
        return

    stderr_value = container.logs(stdout=False, stderr=True)
    stderr = (
        stderr_value.decode("utf-8", errors="replace")
        if isinstance(stderr_value, (bytes, bytearray))
        else str(stderr_value)
    )
    raise Leman2000DockerError(
        "The Leman (2000) Docker container failed "
        f"(exit status {exit_status})."
        f"{(' stderr: ' + stderr) if stderr else ''}"
    )


def _read_output_json(container: Container, container_path: str) -> dict[str, Any]:
    """Copy the model output out of the container and parse it as JSON."""
    try:
        chunks, _ = container.get_archive(container_path)
    except NotFound as exc:
        raise Leman2000DockerError(
            f"Model finished but output file was not created: {container_path}"
        ) from exc

    with tempfile.TemporaryFile() as archive:
        for chunk in chunks:
            archive.write(chunk)
        archive.seek(0)
        try:
            with tarfile.open(fileobj=archive, mode="r|") as tar:
                member = tar.next()
                payload = tar.extractfile(member) if member is not None else None
                if payload is None:
                    raise Leman2000DockerError(
                        "Model finished but output file was not created: "
                        f"{container_path}"
                    )
                return json.load(payload)
        except (tarfile.TarError, OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise Leman2000DockerError(
                f"Model output was not valid JSON: {container_path}"
            ) from exc


def _raise_exec_failure(exit_status: int, output: object) -> None:
    if isinstance(output, (bytes, bytearray)):
        detail = output.decode("utf-8", errors="replace")
    else:
        detail = str(output) if output is not None else ""
    raise Leman2000DockerError(
        "The Leman (2000) Docker container failed "
        f"(exit status {exit_status})."
        f"{(' stderr: ' + detail) if detail else ''}"
    )


def _exec_model(
    container: Container,
    command: Sequence[str],
    timeout_sec: float | None,
    *,
    progress: RunProgress | None = None,
) -> None:
    """Run the model entrypoint inside an already-started container."""
    stop = threading.Event()
    heartbeat: threading.Thread | None = None
    if progress is not None:
        started_at = time.monotonic()
        progress.running(0.0)
        heartbeat = threading.Thread(
            target=_heartbeat_during_wait,
            args=(progress, stop, started_at),
            daemon=True,
        )
        heartbeat.start()

    full_command = [CONTAINER_ENTRYPOINT, *command]
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(container.exec_run, full_command)
            try:
                if timeout_sec is None:
                    exit_code, output = future.result()
                else:
                    exit_code, output = future.result(timeout=timeout_sec)
            except FuturesTimeout as exc:
                future.cancel()
                duration = f" after {timeout_sec:g} seconds"
                raise Leman2000WorkerError(
                    f"The Leman (2000) Docker container timed out{duration}."
                ) from exc
    finally:
        stop.set()
        if heartbeat is not None:
            heartbeat.join(timeout=2.0)

    if int(exit_code) != 0:
        _raise_exec_failure(int(exit_code), output)


class WarmModelRunner:
    """Reuse one long-lived container across model runs via ``docker exec``.

    Octave still starts on every exec, but keeping the container alive warms
    filesystem caches and typically speeds up later runs on Apple Silicon
    (emulated amd64). Prefer this when analysing many files in one process.
    """

    def __init__(
        self,
        *,
        image: str = DEFAULT_IMAGE,
        client: docker.DockerClient | None = None,
        timeout_sec: float | None = DEFAULT_TIMEOUT_SEC,
        show_progress: bool = True,
    ) -> None:
        self._image = image
        self._client_arg = client
        self._timeout_sec = _validate_timeout_sec(timeout_sec)
        self._show_progress = show_progress
        self._client: docker.DockerClient | None = None
        self._owns_client = False
        self._container: Container | None = None

    def open(self) -> WarmModelRunner:
        """Pull the image if needed and start the keepalive container."""
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
                    "verify that `docker info` succeeds. See the README "
                    "Docker setup notes for platform-specific guidance "
                    "(including Apple Silicon)."
                ) from exc
            self._owns_client = True

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

        try:
            self._container = self._client.containers.create(
                **_with_platform(
                    {
                        "image": self._image,
                        "entrypoint": WARM_KEEPALIVE_COMMAND,
                    }
                )
            )
            self._container.start()
        except ImageNotFound as exc:
            self.close()
            raise Leman2000DockerError(
                f"Docker image not found: {self._image!r}"
            ) from exc
        except APIError as exc:
            self.close()
            raise Leman2000DockerError(
                f"Docker API error while starting warm container for "
                f"{self._image!r}: {exc}"
            ) from exc
        return self

    def close(self) -> None:
        """Stop and remove the keepalive container."""
        container = self._container
        self._container = None
        if container is not None:
            try:
                container.remove(force=True)
            except DockerException:
                pass

        if self._owns_client and self._client is not None:
            try:
                self._client.close()
            except DockerException:
                pass
        self._client = None
        self._owns_client = False

    def __enter__(self) -> WarmModelRunner:
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
        """Copy input in, exec the model, and return parsed JSON."""
        if self._container is None:
            raise Leman2000WorkerError(
                "WarmModelRunner is not open. Use it as a context manager "
                "or call open() before run()."
            )

        input_file = Path(input_file).resolve()
        if not input_file.is_file():
            raise FileNotFoundError(f"Input file not found: {input_file}")

        output_path = f"{CONTAINER_OUTPUT_DIR}/{uuid.uuid4()}.json"
        command = _model_command(
            output_path, local_decay_sec, global_decay_sec, detail
        )
        progress = RunProgress() if self._show_progress else None
        try:
            if progress is not None:
                progress.preparing()
            with _build_input_archive(input_file) as archive:
                self._container.put_archive("/", archive)
            _exec_model(
                self._container,
                command,
                self._timeout_sec,
                progress=progress,
            )
            if progress is not None:
                progress.reading()
            return _read_output_json(self._container, output_path)
        except APIError as exc:
            raise Leman2000WorkerError(
                f"Docker API error while running {self._image!r}: {exc}"
            ) from exc
        finally:
            if progress is not None:
                progress.close()


def _run_container(
    client: docker.DockerClient,
    *,
    image: str,
    command: Sequence[str],
    input_file: Path,
    output_path: str,
    timeout_sec: float | None,
    show_progress: bool,
) -> dict[str, Any]:
    """Create a container, copy input in, run it, and copy JSON output out."""
    container = None
    progress = RunProgress() if show_progress else None
    try:
        if progress is not None:
            progress.preparing()
        container = client.containers.create(
            **_with_platform(
                {
                    "image": image,
                    "command": list(command),
                }
            )
        )
        with _build_input_archive(input_file) as archive:
            container.put_archive("/", archive)
        container.start()
        _wait_for_container(container, timeout_sec, progress=progress)
        if progress is not None:
            progress.reading()
        return _read_output_json(container, output_path)
    except ImageNotFound as exc:
        raise Leman2000DockerError(f"Docker image not found: {image!r}") from exc
    except APIError as exc:
        raise Leman2000DockerError(
            f"Docker API error while running {image!r}: {exc}"
        ) from exc
    finally:
        if progress is not None:
            progress.close()
        if container is not None:
            try:
                container.remove(force=True)
            except DockerException:
                pass


def run_model(
    input_file: Path,
    local_decay_sec: Sequence[float],
    global_decay_sec: Sequence[float],
    *,
    detail: int = 0,
    image: str = DEFAULT_IMAGE,
    client: docker.DockerClient | None = None,
    timeout_sec: float | None = DEFAULT_TIMEOUT_SEC,
    show_progress: bool = True,
) -> dict[str, Any]:
    """Run the Octave model in Docker and return parsed JSON.

    The input file is copied into the container and the output is copied back
    out again, so no host directory needs to be shared with Docker.

    Parameters
    ----------
    input_file :
        Absolute path to a ``.wav`` file on the host.
    local_decay_sec :
        Local decay parameter values in seconds.
    global_decay_sec :
        Global decay parameter values in seconds.
    detail :
        Detail level forwarded to the model. Values ``> 1`` include auditory
        nerve and periodicity pitch images.
    image :
        Docker image name. Defaults to :data:`DEFAULT_IMAGE` on GHCR
        (pulled automatically on first use). Local builds can pass
        ``pyleman2000-octave:dev`` from ``./scripts/build_octave_image.sh``.
    client :
        Optional Docker client. Created with :func:`docker.from_env` if omitted.
    timeout_sec :
        Maximum container runtime in seconds. Set to None for no timeout.
    show_progress :
        If True, report image download (for pullable images) and model-run
        status on standard error.

    Returns
    -------
    dict
        Parsed model JSON output.

    Raises
    ------
    Leman2000DockerError
        If Docker is unavailable, the image cannot be pulled or built, or the
        container exits unsuccessfully.
    """
    input_file = Path(input_file).resolve()
    if not input_file.is_file():
        raise FileNotFoundError(f"Input file not found: {input_file}")
    timeout_sec = _validate_timeout_sec(timeout_sec)

    with _docker_client(client) as client_obj:
        try:
            _ensure_image(client_obj, image, show_progress=show_progress)
        except Leman2000DockerError:
            raise
        except DockerException as exc:
            raise Leman2000DockerError(
                f"Failed to prepare Docker image {image!r}. "
                f"Underlying error: {exc}"
            ) from exc

        output_path = f"{CONTAINER_OUTPUT_DIR}/{uuid.uuid4()}.json"
        return _run_container(
            client_obj,
            image=image,
            command=_model_command(
                output_path, local_decay_sec, global_decay_sec, detail
            ),
            input_file=input_file,
            output_path=output_path,
            timeout_sec=timeout_sec,
            show_progress=show_progress,
        )
