"""Tests for the Docker runner with a mocked Docker SDK client."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from docker.errors import ContainerError

from pyleman2000 import example_wav_path
from pyleman2000.docker_runner import Leman2000DockerError, run_model


def test_run_model_writes_and_reads_output(tmp_path: Path) -> None:
    payload = {
        "audio_length_sec": 0.1,
        "num_channels": 1,
        "sample_rate": 44100,
        "local_global_comparison": [],
    }

    def fake_run(*, image, command, volumes, **kwargs):
        # volumes maps host path -> bind config; find the output dir mount
        output_dir = None
        for host, cfg in volumes.items():
            if cfg["bind"] == "/output":
                output_dir = Path(host)
        assert output_dir is not None
        out_name = Path(command[1]).name
        (output_dir / out_name).write_text(json.dumps(payload), encoding="utf-8")
        return b""

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
    assert kwargs["command"][2] == "0.1"
    assert kwargs["command"][3] == "1.0,2.0"
    assert kwargs["command"][4] == "0"
    assert kwargs["remove"] is True


def test_run_model_surfaces_container_error() -> None:
    client = MagicMock()
    client.images.get.return_value = MagicMock()
    client.containers.run.side_effect = ContainerError(
        container=MagicMock(),
        exit_status=1,
        command="leman",
        image="img",
        stderr=b"boom",
    )

    with pytest.raises(Leman2000DockerError, match="boom"):
        run_model(
            example_wav_path(),
            local_decay_sec=[0.1],
            global_decay_sec=[1.0],
            client=client,
        )
