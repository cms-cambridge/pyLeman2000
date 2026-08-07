"""Choose how many warm Docker workers a batch should open.

Worker count is driven by total audio duration, because that is what predicts
compute: the expensive stages (``IPEMCalcANI`` / ``IPEMPeriodicityPitch``) run
once per file and scale with audio length, while extra decay combinations are
nearly free. Available RAM and CPU only act as caps.

See ``artifacts/benchmark/batch_scaling.md`` for the measurements behind the
constants here.
"""

from __future__ import annotations

import os
import platform
import wave
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Literal

BackendName = Literal["octave", "matlab"]

WORKERS_ENV = "PYLEMAN2000_WORKERS"
# Measured warm MATLAB worker footprint (PSS): ~625 MB once ready, growing by
# roughly 10 MB per second of audio (900 MB at 30 s, 1.8 GB at 120 s).
MATLAB_WORKER_BASE_RAM_BYTES = 700 * 1024**2
RAM_BYTES_PER_AUDIO_SEC = 10 * 1024**2
# Headroom over the measured peak, since footprint varies with WAV layout.
RAM_SAFETY_FACTOR = 1.5
# Octave is not measured; assume it needs more than the compiled worker.
OCTAVE_RAM_MULTIPLIER = 2.0
# On-disk image size gates (distinct from RSS). Packaging spike measured
# ~3.8 GiB for the MATLAB worker and ~4.4 GiB for Octave; CI fails if the
# published images balloon past these ceilings.
MATLAB_IMAGE_SIZE_MIN_BYTES = 2 * 1024**3
MATLAB_IMAGE_SIZE_MAX_BYTES = 5 * 1024**3
OCTAVE_IMAGE_SIZE_MIN_BYTES = 2 * 1024**3
OCTAVE_IMAGE_SIZE_MAX_BYTES = 6 * 1024**3
# Warm-container working-set floors: loaded Runtime / Octave should be well
# above an empty shell, and at or below the per-worker RSS budgets above.
MATLAB_WARM_RSS_MIN_BYTES = 512 * 1024**2
OCTAVE_WARM_RSS_MIN_BYTES = 64 * 1024**2
# Audio seconds a worker must be given before its ~5 s startup pays for
# itself. Benchmarked crossover: extra workers lose on short audio and win
# from roughly 1.6x this much audio per worker upwards.
AUDIO_SEC_PER_WORKER = 25.0
DEFAULT_HARD_CAP = 8
EMULATED_HARD_CAP = 4


