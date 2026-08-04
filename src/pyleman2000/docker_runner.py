"""Docker client helpers for running the compiled Leman (2000) model."""

from __future__ import annotations

import json
import math
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

DEFAULT_IMAGE = (
    "ghcr.io/pmcharrison/leman_2000"
    "@sha256:08d5ce84b9844954473832af65188f8f56fdfc8bcc3c64e0307e532a062e2442"
)
CONTAINER_INPUT_PATH = "/input.wav"
CONTAINER_OUTPUT_DIR = "/output"
CONTAINER_PLATFORM = "linux/amd64"
CONTAINER_ENTRYPOINT = "/leman_2000_docker.sh"
WARM_KEEPALIVE_COMMAND = ["sleep", "infinity"]
DEFAULT_TIMEOUT_SEC = 600.0


class Leman2000DockerError(RuntimeError):
    """Raised when the Docker-backed model fails to run."""


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


def _pull_error(image: str, detail: object) -> Leman2000DockerError:
    return Leman2000DockerError(
        f"Failed to pull Docker image {image!r}. The first download "
        "is about 1 GB compressed and may take several minutes. "
        f"Underlying error: {detail}"
    )


def _pull_image(
    client: docker.DockerClient, image: str, *, show_progress: bool
) -> None:
    if not show_progress:
        client.images.pull(image, platform=CONTAINER_PLATFORM)
        return

    repository, tag = parse_repository_tag(image)
    events = client.api.pull(
        repository,
        tag=tag or "latest",
        platform=CONTAINER_PLATFORM,
        stream=True,
        decode=True,
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
                raise Leman2000DockerError(
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

    The MATLAB Compiler Runtime still starts on every exec, but keeping the
    container alive warms filesystem caches and typically speeds up later runs
    on Apple Silicon (emulated amd64). Prefer this when analysing many files
    in one process.
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
                f"Failed to prepare Docker image {self._image!r}. The first "
                "pull is about 1 GB compressed and can take several minutes "
                f"on a slow connection. Underlying error: {exc}"
            ) from exc

        try:
            self._container = self._client.containers.create(
                image=self._image,
                entrypoint=WARM_KEEPALIVE_COMMAND,
                platform=CONTAINER_PLATFORM,
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
            raise Leman2000DockerError(
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
            raise Leman2000DockerError(
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
            image=image,
            command=list(command),
            platform=CONTAINER_PLATFORM,
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
    """Run the compiled model in Docker and return parsed JSON.

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
        Detail level forwarded to the MATLAB binary. Values ``> 1`` include
        auditory nerve and periodicity pitch images.
    image :
        Docker image name.
    client :
        Optional Docker client. Created with :func:`docker.from_env` if omitted.
    timeout_sec :
        Maximum container runtime in seconds. Set to None for no timeout.
    show_progress :
        If True, report image download and model-run status on standard error.

    Returns
    -------
    dict
        Parsed model JSON output.

    Raises
    ------
    Leman2000DockerError
        If Docker is unavailable or the container exits unsuccessfully.
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
                f"Failed to prepare Docker image {image!r}. The first pull "
                "is about 1 GB compressed and can take several minutes on a "
                f"slow connection. Underlying error: {exc}"
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
