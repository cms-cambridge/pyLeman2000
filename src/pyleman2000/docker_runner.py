"""Docker client helpers for running the compiled Leman (2000) model."""

from __future__ import annotations

import json
import math
import tarfile
import tempfile
import uuid
from pathlib import Path
from typing import Any, BinaryIO, Sequence

import docker
from docker.errors import APIError, DockerException, ImageNotFound, NotFound
from docker.models.containers import Container
from docker.utils import parse_repository_tag
from requests.exceptions import Timeout

from pyleman2000.progress import PullProgress

DEFAULT_IMAGE = (
    "ghcr.io/pmcharrison/leman_2000"
    "@sha256:08d5ce84b9844954473832af65188f8f56fdfc8bcc3c64e0307e532a062e2442"
)
CONTAINER_INPUT_PATH = "/input.wav"
CONTAINER_OUTPUT_DIR = "/output"
CONTAINER_PLATFORM = "linux/amd64"
DEFAULT_TIMEOUT_SEC = 600.0


class Leman2000DockerError(RuntimeError):
    """Raised when the Docker-backed model fails to run."""


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
        If True, report image download progress on standard error.

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
    if timeout_sec is not None:
        timeout_sec = float(timeout_sec)
        if not math.isfinite(timeout_sec) or timeout_sec <= 0:
            raise ValueError("timeout_sec must be a finite positive number or None")

    owns_client = client is None
    client_obj: docker.DockerClient | None = client
    try:
        if client_obj is None:
            try:
                client_obj = docker.from_env()
            except DockerException as exc:
                raise Leman2000DockerError(
                    "pyLeman2000 could not connect to Docker. Install Docker "
                    "Desktop or the Docker Engine, start the daemon, and "
                    "verify that `docker info` succeeds. See the README "
                    "Docker setup notes for platform-specific guidance "
                    "(including Apple Silicon)."
                ) from exc

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
        command = [
            CONTAINER_INPUT_PATH,
            output_path,
            _format_decay_list(local_decay_sec),
            _format_decay_list(global_decay_sec),
            str(int(detail)),
        ]

        container = None
        try:
            container = client_obj.containers.create(
                image=image,
                command=command,
                platform=CONTAINER_PLATFORM,
            )
            with _build_input_archive(input_file) as archive:
                container.put_archive("/", archive)
            container.start()

            try:
                wait_result = (
                    container.wait()
                    if timeout_sec is None
                    else container.wait(timeout=timeout_sec)
                )
            except Timeout as exc:
                duration = (
                    f" after {timeout_sec:g} seconds" if timeout_sec is not None else ""
                )
                raise Leman2000DockerError(
                    f"The Leman (2000) Docker container timed out{duration}."
                ) from exc

            exit_status = int(wait_result.get("StatusCode", -1))
            if exit_status != 0:
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

            return _read_output_json(container, output_path)
        except ImageNotFound as exc:
            raise Leman2000DockerError(f"Docker image not found: {image!r}") from exc
        except APIError as exc:
            raise Leman2000DockerError(
                f"Docker API error while running {image!r}: {exc}"
            ) from exc
        finally:
            if container is not None:
                try:
                    container.remove(force=True)
                except DockerException:
                    pass
    finally:
        if owns_client and client_obj is not None:
            try:
                client_obj.close()
            except DockerException:
                pass
