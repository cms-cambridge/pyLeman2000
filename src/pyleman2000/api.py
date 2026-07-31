"""Public API for running Leman's (2000) tonal contextuality model."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

import docker
import numpy as np

from pyleman2000.docker_runner import (
    DEFAULT_IMAGE,
    DEFAULT_TIMEOUT_SEC,
    run_model,
)
from pyleman2000.formatters import (
    format_local_global_comparison,
    validate_windows,
    window_local_global_comparison,
)
from pyleman2000.types import Leman2000Result


def example_wav_path() -> Path:
    """Return the path to the packaged example hi-hat WAV file."""
    return Path(__file__).resolve().parent / "data" / "hihat.wav"


def _as_float_sequence(values: float | Sequence[float], name: str) -> list[float]:
    if isinstance(values, (str, bytes)):
        raise TypeError(f"{name} must be a float or sequence of floats")
    raw_values = (
        list(values)
        if isinstance(values, Sequence | np.ndarray)
        else [values]
    )
    if not raw_values:
        raise ValueError(f"{name} must not be empty")

    result: list[float] = []
    for value in raw_values:
        if isinstance(value, (bool, np.bool_)):
            raise TypeError(f"{name} must not contain boolean values")
        try:
            converted = float(value)
        except (TypeError, ValueError) as exc:
            raise TypeError(f"{name} must contain only real numbers") from exc
        if not np.isfinite(converted):
            raise ValueError(f"{name} values must be finite")
        if converted <= 0:
            raise ValueError(f"{name} values must be positive")
        result.append(converted)
    return result


def leman2000(
    input_file: str | Path,
    local_decay_sec: float | Sequence[float],
    global_decay_sec: float | Sequence[float],
    windows: Sequence[Sequence[float]] | None = None,
    windowing_function: Callable[[np.ndarray], float] = np.mean,
    keep_auditory_nerve: bool = False,
    keep_periodicity_pitch: bool = False,
    *,
    docker_image: str = DEFAULT_IMAGE,
    docker_client: docker.DockerClient | None = None,
    docker_timeout_sec: float | None = DEFAULT_TIMEOUT_SEC,
) -> Leman2000Result:
    """Run Leman's (2000) tonal contextuality model on a WAV file.

    This model was published in a 2000 Music Perception paper, and was shown
    to provide a psychoacoustic account of the Krumhansl-Kessler probe-tone
    data. Computation is performed by a Dockerised MATLAB/IPEM binary.

    Parameters
    ----------
    input_file :
        Path to the input file (WAV format, ``.wav`` extension).
    local_decay_sec :
        Local decay parameter(s) in seconds. If a sequence is given, results
        are produced for all combinations with ``global_decay_sec``.
    global_decay_sec :
        Global decay parameter(s) in seconds.
    windows :
        Optional time windows for averaging. Each window is ``(start, end)``
        in seconds. Both endpoints are included. ``window_id`` values in the
        returned table are 1-based, and rows are ordered window-major.
    windowing_function :
        Reduction used within each window. Defaults to :func:`numpy.mean`.
    keep_auditory_nerve :
        If True, include auditory nerve simulation outputs. These can be
        large nested dictionaries from the MATLAB binary.
    keep_periodicity_pitch :
        If True, include periodicity pitch outputs. These can be large
        nested dictionaries from the MATLAB binary.
    docker_image :
        Docker image providing the compiled model.
    docker_client :
        Optional Docker SDK client. Useful for testing.
    docker_timeout_sec :
        Maximum container runtime in seconds. Set to None for no timeout.

    Returns
    -------
    Leman2000Result
        Structured model output, including a long-form local/global
        comparison DataFrame and optional windowed summaries.
    """
    path = Path(input_file).expanduser().resolve()
    if path.suffix.lower() != ".wav":
        raise ValueError(f"input_file must be a .wav file, got {path.name!r}")
    if not path.is_file():
        raise FileNotFoundError(f"Input file not found: {path}")

    local_vals = _as_float_sequence(local_decay_sec, "local_decay_sec")
    global_vals = _as_float_sequence(global_decay_sec, "global_decay_sec")
    if windows is not None:
        validate_windows(windows)
    if not callable(windowing_function):
        raise TypeError("windowing_function must be callable")

    detail = 5 if (keep_auditory_nerve or keep_periodicity_pitch) else 0
    raw = run_model(
        input_file=path,
        local_decay_sec=local_vals,
        global_decay_sec=global_vals,
        detail=detail,
        image=docker_image,
        client=docker_client,
        timeout_sec=docker_timeout_sec,
    )

    if not isinstance(raw, Mapping):
        raise ValueError("Model output must be a JSON object")
    required = {
        "audio_length_sec",
        "num_channels",
        "sample_rate",
        "local_global_comparison",
    }
    missing = sorted(required.difference(raw))
    if missing:
        raise ValueError(
            "Model output is missing required field(s): " + ", ".join(missing)
        )
    for keep, field in (
        (keep_auditory_nerve, "auditory_nerve"),
        (keep_periodicity_pitch, "periodicity_pitch"),
    ):
        if keep and field not in raw:
            raise ValueError(
                f"{field!r} was requested via keep_* flags, but Docker image "
                f"{docker_image!r} did not return that field. Verify that the "
                "image is compatible with this package version."
            )

    local_global = format_local_global_comparison(
        raw["local_global_comparison"],
        float(raw["audio_length_sec"]),
    )

    windowed = None
    if windows is not None:
        windowed = window_local_global_comparison(
            local_global,
            windows,
            windowing_function=windowing_function,
        )

    auditory_nerve = raw.get("auditory_nerve") if keep_auditory_nerve else None
    periodicity_pitch = (
        raw.get("periodicity_pitch") if keep_periodicity_pitch else None
    )

    return Leman2000Result(
        audio_length_sec=float(raw["audio_length_sec"]),
        num_channels=int(raw["num_channels"]),
        sample_rate=float(raw["sample_rate"]),
        local_global_comparison=local_global,
        windowed_local_global_comparison=windowed,
        auditory_nerve=auditory_nerve,
        periodicity_pitch=periodicity_pitch,
    )
