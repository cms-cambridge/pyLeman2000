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
    DEFAULT_IMAGE,
    LOCAL_DEV_IMAGE,
    Leman2000DockerError,
    WarmModelRunner,
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
    assert "platform" not in create_kwargs
    assert create_kwargs["command"][0] == CONTAINER_INPUT_PATH
    assert create_kwargs["command"][1].startswith(f"{CONTAINER_OUTPUT_DIR}/")
    assert create_kwargs["command"][2] == "0.1"
    assert create_kwargs["command"][3] == "1.0,2.0"
    assert create_kwargs["command"][4] == "0"

    # No host path is bind-mounted; Docker Desktop file sharing is irrelevant.
    assert "volumes" not in create_kwargs

    ((destination, archive),) = client.copied_archives
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


def test_run_model_pulls_a_missing_image_with_progress() -> None:
    client = _client_returning(json.dumps(PAYLOAD).encode("utf-8"))
    client.images.get.side_effect = ImageNotFound("missing")
    client.api.pull.return_value = [
        {"id": "layer", "status": "Downloading", "progressDetail": {"current": 1}}
    ]
    remote_image = "ghcr.io/example/leman@sha256:abc"

    run_model(
        example_wav_path(),
        local_decay_sec=[0.1],
        global_decay_sec=[1.0],
        image=remote_image,
        client=client,
    )

    repository, digest = remote_image.split("@")
    client.api.pull.assert_called_once_with(
        repository,
        tag=digest,
        stream=True,
        decode=True,
    )
    client.images.pull.assert_not_called()


def test_run_model_pulls_without_progress_when_disabled() -> None:
    client = _client_returning(json.dumps(PAYLOAD).encode("utf-8"))
    client.images.get.side_effect = ImageNotFound("missing")
    remote_image = "ghcr.io/example/leman:latest"

    run_model(
        example_wav_path(),
        local_decay_sec=[0.1],
        global_decay_sec=[1.0],
        image=remote_image,
        client=client,
        show_progress=False,
    )

    client.images.pull.assert_called_once_with(remote_image)
    client.api.pull.assert_not_called()


def test_run_model_pulls_default_image_when_missing() -> None:
    client = _client_returning(json.dumps(PAYLOAD).encode("utf-8"))
    client.images.get.side_effect = ImageNotFound("missing")

    run_model(
        example_wav_path(),
        local_decay_sec=[0.1],
        global_decay_sec=[1.0],
        client=client,
        show_progress=False,
    )

    client.images.pull.assert_called_once_with(DEFAULT_IMAGE)


def test_run_model_requires_local_build_for_dev_image() -> None:
    client = MagicMock()
    client.images.get.side_effect = ImageNotFound("missing")

    with pytest.raises(Leman2000DockerError, match="build_octave_image"):
        run_model(
            example_wav_path(),
            local_decay_sec=[0.1],
            global_decay_sec=[1.0],
            image=LOCAL_DEV_IMAGE,
            client=client,
        )

    client.images.pull.assert_not_called()
    client.api.pull.assert_not_called()


def test_run_model_respects_platform_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client_returning(json.dumps(PAYLOAD).encode("utf-8"))
    monkeypatch.setenv("PYLEMAN2000_DOCKER_PLATFORM", "linux/amd64")

    run_model(
        example_wav_path(),
        local_decay_sec=[0.1],
        global_decay_sec=[1.0],
        client=client,
        show_progress=False,
    )

    _, create_kwargs = client.containers.create.call_args
    assert create_kwargs["platform"] == "linux/amd64"


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
    client.api.pull.side_effect = APIError("pull denied")

    with pytest.raises(Leman2000DockerError, match="Failed to pull"):
        run_model(
            example_wav_path(),
            local_decay_sec=[0.1],
            global_decay_sec=[1.0],
            image="ghcr.io/example/leman:latest",
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


def test_run_model_reports_run_progress(capsys: pytest.CaptureFixture[str]) -> None:
    client = _client_returning(json.dumps(PAYLOAD).encode("utf-8"))

    run_model(
        example_wav_path(),
        local_decay_sec=[0.1],
        global_decay_sec=[1.0],
        client=client,
        show_progress=True,
    )

    err = capsys.readouterr().err
    assert "Preparing Leman (2000) container" in err
    assert "Running Leman (2000) model:" in err
    assert "Reading Leman (2000) results" in err


def test_run_model_is_quiet_when_progress_disabled(
    capsys: pytest.CaptureFixture[str],
) -> None:
    client = _client_returning(json.dumps(PAYLOAD).encode("utf-8"))

    run_model(
        example_wav_path(),
        local_decay_sec=[0.1],
        global_decay_sec=[1.0],
        client=client,
        show_progress=False,
    )

    assert capsys.readouterr().err == ""


def test_warm_runner_reuses_one_container_via_exec() -> None:
    client = _client_returning(json.dumps(PAYLOAD).encode("utf-8"))
    container = client.containers.create.return_value
    container.exec_run.return_value = (0, b"")

    with WarmModelRunner(client=client, show_progress=False) as runner:
        first = runner.run(
            example_wav_path(),
            local_decay_sec=[0.1],
            global_decay_sec=[1.0],
        )
        second = runner.run(
            example_wav_path(),
            local_decay_sec=[0.5],
            global_decay_sec=[2.0],
            detail=5,
        )

    assert first == PAYLOAD
    assert second == PAYLOAD
    client.containers.create.assert_called_once()
    _, create_kwargs = client.containers.create.call_args
    assert create_kwargs["entrypoint"] == ["sleep", "infinity"]
    assert "platform" not in create_kwargs
    assert "command" not in create_kwargs
    container.start.assert_called_once_with()
    assert container.exec_run.call_count == 2
    first_cmd = container.exec_run.call_args_list[0].args[0]
    second_cmd = container.exec_run.call_args_list[1].args[0]
    assert first_cmd[0] == "/leman_2000_docker.sh"
    assert first_cmd[1] == CONTAINER_INPUT_PATH
    assert first_cmd[3:] == ["0.1", "1.0", "0"]
    assert second_cmd[3:] == ["0.5", "2.0", "5"]
    container.wait.assert_not_called()
    container.remove.assert_called_once_with(force=True)


def test_warm_runner_surfaces_exec_errors() -> None:
    client = _client_returning(b"")
    container = client.containers.create.return_value
    container.exec_run.return_value = (1, b"boom")

    with WarmModelRunner(client=client, show_progress=False) as runner:
        with pytest.raises(Leman2000DockerError, match="boom"):
            runner.run(
                example_wav_path(),
                local_decay_sec=[0.1],
                global_decay_sec=[1.0],
            )

    container.remove.assert_called_once_with(force=True)


def test_warm_runner_requires_open() -> None:
    runner = WarmModelRunner(client=MagicMock(), show_progress=False)
    with pytest.raises(Leman2000DockerError, match="not open"):
        runner.run(
            example_wav_path(),
            local_decay_sec=[0.1],
            global_decay_sec=[1.0],
        )
