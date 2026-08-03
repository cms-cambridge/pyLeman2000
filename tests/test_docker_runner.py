"""Tests for the Docker runner with a mocked Docker SDK client."""

from __future__ import annotations

import io
import json
import tarfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from docker.errors import APIError, ImageNotFound, NotFound
from requests.exceptions import ReadTimeout

from pyleman2000 import example_wav_path
from pyleman2000.docker_runner import (
    CONTAINER_INPUT_PATH,
    CONTAINER_OUTPUT_DIR,
    CONTAINER_PLATFORM,
    DEFAULT_IMAGE,
    Leman2000DockerError,
    run_model,
)

PAYLOAD = {
    "audio_length_sec": 0.1,
    "num_channels": 1,
    "sample_rate": 44100,
    "local_global_comparison": [],
}


def _tar_archive(name: str, contents: bytes) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as tar:
        entry = tarfile.TarInfo(name)
        entry.size = len(contents)
        tar.addfile(entry, io.BytesIO(contents))
    return buffer.getvalue()


def _client_returning(contents: bytes, *, status_code: int = 0) -> MagicMock:
    """Build a mock client whose container yields ``contents`` as its output.

    The mock records archives copied into the container under
    ``client.copied_archives``, because the runner closes them once sent.
    """
    client = MagicMock()
    client.images.get.return_value = MagicMock()
    container = client.containers.create.return_value
    container.wait.return_value = {"StatusCode": status_code}

    def get_archive(path: str, *args: object, **kwargs: object):
        name = Path(path).name
        return iter([_tar_archive(name, contents)]), {"name": name}

    container.get_archive.side_effect = get_archive

    copied: list[tuple[str, bytes]] = []

    def put_archive(path: str, data) -> bool:
        copied.append((path, data.read()))
        return True

    container.put_archive.side_effect = put_archive
    client.copied_archives = copied
    return client


def test_run_model_copies_input_into_the_container() -> None:
    client = _client_returning(json.dumps(PAYLOAD).encode("utf-8"))
    container = client.containers.create.return_value

    result = run_model(
        example_wav_path(),
        local_decay_sec=[0.1],
        global_decay_sec=[1.0, 2.0],
        detail=0,
        client=client,
    )

    assert result == PAYLOAD
    _, create_kwargs = client.containers.create.call_args
    assert create_kwargs["image"] == DEFAULT_IMAGE
    assert create_kwargs["platform"] == CONTAINER_PLATFORM
    assert create_kwargs["command"][0] == CONTAINER_INPUT_PATH
    assert create_kwargs["command"][1].startswith(f"{CONTAINER_OUTPUT_DIR}/")
    assert create_kwargs["command"][2] == "0.1"
    assert create_kwargs["command"][3] == "1.0,2.0"
    assert create_kwargs["command"][4] == "0"

    # No host path is bind-mounted; Docker Desktop file sharing is irrelevant.
    assert "volumes" not in create_kwargs

    (destination, archive), = client.copied_archives
    assert destination == "/"
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r") as tar:
        members = {member.name: member for member in tar.getmembers()}
        assert members[CONTAINER_OUTPUT_DIR.lstrip("/")].isdir()
        copied = tar.extractfile(CONTAINER_INPUT_PATH.lstrip("/"))
        assert copied is not None
        assert copied.read() == example_wav_path().read_bytes()

    container.start.assert_called_once_with()
    container.wait.assert_called_once_with(timeout=600.0)
    container.remove.assert_called_once_with(force=True)


def test_run_model_surfaces_container_error() -> None:
    client = _client_returning(b"", status_code=1)
    container = client.containers.create.return_value
    container.logs.return_value = b"boom"

    with pytest.raises(Leman2000DockerError, match="boom"):
        run_model(
            example_wav_path(),
            local_decay_sec=[0.1],
            global_decay_sec=[1.0],
            client=client,
        )
    container.remove.assert_called_once_with(force=True)


def test_run_model_pulls_a_missing_image() -> None:
    client = _client_returning(json.dumps(PAYLOAD).encode("utf-8"))
    client.images.get.side_effect = ImageNotFound("missing")

    run_model(
        example_wav_path(),
        local_decay_sec=[0.1],
        global_decay_sec=[1.0],
        client=client,
    )

    client.images.pull.assert_called_once_with(DEFAULT_IMAGE)


def test_run_model_wraps_image_lookup_errors() -> None:
    client = MagicMock()
    client.images.get.side_effect = APIError("daemon failed")

    with pytest.raises(Leman2000DockerError, match="inspect Docker image"):
        run_model(
            example_wav_path(),
            local_decay_sec=[0.1],
            global_decay_sec=[1.0],
            client=client,
        )


def test_run_model_times_out_and_removes_container() -> None:
    client = _client_returning(b"")
    container = client.containers.create.return_value
    container.wait.side_effect = ReadTimeout("timed out")

    with pytest.raises(Leman2000DockerError, match="timed out"):
        run_model(
            example_wav_path(),
            local_decay_sec=[0.1],
            global_decay_sec=[1.0],
            timeout_sec=0.1,
            client=client,
        )

    container.remove.assert_called_once_with(force=True)


def test_run_model_wraps_invalid_json() -> None:
    client = _client_returning(b"not json")

    with pytest.raises(Leman2000DockerError, match="valid JSON"):
        run_model(
            example_wav_path(),
            local_decay_sec=[0.1],
            global_decay_sec=[1.0],
            client=client,
        )


def test_run_model_rejects_missing_input(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="Input file not found"):
        run_model(
            tmp_path / "missing.wav",
            local_decay_sec=[0.1],
            global_decay_sec=[1.0],
            client=MagicMock(),
        )


def test_run_model_wraps_pull_failures() -> None:
    client = MagicMock()
    client.images.get.side_effect = ImageNotFound("missing")
    client.images.pull.side_effect = APIError("pull denied")

    with pytest.raises(Leman2000DockerError, match="about 1 GB"):
        run_model(
            example_wav_path(),
            local_decay_sec=[0.1],
            global_decay_sec=[1.0],
            client=client,
        )


def test_run_model_requires_output_file() -> None:
    client = _client_returning(b"")
    container = client.containers.create.return_value
    container.get_archive.side_effect = NotFound("no such file")

    with pytest.raises(Leman2000DockerError, match="output file was not created"):
        run_model(
            example_wav_path(),
            local_decay_sec=[0.1],
            global_decay_sec=[1.0],
            client=client,
        )


def test_run_model_rejects_invalid_timeout() -> None:
    with pytest.raises(ValueError, match="timeout_sec"):
        run_model(
            example_wav_path(),
            local_decay_sec=[0.1],
            global_decay_sec=[1.0],
            timeout_sec=0,
            client=MagicMock(),
        )


def test_run_model_allows_unlimited_timeout() -> None:
    client = _client_returning(json.dumps(PAYLOAD).encode("utf-8"))
    container = client.containers.create.return_value

    result = run_model(
        example_wav_path(),
        local_decay_sec=[0.1],
        global_decay_sec=[1.0],
        timeout_sec=None,
        client=client,
    )

    assert result == PAYLOAD
    container.wait.assert_called_once_with()