def available_ram_bytes() -> int | None:
    """Return available system RAM in bytes, or ``None`` if unknown."""
    try:
        with open("/proc/meminfo", encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("MemAvailable:"):
                    parts = line.split()
                    # Value is in kB.
                    return int(parts[1]) * 1024
    except (OSError, IndexError, ValueError):
        return None
    return None


def is_likely_emulated_amd64(machine: str | None = None) -> bool:
    """Return True when the host is ARM and images are likely amd64-emulated."""
    host = (machine if machine is not None else platform.machine()).lower()
    return host in {"aarch64", "arm64"}


def wav_duration_sec(path: str | Path) -> float | None:
    """Return a WAV file's duration in seconds, or ``None`` if unreadable.

    Reads only the header, so this is cheap enough to call before starting
    any container.

    Parameters
    ----------
    path :
        Path to a ``.wav`` file.

    Returns
    -------
    float or None
        Duration in seconds, or ``None`` when the header cannot be parsed.
    """
    try:
        with wave.open(str(path), "rb") as handle:
            frames = handle.getnframes()
            rate = handle.getframerate()
    except (OSError, wave.Error, EOFError):
        return None
    if rate <= 0:
        return None
    return frames / float(rate)


def wav_durations_sec(paths: Sequence[str | Path]) -> list[float] | None:
    """Return each WAV's duration, or ``None`` if any file is unreadable.

    Parameters
    ----------
    paths :
        Paths to the WAV files in a batch.

    Returns
    -------
    list of float, or None
        Durations in seconds, or ``None`` when any header fails to parse
        (callers should then fall back to a single worker).
    """
    durations: list[float] = []
    for path in paths:
        duration = wav_duration_sec(path)
        if duration is None:
            return None
        durations.append(duration)
    return durations


def ram_per_worker_bytes(
    backend: BackendName = "matlab",
    max_audio_sec: float | None = None,
) -> int:
    """Estimate the RAM one warm worker needs, including headroom.

    Parameters
    ----------
    backend :
        ``"matlab"`` or ``"octave"``. Octave is unmeasured and assumed to
        need more than the compiled MATLAB worker.
    max_audio_sec :
        Duration of the longest file the worker will analyse. Memory grows
        with audio length; ``None`` assumes a short file.

    Returns
    -------
    int
        Estimated bytes per worker.
    """
    longest = max(0.0, float(max_audio_sec or 0.0))
    estimate = (
        MATLAB_WORKER_BASE_RAM_BYTES + RAM_BYTES_PER_AUDIO_SEC * longest
    ) * RAM_SAFETY_FACTOR
    if backend != "matlab":
        estimate *= OCTAVE_RAM_MULTIPLIER
    return int(estimate)


def choose_worker_count(
    n_files: int,
    *,
    total_audio_sec: float | None = None,
    max_audio_sec: float | None = None,
    workers: int | None = None,
    backend: BackendName = "matlab",
    available_ram: int | None | object = ...,
    cpu_count: int | None | object = ...,
    emulated: bool | None = None,
    environ: Mapping[str, str] | None = None,
    hard_cap: int | None = None,
) -> int:
    """Pick a worker count for a multi-file batch.

    Defaults to one worker and only scales up when there is enough total
    audio to amortise each extra worker's startup. RAM, CPU count, file
    count, and a hard cap are applied as ceilings.

    Parameters
    ----------
    n_files :
        Number of input files in the batch.
    total_audio_sec :
        Total audio duration across the batch. When ``None`` (unknown), a
        single worker is used.
    max_audio_sec :
        Duration of the longest file, used to size the per-worker RAM
        budget. When omitted, files are assumed to be evenly sized.
    workers :
        Explicit override. When set, still capped by ``n_files``.
    backend :
        ``"matlab"`` or ``"octave"``; selects the per-worker RAM budget.
    available_ram :
        Available RAM in bytes. Defaults to :func:`available_ram_bytes`.
        Pass ``None`` to skip the RAM cap.
    cpu_count :
        Usable CPU count. Defaults to :func:`os.cpu_count`. Pass ``None`` to
        skip the CPU cap.
    emulated :
        Whether Docker is likely running under amd64 emulation. Defaults to
        :func:`is_likely_emulated_amd64`.
    environ :
        Environment mapping; defaults to :data:`os.environ`. Honours
        ``PYLEMAN2000_WORKERS`` when ``workers`` is omitted.
    hard_cap :
        Maximum workers. Defaults to 8, or 4 when emulated.

    Returns
    -------
    int
        Worker count in ``1 .. max(1, n_files)``.
    """
    if not isinstance(n_files, int) or isinstance(n_files, bool) or n_files < 0:
        raise ValueError("n_files must be an integer >= 0")
    if n_files == 0:
        return 1

    env = os.environ if environ is None else environ
    if emulated is None:
        emulated = is_likely_emulated_amd64()
    if hard_cap is None:
        hard_cap = EMULATED_HARD_CAP if emulated else DEFAULT_HARD_CAP
    if hard_cap < 1:
        raise ValueError("hard_cap must be >= 1")

    if workers is None:
        raw = env.get(WORKERS_ENV)
        if raw is not None and str(raw).strip() != "":
            try:
                workers = int(raw)
            except ValueError as exc:
                raise ValueError(
                    f"{WORKERS_ENV} must be an integer, got {raw!r}"
                ) from exc

    if workers is not None:
        if not isinstance(workers, int) or isinstance(workers, bool) or workers < 1:
            raise ValueError("workers must be an integer >= 1")
        return min(workers, n_files, hard_cap)

    if total_audio_sec is None or total_audio_sec <= 0:
        desired = 1
    else:
        desired = max(1, round(total_audio_sec / AUDIO_SEC_PER_WORKER))

    caps = [n_files, hard_cap]

    if cpu_count is ...:
        cpu_count = os.cpu_count()
    if isinstance(cpu_count, int) and cpu_count > 0:
        caps.append(cpu_count)

    if available_ram is ...:
        available_ram = available_ram_bytes()
    if isinstance(available_ram, int) and available_ram > 0:
        longest = max_audio_sec
        if longest is None and total_audio_sec is not None:
            # Without per-file durations, assume files are evenly sized.
            longest = total_audio_sec / n_files
        per_worker = ram_per_worker_bytes(backend, longest)
        caps.append(max(1, available_ram // per_worker))

    return max(1, min(desired, *caps))
