"""Choose how many warm Docker workers a batch should open."""

from __future__ import annotations

import os
import platform
from collections.abc import Mapping
from typing import Literal

BackendName = Literal["octave", "matlab"]

WORKERS_ENV = "PYLEMAN2000_WORKERS"
# Conservative RSS budgets for a warm container plus headroom for the host.
MATLAB_RAM_PER_WORKER_BYTES = 5 * 1024**3
# Octave's on-disk image is ~4.4 GiB; a loaded IPEM run can approach that, so
# keep the per-worker RSS budget in the same ballpark.
OCTAVE_RAM_PER_WORKER_BYTES = 4 * 1024**3
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
DEFAULT_HARD_CAP = 8
EMULATED_HARD_CAP = 4
FALLBACK_WORKERS = 4


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


def choose_worker_count(
    n_files: int,
    *,
    workers: int | None = None,
    backend: BackendName = "matlab",
    available_ram: int | None | object = ...,
    emulated: bool | None = None,
    environ: Mapping[str, str] | None = None,
    hard_cap: int | None = None,
) -> int:
    """Pick a worker count for a multi-file batch.

    Parameters
    ----------
    n_files :
        Number of input files in the batch.
    workers :
        Explicit override. When set, still capped by ``n_files``.
    backend :
        ``"matlab"`` or ``"octave"``; selects the per-worker RAM budget.
    available_ram :
        Available RAM in bytes. Defaults to :func:`available_ram_bytes`.
        Pass ``None`` to force the no-RAM-info fallback.
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

    if available_ram is ...:
        available_ram = available_ram_bytes()

    per_worker = (
        MATLAB_RAM_PER_WORKER_BYTES
        if backend == "matlab"
        else OCTAVE_RAM_PER_WORKER_BYTES
    )
    if isinstance(available_ram, int) and available_ram > 0:
        from_ram = max(1, available_ram // per_worker)
    else:
        from_ram = FALLBACK_WORKERS

    return max(1, min(n_files, from_ram, hard_cap))
