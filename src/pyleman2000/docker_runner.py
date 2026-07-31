"""Docker client helpers for running the compiled Leman (2000) model."""

from __future__ import annotations

import json
import math
import uuid
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Sequence

import docker
from docker.errors import APIError, DockerException, ImageNotFound
from requests.exceptions import Timeout

DEFAULT_IMAGE = (
    "ghcr.io/pmcharrison/leman_2000"
    "@sha256:08d5ce84b9844954473832af65188f8f56fdfc8bcc3c64e0307e532a062e2442"
)
INPUT_MOUNT = "/input.wav"
OUTPUT_MOUNT = "/output"
DEFAULT_TIMEOUT_SEC = 600.0


class Leman2000DockerError(RuntimeError):
    """Raised when the Docker-backed model fails to run."""


def _format_decay_list(values: Sequence[float]) -> str:
    return ",".join(str(float(v)) for v in values)


def _ensure_image(client: docker.DockerClient, image: str) -> None:
    try:
        client.images.get(image)
    except ImageNotFound:
        try:
            client.images.pull(image)
        except APIError as exc:
            raise Leman2000DockerError(
                f"Failed to pull Docker image {image!r}: {exc}"
            ) from exc
    except DockerException as exc:
        raise Leman2000DockerError(
            f"Failed to inspect Docker image {image!r}: {exc}"
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
) -> dict[str, Any]:
    """Run the compiled model in Docker and return parsed JSON.

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
                    "Could not connect to Docker. Is the Docker daemon running?"
                ) from exc

        _ensure_image(client_obj, image)

        output_name = f"{uuid.uuid4()}.json"
        with TemporaryDirectory(prefix="pyleman2000-") as tmp:
            tmp_dir = Path(tmp)
            host_output_dir = tmp_dir / "output"
            host_output_dir.mkdir()

            command = [
                INPUT_MOUNT,
                f"{OUTPUT_MOUNT}/{output_name}",
                _format_decay_list(local_decay_sec),
                _format_decay_list(global_decay_sec),
                str(int(detail)),
            ]
            volumes = {
                str(input_file): {"bind": INPUT_MOUNT, "mode": "ro"},
                str(host_output_dir): {"bind": OUTPUT_MOUNT, "mode": "rw"},
            }

            container = None
            try:
                container = client_obj.containers.run(
                    image=image,
                    command=command,
                    volumes=volumes,
                    detach=True,
                    stdout=True,
                    stderr=True,
                    platform="linux/amd64",
                )
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
            except ImageNotFound as exc:
                raise Leman2000DockerError(
                    f"Docker image not found: {image!r}"
                ) from exc
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

            output_path = host_output_dir / output_name
            if not output_path.is_file():
                raise Leman2000DockerError(
                    f"Model finished but output file was not created: {output_path}"
                )
            try:
                return json.loads(output_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                raise Leman2000DockerError(
                    f"Model output was not valid JSON: {output_path}"
                ) from exc
    finally:
        if owns_client and client_obj is not None:
            try:
                client_obj.close()
            except DockerException:
                pass
