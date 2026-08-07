"""Tests for the public API with a mocked Docker runner."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

from pyleman2000 import (
    DEFAULT_MATLAB_IMAGE,
    Leman2000Result,
    Leman2000Session,
    example_wav_path,
    leman2000,
)

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
            backend="octave",
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
    assert kwargs["local_decay_sec"] == [0.1, 0.2]
    assert kwargs["global_decay_sec"] == [1.0, 2.0]


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
            backend="octave",
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
            backend="octave",
        )

    assert run_model.call_args.kwargs["detail"] == 5
    assert result.auditory_nerve is not None
    assert result.periodicity_pitch is None


def test_forwards_docker_options_and_windowing_function(
    raw_result: dict, tmp_path: Path
) -> None:
    wav = tmp_path / "tone.WAV"
    wav.write_bytes(b"RIFF")
    client = MagicMock()

    with patch("pyleman2000.api.run_model", return_value=raw_result) as run_model:
        result = leman2000(
            input_file=wav,
            local_decay_sec=(0.1,),
            global_decay_sec=(1.0,),
            windows=[(0.0, 0.3)],
            windowing_function=np.median,
            backend="octave",
            docker_image="example/image@sha256:digest",
            docker_client=client,
            docker_timeout_sec=12.0,
        )

    assert run_model.call_args.kwargs["image"] == "example/image@sha256:digest"
    assert run_model.call_args.kwargs["client"] is client
    assert run_model.call_args.kwargs["timeout_sec"] == 12.0
    expected = np.median(
        result.local_global_comparison.loc[
            (result.local_global_comparison["local_decay_sec"] == 0.1)
            & (result.local_global_comparison["global_decay_sec"] == 1.0),
            "running_correlation",
        ]
    )
    assert (
        result.windowed_local_global_comparison.iloc[0][
            "local_global_correlation"
        ]
        == pytest.approx(expected)
    )


@pytest.mark.parametrize(
    "value, error, match",
    [
        ([], ValueError, "must not be empty"),
        ("0.1", TypeError, "float or sequence"),
        (True, TypeError, "boolean"),
        ([False], TypeError, "boolean"),
        (0.0, ValueError, "positive"),
        (-0.1, ValueError, "positive"),
        (np.nan, ValueError, "finite"),
        (np.inf, ValueError, "finite"),
    ],
)
def test_rejects_invalid_decay_values(
    raw_result: dict,
    tmp_path: Path,
    value,
    error: type[Exception],
    match: str,
) -> None:
    wav = tmp_path / "tone.wav"
    wav.write_bytes(b"RIFF")

    with pytest.raises(error, match=match):
        leman2000(wav, local_decay_sec=value, global_decay_sec=1.0)


def test_requested_detail_must_be_present(
    raw_result: dict, tmp_path: Path
) -> None:
    wav = tmp_path / "tone.wav"
    wav.write_bytes(b"RIFF")
    raw_result.pop("auditory_nerve")

    with (
        patch("pyleman2000.api.run_model_matlab", return_value=raw_result),
        pytest.raises(ValueError, match="auditory_nerve"),
    ):
        leman2000(
            wav,
            local_decay_sec=0.1,
            global_decay_sec=1.0,
            keep_auditory_nerve=True,
        )


def test_invalid_windows_are_rejected_before_docker(tmp_path: Path) -> None:
    wav = tmp_path / "tone.wav"
    wav.write_bytes(b"RIFF")

    with (
        patch("pyleman2000.api.run_model") as run_model,
        patch("pyleman2000.api.run_model_matlab") as run_matlab,
        pytest.raises(ValueError, match="greater than or equal"),
    ):
        leman2000(
            wav,
            local_decay_sec=0.1,
            global_decay_sec=1.0,
            windows=[(1.0, 0.0)],
        )

    run_model.assert_not_called()
    run_matlab.assert_not_called()


def test_empty_windows_are_rejected_before_docker(tmp_path: Path) -> None:
    wav = tmp_path / "tone.wav"
    wav.write_bytes(b"RIFF")

    with (
        patch("pyleman2000.api.run_model") as run_model,
        patch("pyleman2000.api.run_model_matlab") as run_matlab,
        pytest.raises(ValueError, match="at least one"),
    ):
        leman2000(
            wav,
            local_decay_sec=0.1,
            global_decay_sec=1.0,
            windows=[],
        )

    run_model.assert_not_called()
    run_matlab.assert_not_called()


def test_rejects_non_callable_windowing_function(tmp_path: Path) -> None:
    wav = tmp_path / "tone.wav"
    wav.write_bytes(b"RIFF")

    with (
        patch("pyleman2000.api.run_model") as run_model,
        patch("pyleman2000.api.run_model_matlab") as run_matlab,
        pytest.raises(TypeError, match="windowing_function"),
    ):
        leman2000(
            wav,
            local_decay_sec=0.1,
            global_decay_sec=1.0,
            windows=[(0.0, 0.1)],
            windowing_function="mean",  # type: ignore[arg-type]
        )

    run_model.assert_not_called()
    run_matlab.assert_not_called()


def test_rejects_non_wav(tmp_path: Path) -> None:
    path = tmp_path / "tone.txt"
    path.write_text("nope")
    with pytest.raises(ValueError, match="\\.wav"):
        leman2000(path, local_decay_sec=0.1, global_decay_sec=1.0)


def test_rejects_missing_file(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        leman2000(tmp_path / "missing.wav", 0.1, 1.0)


def test_session_reuses_warm_runner(raw_result: dict, tmp_path: Path) -> None:
    wav = tmp_path / "tone.wav"
    wav.write_bytes(example_wav_path().read_bytes())
    runner = MagicMock()
    runner.run.return_value = raw_result

    with patch("pyleman2000.api.WarmModelRunner", return_value=runner):
        with Leman2000Session(backend="octave", show_progress=False) as session:
            first = session.run(
                input_file=wav,
                local_decay_sec=0.1,
                global_decay_sec=1.0,
            )
            second = session.run(
                input_file=wav,
                local_decay_sec=[0.1, 0.5],
                global_decay_sec=[1.0, 2.0],
                windows=[(0.0, 0.1)],
            )

    assert isinstance(first, Leman2000Result)
    assert isinstance(second, Leman2000Result)
    runner.open.assert_called_once_with()
    assert runner.run.call_count == 2
    assert runner.run.call_args_list[0].kwargs["detail"] == 0
    assert runner.run.call_args_list[1].kwargs["local_decay_sec"] == [0.1, 0.5]
    assert second.windowed_local_global_comparison is not None
    runner.close.assert_called_once_with()


def test_leman2000_default_backend_is_matlab(
    raw_result: dict, tmp_path: Path
) -> None:
    wav = tmp_path / "tone.wav"
    wav.write_bytes(example_wav_path().read_bytes())

    with patch(
        "pyleman2000.api.run_model_matlab", return_value=raw_result
    ) as run_matlab:
        with patch("pyleman2000.api.run_model") as run_octave:
            result = leman2000(
                input_file=wav,
                local_decay_sec=0.1,
                global_decay_sec=1.0,
                show_progress=False,
            )

    assert isinstance(result, Leman2000Result)
    run_matlab.assert_called_once()
    run_octave.assert_not_called()
    assert run_matlab.call_args.kwargs["image"] == DEFAULT_MATLAB_IMAGE


def test_leman2000_octave_backend_dispatches_to_octave_runner(
    raw_result: dict, tmp_path: Path
) -> None:
    wav = tmp_path / "tone.wav"
    wav.write_bytes(example_wav_path().read_bytes())

    with patch("pyleman2000.api.run_model", return_value=raw_result) as run_octave:
        with patch("pyleman2000.api.run_model_matlab") as run_matlab:
            leman2000(
                input_file=wav,
                local_decay_sec=0.1,
                global_decay_sec=1.0,
                backend="octave",
                show_progress=False,
            )

    run_octave.assert_called_once()
    run_matlab.assert_not_called()


def test_session_default_backend_uses_matlab_worker(
    raw_result: dict, tmp_path: Path
) -> None:
    wav = tmp_path / "tone.wav"
    wav.write_bytes(example_wav_path().read_bytes())
    runner = MagicMock()
    runner.run.return_value = raw_result

    with patch("pyleman2000.api.MatlabWorkerRunner", return_value=runner) as ctor:
        with patch("pyleman2000.api.WarmModelRunner") as octave_ctor:
            with Leman2000Session(show_progress=False) as session:
                session.run(wav, local_decay_sec=0.1, global_decay_sec=1.0)

    octave_ctor.assert_not_called()
    ctor.assert_called_once()
    assert ctor.call_args.kwargs["image"] == DEFAULT_MATLAB_IMAGE
    runner.open.assert_called_once_with()
    runner.close.assert_called_once_with()


def test_rejects_unknown_backend(tmp_path: Path) -> None:
    wav = tmp_path / "tone.wav"
    wav.write_bytes(b"RIFF")
    with pytest.raises(ValueError, match="backend must be"):
        leman2000(wav, 0.1, 1.0, backend="julia")  # type: ignore[arg-type]
