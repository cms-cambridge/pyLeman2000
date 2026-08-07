"""Public API for running Leman's (2000) tonal contextuality model."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from queue import Queue
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
from pyleman2000.progress import BatchProgress
from pyleman2000.types import Leman2000BatchResult, Leman2000Result, combine_results
from pyleman2000.worker_sizing import choose_worker_count

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


def leman2000_batch(
    input_files: Sequence[str | Path],
    local_decay_sec: float | Sequence[float],
    global_decay_sec: float | Sequence[float],
    windows: Sequence[Sequence[float]] | None = None,
    windowing_function: Callable[[np.ndarray], float] = np.mean,
    keep_auditory_nerve: bool = False,
    keep_periodicity_pitch: bool = False,
    *,
    workers: int | None = None,
    backend: BackendName = "matlab",
    docker_image: str | None = None,
    docker_client: docker.DockerClient | None = None,
    docker_timeout_sec: float | None = DEFAULT_TIMEOUT_SEC,
    show_progress: bool = True,
) -> Leman2000BatchResult:
    """Analyse many WAV files with a warm worker pool.

    Opens a :class:`Leman2000Pool`, maps ``input_files`` across workers, and
    returns stacked DataFrames. Worker count defaults to a RAM-aware choice
    (see :func:`pyleman2000.worker_sizing.choose_worker_count`), overridable
    via ``workers`` or the ``PYLEMAN2000_WORKERS`` environment variable.

    When ``show_progress`` is True, a batch progress line is shown and
    per-container run progress is suppressed to avoid overlapping status
    output.

    Parameters
    ----------
    input_files :
        Paths to WAV files to analyse.
    local_decay_sec :
        Local decay parameter(s) in seconds (shared across files).
    global_decay_sec :
        Global decay parameter(s) in seconds (shared across files).
    windows :
        Optional time windows, as for :func:`leman2000`.
    windowing_function :
        Reduction used within each window.
    keep_auditory_nerve :
        If True, include auditory nerve outputs on each per-file result.
    keep_periodicity_pitch :
        If True, include periodicity pitch outputs on each per-file result.
    workers :
        Explicit worker count. When omitted, chosen from available RAM,
        backend, file count, and emulation heuristics.
    backend :
        ``"matlab"`` (default) or ``"octave"``.
    docker_image :
        Docker image providing the model.
    docker_client :
        Optional Docker SDK client.
    docker_timeout_sec :
        Maximum container runtime in seconds per analysis.
    show_progress :
        If True, report batch progress on standard error.

    Returns
    -------
    Leman2000BatchResult
        Combined ``files`` / correlation tables plus per-file ``results``.
    """
    files = list(input_files)
    if not files:
        empty = combine_results([], [], workers=1)
        return empty

    n_workers = choose_worker_count(
        len(files),
        workers=workers,
        backend=backend,
    )
    # Batch progress replaces noisy per-session run progress.
    session_progress = False
    progress = BatchProgress() if show_progress else None

    with Leman2000Pool(
        workers=n_workers,
        backend=backend,
        docker_image=docker_image,
        docker_client=docker_client,
        docker_timeout_sec=docker_timeout_sec,
        show_progress=session_progress,
    ) as pool:
        results = pool.map(
            files,
            local_decay_sec=local_decay_sec,
            global_decay_sec=global_decay_sec,
            windows=windows,
            windowing_function=windowing_function,
            keep_auditory_nerve=keep_auditory_nerve,
            keep_periodicity_pitch=keep_periodicity_pitch,
            progress=progress,
        )
    return combine_results(files, results, workers=n_workers)


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


class Leman2000Pool:
    """Pool of warm sessions for parallel multi-file analysis.

    Each worker is one :class:`Leman2000Session` (one Docker container /
    MATLAB Runtime process) and handles a single request at a time. Files are
    distributed across workers with a thread pool; the heavy work stays inside
    Docker, so threads are appropriate.

    Do not call :meth:`Leman2000Session.run` concurrently on one session.
    Use this pool when analysing many files.

    Examples
    --------
    >>> with Leman2000Pool(workers=4, show_progress=False) as pool:
    ...     results = pool.map(
    ...         [example_wav_path(), example_wav_path()],
    ...         local_decay_sec=0.1,
    ...         global_decay_sec=1.0,
    ...     )
    """

    def __init__(
        self,
        *,
        workers: int = 2,
        backend: BackendName = "matlab",
        docker_image: str | None = None,
        docker_client: docker.DockerClient | None = None,
        docker_timeout_sec: float | None = DEFAULT_TIMEOUT_SEC,
        show_progress: bool = True,
    ) -> None:
        if not isinstance(workers, int) or isinstance(workers, bool) or workers < 1:
            raise ValueError("workers must be an integer >= 1")
        self._workers = workers
        self._session_kwargs = {
            "backend": backend,
            "docker_image": docker_image,
            "docker_client": docker_client,
            "docker_timeout_sec": docker_timeout_sec,
            "show_progress": show_progress,
        }
        self._sessions: list[Leman2000Session] = []
        self._available: Queue[Leman2000Session] | None = None

    def open(self) -> Leman2000Pool:
        """Start ``workers`` warm sessions."""
        if self._available is not None:
            return self

        sessions: list[Leman2000Session] = []
        try:
            for _ in range(self._workers):
                session = Leman2000Session(**self._session_kwargs)
                session.__enter__()
                sessions.append(session)
        except BaseException:
            for session in sessions:
                session.__exit__(None, None, None)
            raise

        available: Queue[Leman2000Session] = Queue()
        for session in sessions:
            available.put(session)
        self._sessions = sessions
        self._available = available
        return self

    def close(self) -> None:
        """Close every pooled session."""
        sessions = self._sessions
        self._sessions = []
        self._available = None
        errors: list[BaseException] = []
        for session in sessions:
            try:
                session.__exit__(None, None, None)
            except BaseException as exc:  # noqa: BLE001 - collect all close errors
                errors.append(exc)
        if errors:
            raise errors[0]

    def __enter__(self) -> Leman2000Pool:
        return self.open()

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def map(
        self,
        input_files: Sequence[str | Path],
        local_decay_sec: float | Sequence[float],
        global_decay_sec: float | Sequence[float],
        windows: Sequence[Sequence[float]] | None = None,
        windowing_function: Callable[[np.ndarray], float] = np.mean,
        keep_auditory_nerve: bool = False,
        keep_periodicity_pitch: bool = False,
        *,
        progress: BatchProgress | None = None,
    ) -> list[Leman2000Result]:
        """Analyse many WAV files in parallel.

        Parameters match :meth:`Leman2000Session.run`. Results are returned in
        the same order as ``input_files``. Each pooled session still runs at
        most one analysis at a time.

        Parameters
        ----------
        input_files :
            Paths to WAV files to analyse.
        local_decay_sec :
            Local decay parameter(s) in seconds (shared across files).
        global_decay_sec :
            Global decay parameter(s) in seconds (shared across files).
        windows :
            Optional time windows, as for :func:`leman2000`.
        windowing_function :
            Reduction used within each window.
        keep_auditory_nerve :
            If True, include auditory nerve outputs.
        keep_periodicity_pitch :
            If True, include periodicity pitch outputs.
        progress :
            Optional batch progress display updated as files complete.

        Returns
        -------
        list[Leman2000Result]
            One result per input path, in input order.
        """
        if self._available is None:
            raise RuntimeError(
                "Leman2000Pool is not open. Use it as a context manager "
                "or call open() before map()."
            )

        files = list(input_files)
        if not files:
            return []

        available = self._available
        results: list[Leman2000Result | None] = [None] * len(files)

        def _analyse(index: int, path: str | Path) -> tuple[int, Leman2000Result]:
            session = available.get()
            try:
                result = session.run(
                    input_file=path,
                    local_decay_sec=local_decay_sec,
                    global_decay_sec=global_decay_sec,
                    windows=windows,
                    windowing_function=windowing_function,
                    keep_auditory_nerve=keep_auditory_nerve,
                    keep_periodicity_pitch=keep_periodicity_pitch,
                )
                return index, result
            finally:
                available.put(session)

        if progress is not None:
            progress.start(len(files), self._workers)

        completed = 0
        with ThreadPoolExecutor(max_workers=self._workers) as executor:
            futures = [
                executor.submit(_analyse, index, path)
                for index, path in enumerate(files)
            ]
            try:
                for future in as_completed(futures):
                    index, result = future.result()
                    results[index] = result
                    completed += 1
                    if progress is not None:
                        progress.update(completed)
            except BaseException:
                for future in futures:
                    future.cancel()
                raise
            finally:
                if progress is not None:
                    progress.close()

        ordered: list[Leman2000Result] = []
        for result in results:
            assert result is not None
            ordered.append(result)
        return ordered
