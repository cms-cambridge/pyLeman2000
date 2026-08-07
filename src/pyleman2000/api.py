"""Public API for running Leman's (2000) tonal contextuality model."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Literal

import docker
import numpy as np

from pyleman2000.docker_runner import (
    DEFAULT_IMAGE,
    DEFAULT_TIMEOUT_SEC,
    WarmModelRunner,
    run_model,
)
from pyleman2000.formatters import (
    format_local_global_comparison,
    validate_windows,
    window_local_global_comparison,
)
from pyleman2000.matlab_worker import (
    DEFAULT_MATLAB_IMAGE,
    MatlabWorkerRunner,
    run_model_matlab,
)
from pyleman2000.types import Leman2000Result

BackendName = Literal["octave", "matlab"]


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


def _resolve_backend(
    backend: BackendName,
    docker_image: str | None,
) -> tuple[BackendName, str]:
    if backend not in ("octave", "matlab"):
        raise ValueError(
            f"backend must be 'octave' or 'matlab', got {backend!r}"
        )
    if docker_image is not None:
        return backend, docker_image
    if backend == "matlab":
        return backend, DEFAULT_MATLAB_IMAGE
    return backend, DEFAULT_IMAGE


def _prepare_analysis_args(
    input_file: str | Path,
    local_decay_sec: float | Sequence[float],
    global_decay_sec: float | Sequence[float],
    windows: Sequence[Sequence[float]] | None,
    windowing_function: Callable[[np.ndarray], float],
    keep_auditory_nerve: bool,
    keep_periodicity_pitch: bool,
) -> tuple[Path, list[float], list[float], int]:
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
    return path, local_vals, global_vals, detail


def _result_from_raw(
    raw: object,
    *,
    windows: Sequence[Sequence[float]] | None,
    windowing_function: Callable[[np.ndarray], float],
    keep_auditory_nerve: bool,
    keep_periodicity_pitch: bool,
    docker_image: str,
) -> Leman2000Result:
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


def leman2000(
    input_file: str | Path,
    local_decay_sec: float | Sequence[float],
    global_decay_sec: float | Sequence[float],
    windows: Sequence[Sequence[float]] | None = None,
    windowing_function: Callable[[np.ndarray], float] = np.mean,
    keep_auditory_nerve: bool = False,
    keep_periodicity_pitch: bool = False,
    *,
    backend: BackendName = "matlab",
    docker_image: str | None = None,
    docker_client: docker.DockerClient | None = None,
    docker_timeout_sec: float | None = DEFAULT_TIMEOUT_SEC,
    show_progress: bool = True,
) -> Leman2000Result:
    """Run Leman's (2000) tonal contextuality model on a WAV file.

    This model was published in a 2000 Music Perception paper, and was shown
    to provide a psychoacoustic account of the Krumhansl-Kessler probe-tone
    data. Computation runs in Docker. The default ``backend="matlab"`` uses a
    compiled MATLAB Runtime worker published to GHCR (see ``docker/matlab/``).
    ``backend="octave"`` uses a license-free GNU Octave image
    (``linux/amd64``; see ``docker/octave/``).

    For repeated analyses in one process, prefer :class:`Leman2000Session`,
    which reuses a warm container / worker. With the MATLAB backend the
    session keeps the compiled worker process alive, which is where most of
    the speed gain comes from.

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
        in seconds. Both endpoints are included (intentional divergence from
        ``leman2000R``, which uses half-open ``[start, end)``). ``window_id``
        values in the returned table are 1-based, and rows are ordered
        window-major.
    windowing_function :
        Reduction used within each window. Defaults to :func:`numpy.mean`.
    keep_auditory_nerve :
        If True, include auditory nerve simulation outputs. These can be
        large nested dictionaries from the model.
    keep_periodicity_pitch :
        If True, include periodicity pitch outputs. These can be large
        nested dictionaries from the model.
    backend :
        ``"matlab"`` (default) or ``"octave"``.
    docker_image :
        Docker image providing the model. Defaults to digest-pinned GHCR
        images (``DEFAULT_MATLAB_IMAGE`` / ``DEFAULT_IMAGE``). For local
        builds, pass ``pyleman2000-matlab:dev`` or ``pyleman2000-octave:dev``.
    docker_client :
        Optional Docker SDK client. Useful for testing.
    docker_timeout_sec :
        Maximum container runtime in seconds. Set to None for no timeout.
    show_progress :
        If True, report progress on standard error while a pullable image is
        downloaded and while the container runs.

    Returns
    -------
    Leman2000Result
        Structured model output, including a long-form local/global
        comparison DataFrame and optional windowed summaries.
    """
    backend, image = _resolve_backend(backend, docker_image)
    path, local_vals, global_vals, detail = _prepare_analysis_args(
        input_file,
        local_decay_sec,
        global_decay_sec,
        windows,
        windowing_function,
        keep_auditory_nerve,
        keep_periodicity_pitch,
    )
    runner = run_model_matlab if backend == "matlab" else run_model
    raw = runner(
        input_file=path,
        local_decay_sec=local_vals,
        global_decay_sec=global_vals,
        detail=detail,
        image=image,
        client=docker_client,
        timeout_sec=docker_timeout_sec,
        show_progress=show_progress,
    )
    return _result_from_raw(
        raw,
        windows=windows,
        windowing_function=windowing_function,
        keep_auditory_nerve=keep_auditory_nerve,
        keep_periodicity_pitch=keep_periodicity_pitch,
        docker_image=image,
    )


class Leman2000Session:
    """Reuse one Docker container across multiple model runs.

    With ``backend="matlab"`` (default), the compiled MATLAB Runtime worker
    stays loaded, which is typically much faster for repeated analyses. With
    ``backend="octave"``, Octave still starts on every analysis, but keeping
    the container alive warms filesystem caches.

    Examples
    --------
    >>> with Leman2000Session() as session:
    ...     result = session.run(
    ...         input_file=example_wav_path(),
    ...         local_decay_sec=0.1,
    ...         global_decay_sec=1.0,
    ...     )
    """

    def __init__(
        self,
        *,
        backend: BackendName = "matlab",
        docker_image: str | None = None,
        docker_client: docker.DockerClient | None = None,
        docker_timeout_sec: float | None = DEFAULT_TIMEOUT_SEC,
        show_progress: bool = True,
    ) -> None:
        backend, image = _resolve_backend(backend, docker_image)
        self._backend = backend
        self._docker_image = image
        runner_cls = (
            MatlabWorkerRunner if backend == "matlab" else WarmModelRunner
        )
        self._runner = runner_cls(
            image=image,
            client=docker_client,
            timeout_sec=docker_timeout_sec,
            show_progress=show_progress,
        )

    def __enter__(self) -> Leman2000Session:
        self._runner.open()
        return self

    def __exit__(self, *exc_info: object) -> None:
        self._runner.close()

    def run(
        self,
        input_file: str | Path,
        local_decay_sec: float | Sequence[float],
        global_decay_sec: float | Sequence[float],
        windows: Sequence[Sequence[float]] | None = None,
        windowing_function: Callable[[np.ndarray], float] = np.mean,
        keep_auditory_nerve: bool = False,
        keep_periodicity_pitch: bool = False,
    ) -> Leman2000Result:
        """Run the model on one WAV file using the warm container.

        Parameters match :func:`leman2000` analysis arguments (excluding
        Docker connection options, which are set on the session).
        """
        path, local_vals, global_vals, detail = _prepare_analysis_args(
            input_file,
            local_decay_sec,
            global_decay_sec,
            windows,
            windowing_function,
            keep_auditory_nerve,
            keep_periodicity_pitch,
        )
        raw = self._runner.run(
            input_file=path,
            local_decay_sec=local_vals,
            global_decay_sec=global_vals,
            detail=detail,
        )
        return _result_from_raw(
            raw,
            windows=windows,
            windowing_function=windowing_function,
            keep_auditory_nerve=keep_auditory_nerve,
            keep_periodicity_pitch=keep_periodicity_pitch,
            docker_image=self._docker_image,
        )
