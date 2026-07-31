"""Docker client helpers for running the compiled Leman (2000) model."""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Sequence

import docker
from docker.errors import APIError, ContainerError, DockerException, ImageNotFound

DEFAULT_IMAGE = "ghcr.io/pmcharrison/leman_2000:latest"
INPUT_MOUNT = "/input.wav"
OUTPUT_MOUNT = "/output"


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


def run_model(
    input_file: Path,
    local_decay_sec: Sequence[float],
    global_decay_sec: Sequence[float],
    *,
    detail: int = 0,
    image: str = DEFAULT_IMAGE,
    client: docker.DockerClient | None = None,
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
            host_input = tmp_dir / "input.wav"
            host_input.write_bytes(input_file.read_bytes())
            host_output_dir = tmp_dir / "output"
            host_output_dir.mkdir()

            command = [
                "input.wav",
                f"output/{output_name}",
                _format_decay_list(local_decay_sec),
                _format_decay_list(global_decay_sec),
                str(int(detail)),
            ]
            volumes = {
                str(host_input): {"bind": INPUT_MOUNT, "mode": "ro"},
                str(host_output_dir): {"bind": OUTPUT_MOUNT, "mode": "rw"},
            }

            try:
                client_obj.containers.run(
                    image=image,
                    command=command,
                    volumes=volumes,
                    remove=True,
                    stdout=True,
                    stderr=True,
                )
            except ContainerError as exc:
                stderr = ""
                if exc.stderr:
                    stderr = (
                        exc.stderr.decode("utf-8", errors="replace")
                        if isinstance(exc.stderr, (bytes, bytearray))
                        else str(exc.stderr)
                    )
                raise Leman2000DockerError(
                    "The Leman (2000) Docker container failed "
                    f"(exit status {exc.exit_status})."
                    f"{(' stderr: ' + stderr) if stderr else ''}"
                ) from exc
            except ImageNotFound as exc:
                raise Leman2000DockerError(
                    f"Docker image not found: {image!r}"
                ) from exc
            except APIError as exc:
                raise Leman2000DockerError(
                    f"Docker API error while running {image!r}: {exc}"
                ) from exc

            output_path = host_output_dir / output_name
            if not output_path.is_file():
                raise Leman2000DockerError(
                    f"Model finished but output file was not created: {output_path}"
                )
            return json.loads(output_path.read_text(encoding="utf-8"))
    finally:
        if owns_client and client_obj is not None:
            try:
                client_obj.close()
            except Exception:
                pass
