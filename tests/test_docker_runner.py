"""Tests for the Docker runner with a mocked Docker SDK client."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from docker.errors import APIError, ImageNotFound
from requests.exceptions import ReadTimeout

from pyleman2000 import example_wav_path
from pyleman2000.docker_runner import (
    DEFAULT_IMAGE,
    INPUT_MOUNT,
    Leman2000DockerError,
    OUTPUT_MOUNT,
    run_model,
)


def test_run_model_writes_and_reads_output(tmp_path: Path) -> None:
    payload = {
        "audio_length_sec": 0.1,
        "num_channels": 1,
        "sample_rate": 44100,
        "local_global_comparison": [],
    }

    container = MagicMock()
    container.wait.return_value = {"StatusCode": 0}

    def fake_run(*, image, command, volumes, **kwargs):
        # volumes maps host path -> bind config; find the output dir mount
        output_dir = None
        for host, cfg in volumes.items():
            if cfg["bind"] == OUTPUT_MOUNT:
                output_dir = Path(host)
        assert output_dir is not None
        out_name = Path(command[1]).name
        (output_dir / out_name).write_text(json.dumps(payload), encoding="utf-8")
        return container

    client = MagicMock()
    client.images.get.return_value = MagicMock()
    client.containers.run.side_effect = fake_run

    result = run_model(
        example_wav_path(),
        local_decay_sec=[0.1],
        global_decay_sec=[1.0, 2.0],
        detail=0,
        client=client,
    )

    assert result == payload
    args, kwargs = client.containers.run.call_args
    assert kwargs["image"] == DEFAULT_IMAGE
    assert kwargs["command"][0] == INPUT_MOUNT
    assert kwargs["command"][1].startswith(f"{OUTPUT_MOUNT}/")
    assert kwargs["command"][2] == "0.1"
    assert kwargs["command"][3] == "1.0,2.0"
    assert kwargs["command"][4] == "0"
    assert kwargs["detach"] is True
    assert kwargs["platform"] == "linux/amd64"
    assert kwargs["volumes"][str(example_wav_path().resolve())] == {
        "bind": INPUT_MOUNT,
        "mode": "ro",
    }
    container.wait.assert_called_once_with(timeout=600.0)
    container.remove.assert_called_once_with(force=True)


def test_run_model_surfaces_container_error() -> None:
    client = MagicMock()
    client.images.get.return_value = MagicMock()
    container = client.containers.run.return_value
    container.wait.return_value = {"StatusCode": 1}
    container.logs.return_value = b"boom"

    with pytest.raises(Leman2000DockerError, match="boom"):
        run_model(
            example_wav_path(),
            local_decay_sec=[0.1],
            global_decay_sec=[1.0],
            client=client,
        )
    container.remove.assert_called_once_with(force=True)


def test_run_model_pulls_a_missing_image(tmp_path: Path) -> None:
    payload = {
        "audio_length_sec": 0.1,
        "num_channels": 1,
        "sample_rate": 44100,
        "local_global_comparison": [],
    }
    client = MagicMock()
    client.images.get.side_effect = ImageNotFound("missing")
    container = client.containers.run.return_value
    container.wait.return_value = {"StatusCode": 0}

    def write_output(*, command, volumes, **kwargs):
        output_dir = next(
            Path(host)
            for host, config in volumes.items()
            if config["bind"] == OUTPUT_MOUNT
        )
        (output_dir / Path(command[1]).name).write_text(json.dumps(payload))
        return container

    client.containers.run.side_effect = write_output

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
    client = MagicMock()
    client.images.get.return_value = MagicMock()
    container = client.containers.run.return_value
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
    client = MagicMock()
    client.images.get.return_value = MagicMock()
    container = client.containers.run.return_value
    container.wait.return_value = {"StatusCode": 0}

    def write_invalid_output(*, command, volumes, **kwargs):
        output_dir = next(
            Path(host)
            for host, config in volumes.items()
            if config["bind"] == OUTPUT_MOUNT
        )
        (output_dir / Path(command[1]).name).write_text("not json")
        return container

    client.containers.run.side_effect = write_invalid_output

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
    client = MagicMock()
    client.images.get.return_value = MagicMock()
    container = client.containers.run.return_value
    container.wait.return_value = {"StatusCode": 0}

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
    payload = {
        "audio_length_sec": 0.1,
        "num_channels": 1,
        "sample_rate": 44100,
        "local_global_comparison": [],
    }
    client = MagicMock()
    client.images.get.return_value = MagicMock()
    container = client.containers.run.return_value
    container.wait.return_value = {"StatusCode": 0}

    def write_output(*, command, volumes, **kwargs):
        output_dir = next(
            Path(host)
            for host, config in volumes.items()
            if config["bind"] == OUTPUT_MOUNT
        )
        (output_dir / Path(command[1]).name).write_text(json.dumps(payload))
        return container

    client.containers.run.side_effect = write_output

    result = run_model(
        example_wav_path(),
        local_decay_sec=[0.1],
        global_decay_sec=[1.0],
        timeout_sec=None,
        client=client,
    )

    assert result == payload
    container.wait.assert_called_once_with()
