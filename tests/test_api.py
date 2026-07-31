"""Tests for the public API with a mocked Docker runner."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

from pyleman2000 import Leman2000Result, leman2000
from pyleman2000.api import example_wav_path

FIXTURE = Path(__file__).parent / "fixtures" / "sample_result.json"


@pytest.fixture
def raw_result() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_example_wav_exists() -> None:
    path = example_wav_path()
    assert path.is_file()
    assert path.suffix == ".wav"


def test_leman2000_with_mocked_runner(raw_result: dict, tmp_path: Path) -> None:
    wav = tmp_path / "tone.wav"
    wav.write_bytes(example_wav_path().read_bytes())

    with patch("pyleman2000.api.run_model", return_value=raw_result) as run_model:
        result = leman2000(
            input_file=wav,
            local_decay_sec=[0.1, 0.2],
            global_decay_sec=[1.0, 2.0],
            windows=[(0.0, 0.1), (0.1, 0.2), (0.2, 0.3)],
        )

    assert isinstance(result, Leman2000Result)
    assert result.audio_length_sec == raw_result["audio_length_sec"]
    assert result.auditory_nerve is None
    assert result.periodicity_pitch is None
    assert result.windowed_local_global_comparison is not None
    assert set(result.local_global_comparison.columns) == {
        "local_decay_sec",
        "global_decay_sec",
        "time_sec",
        "running_correlation",
    }

    run_model.assert_called_once()
    kwargs = run_model.call_args.kwargs
    assert kwargs["detail"] == 0


def test_singleton_parameters(raw_result: dict, tmp_path: Path) -> None:
    wav = tmp_path / "tone.wav"
    wav.write_bytes(b"RIFF")

    singleton = {
        **raw_result,
        "local_global_comparison": raw_result["local_global_comparison"][:1],
    }
    with patch("pyleman2000.api.run_model", return_value=singleton):
        result = leman2000(
            input_file=wav,
            local_decay_sec=0.1,
            global_decay_sec=1.0,
        )

    assert isinstance(result.local_global_comparison, pd.DataFrame)
    assert result.windowed_local_global_comparison is None


def test_keep_flags_request_detail_and_retain_fields(
    raw_result: dict, tmp_path: Path
) -> None:
    wav = tmp_path / "tone.wav"
    wav.write_bytes(b"RIFF")

    with patch("pyleman2000.api.run_model", return_value=raw_result) as run_model:
        result = leman2000(
            input_file=wav,
            local_decay_sec=0.1,
            global_decay_sec=1.0,
            keep_auditory_nerve=True,
            keep_periodicity_pitch=False,
        )

    assert run_model.call_args.kwargs["detail"] == 5
    assert result.auditory_nerve is not None
    assert result.periodicity_pitch is None


def test_rejects_non_wav(tmp_path: Path) -> None:
    path = tmp_path / "tone.txt"
    path.write_text("nope")
    with pytest.raises(ValueError, match="\\.wav"):
        leman2000(path, local_decay_sec=0.1, global_decay_sec=1.0)


def test_rejects_missing_file(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        leman2000(tmp_path / "missing.wav", 0.1, 1.0)
