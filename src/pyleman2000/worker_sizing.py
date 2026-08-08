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
# Measured worker footprints (PSS). MATLAB: ~625 MB once ready, growing by
# roughly 10 MB per audio-second (900 MB at 30 s, 1.8 GB at 120 s). Octave:
# ~1.9 GB at 5 s and 11.6 GB at 30 s, close to 400 MB per audio-second.
MATLAB_WORKER_BASE_RAM_BYTES = 700 * 1024**2
MATLAB_RAM_BYTES_PER_AUDIO_SEC = 10 * 1024**2
MATLAB_RAM_SAFETY_FACTOR = 1.5
OCTAVE_WORKER_BASE_RAM_BYTES = 256 * 1024**2
OCTAVE_RAM_BYTES_PER_AUDIO_SEC = 400 * 1024**2
OCTAVE_RAM_SAFETY_FACTOR = 1.25
# On-disk image size gates (distinct from RSS). Packaging spike measured
# ~3.8 GiB for the MATLAB worker and ~4.4 GiB for Octave; CI fails if the
# published images balloon past these ceilings.
MATLAB_IMAGE_SIZE_MIN_BYTES = 2 * 1024**3
MATLAB_IMAGE_SIZE_MAX_BYTES = 5 * 1024**3
OCTAVE_IMAGE_SIZE_MIN_BYTES = 2 * 1024**3
OCTAVE_IMAGE_SIZE_MAX_BYTES = 6 * 1024**3
# Warm-container working-set floors. These only guard against a bogus (near
# zero) reading; they are deliberately loose because Docker reports cgroup
# usage minus page cache, which excludes the mapped runtime libraries and so
# runs well below a PSS measurement of the same process. Observed on GitHub
# runners: 385 MB (MATLAB) and 58 MB (Octave). The upper bound from
# ``ram_per_worker_bytes`` is the assertion that matters.
MATLAB_WARM_RSS_MIN_BYTES = 128 * 1024**2
OCTAVE_WARM_RSS_MIN_BYTES = 16 * 1024**2
# MATLAB pays a ~5 s Runtime startup per worker, so short batches stay
# sequential. Octave starts for every file even inside a warm container;
# parallelism paid off strongly for the shortest measured file (0.37 s).
MATLAB_AUDIO_SEC_PER_WORKER = 25.0
OCTAVE_AUDIO_SEC_PER_WORKER = 0.4
DEFAULT_HARD_CAP = 8
EMULATED_HARD_CAP = 4


def _host_available_ram_bytes() -> int | None:
    """Return host ``MemAvailable`` in bytes, or ``None`` if unknown."""
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


def _read_int_file(path: str) -> int | None:
    try:
        with open(path, encoding="utf-8") as handle:
            return int(handle.read().strip())
    except (OSError, ValueError):
        return None


def cgroup_available_ram_bytes() -> int | None:
    """Return RAM the current cgroup may still use, or ``None`` if unlimited.

    Handles cgroup v2 (``memory.max`` / ``memory.current``) and v1
    (``memory.limit_in_bytes`` / ``memory.usage_in_bytes``). A limit at or
    above host RAM is treated as unlimited so it never falsely lowers the
    budget.
    """
    host = _host_available_ram_bytes()
    # cgroup v2
    limit = _read_int_file("/sys/fs/cgroup/memory.max")
    usage = _read_int_file("/sys/fs/cgroup/memory.current")
    if limit is None:
        # cgroup v1
        limit = _read_int_file("/sys/fs/cgroup/memory/memory.limit_in_bytes")
        usage = _read_int_file("/sys/fs/cgroup/memory/memory.usage_in_bytes")
    if limit is None or limit <= 0:
        return None
    if host is not None and limit >= host:
        return None
    return max(0, limit - (usage or 0))


def available_ram_bytes() -> int | None:
    """Return RAM available to this process in bytes, or ``None`` if unknown.

    Takes the smaller of host ``MemAvailable`` and the current cgroup's
    remaining allowance, so container/pod memory limits are respected.
    """
    host = _host_available_ram_bytes()
    cgroup = cgroup_available_ram_bytes()
    candidates = [v for v in (host, cgroup) if v is not None]
    if not candidates:
        return None
    return min(candidates)


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
        ``"matlab"`` or ``"octave"``; selects the measured memory model.
    max_audio_sec :
        Duration of the longest file the worker will analyse. Memory grows
        with audio length; ``None`` assumes a short file.

    Returns
    -------
    int
        Estimated bytes per worker.
    """
    longest = max(0.0, float(max_audio_sec or 0.0))
    if backend == "matlab":
        estimate = (
            MATLAB_WORKER_BASE_RAM_BYTES
            + MATLAB_RAM_BYTES_PER_AUDIO_SEC * longest
        ) * MATLAB_RAM_SAFETY_FACTOR
    else:
        estimate = (
            OCTAVE_WORKER_BASE_RAM_BYTES
            + OCTAVE_RAM_BYTES_PER_AUDIO_SEC * longest
        ) * OCTAVE_RAM_SAFETY_FACTOR
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
        Explicit override (from the argument or ``PYLEMAN2000_WORKERS``).
        Honoured as given, capped only by ``n_files``; the automatic
        RAM/CPU/hard caps are skipped, so an explicit count can oversubscribe
        memory. Leave unset for the safe automatic choice.
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
        # An explicit request (argument or PYLEMAN2000_WORKERS) is honoured as
        # given, capped only by the number of files. Automatic RAM/CPU/hard
        # caps apply only when the count is chosen for the caller.
        return min(workers, n_files)

    if total_audio_sec is None or total_audio_sec <= 0:
        desired = 1
    else:
        audio_per_worker = (
            MATLAB_AUDIO_SEC_PER_WORKER
            if backend == "matlab"
            else OCTAVE_AUDIO_SEC_PER_WORKER
        )
        desired = max(1, round(total_audio_sec / audio_per_worker))

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
