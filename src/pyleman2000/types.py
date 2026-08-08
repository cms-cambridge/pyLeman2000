"""Result types for the Leman (2000) model."""

from __future__ import annotations

from collections.abc import Sequence
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd


def _copy_dataframe(frame: pd.DataFrame) -> pd.DataFrame:
    """Return a DataFrame detached from caller-owned mutable values."""
    copied = frame.copy(deep=True)
    for column in copied.columns:
        series = copied[column]
        if pd.api.types.is_object_dtype(series.dtype):
            copied[column] = [deepcopy(value) for value in series.to_list()]
    return copied


@dataclass(frozen=True, eq=False)
class Leman2000Result:
    """Structured output from :func:`pyleman2000.leman2000`.

    Equality is intentionally identity-based (``eq=False``): comparing nested
    DataFrames and optional MATLAB payloads by value is brittle and rarely
    useful for callers. Compare attributes or DataFrames explicitly instead.

    Parameters
    ----------
    audio_length_sec :
        Length of the input audio file in seconds.
    num_channels :
        Number of channels in the input audio file.
    sample_rate :
        Sample rate of the input audio file in Hz.
    local_global_comparison :
        Running correlations between local and global images over time.
        Columns: ``local_decay_sec``, ``global_decay_sec``, ``time_sec``,
        ``running_correlation``.
    windowed_local_global_comparison :
        Windowed averages of local-global correlations, if windows were
        requested. Columns: ``local_decay_sec``, ``global_decay_sec``,
        ``window_id``, ``window_start``, ``window_end``,
        ``local_global_correlation``.
    auditory_nerve :
        Auditory nerve simulation outputs, if requested. These are nested
        dictionaries from the MATLAB binary (commonly including keys such as
        ``images``, ``sample_freq``, and ``filter_freqs``) and can be large.
    periodicity_pitch :
        Periodicity pitch outputs, if requested. These are nested dictionaries
        from the MATLAB binary (commonly including keys such as ``signal``,
        ``sample_freq``, ``pitch_periods``, and
        ``filtered_auditory_nerve_images``) and can be large.
    """

    audio_length_sec: float
    num_channels: int
    sample_rate: float
    local_global_comparison: pd.DataFrame
    windowed_local_global_comparison: pd.DataFrame | None = None
    auditory_nerve: dict[str, Any] | None = None
    periodicity_pitch: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        """Detach mutable output objects from caller-owned inputs."""
        object.__setattr__(
            self,
            "local_global_comparison",
            _copy_dataframe(self.local_global_comparison),
        )
        if self.windowed_local_global_comparison is not None:
            object.__setattr__(
                self,
                "windowed_local_global_comparison",
                _copy_dataframe(self.windowed_local_global_comparison),
            )
        object.__setattr__(self, "auditory_nerve", deepcopy(self.auditory_nerve))
        object.__setattr__(
            self,
            "periodicity_pitch",
            deepcopy(self.periodicity_pitch),
        )

    def __repr__(self) -> str:
        """Return a compact summary that avoids dumping large payloads."""
        windowed = self.windowed_local_global_comparison
        windowed_summary = (
            "None"
            if windowed is None
            else f"DataFrame(shape={tuple(windowed.shape)})"
        )
        return (
            "Leman2000Result("
            f"audio_length_sec={self.audio_length_sec!r}, "
            f"num_channels={self.num_channels!r}, "
            f"sample_rate={self.sample_rate!r}, "
            "local_global_comparison="
            f"DataFrame(shape={tuple(self.local_global_comparison.shape)}), "
            f"windowed_local_global_comparison={windowed_summary}, "
            f"auditory_nerve={'set' if self.auditory_nerve is not None else None}, "
            "periodicity_pitch="
            f"{'set' if self.periodicity_pitch is not None else None})"
        )


FILE_COLUMNS = [
    "file_id",
    "input_file",
    "status",
    "audio_length_sec",
    "num_channels",
    "sample_rate",
]


@dataclass(frozen=True)
class Leman2000BatchFailure:
    """Failure information for one file in a batch.

    Parameters
    ----------
    file_id :
        One-based position of the file in the batch input.
    input_file :
        Resolved path to the input file.
    error_type :
        Name of the exception class raised while processing the file.
    message :
        Exception message.
    exception :
        Original exception object, including its type and diagnostic context.
    """

    file_id: int
    input_file: str
    error_type: str
    message: str
    exception: BaseException = field(repr=False, compare=False)


@dataclass(frozen=True, eq=False)
class Leman2000BatchResult:
    """Stacked output from :func:`pyleman2000.leman2000_batch`.

    Parameters
    ----------
    workers :
        Number of warm workers used for the batch.
    files :
        One row per input file. Columns: ``file_id``, ``input_file``,
        ``status``, ``audio_length_sec``, ``num_channels``, ``sample_rate``.
        Metadata values use nullable numeric dtypes and are missing for files
        that failed.
    local_global_comparison :
        Running correlations for all files, with ``file_id`` and
        ``input_file`` columns prepended.
    windowed_local_global_comparison :
        Windowed averages, with ``file_id`` and ``input_file`` columns
        prepended, or ``None`` when no file was windowed. Only files that were
        windowed contribute rows, so if windows were requested for some files
        but not others this table covers just that subset (``leman2000_batch``
        shares one ``windows`` argument, so its output is all-or-nothing).
    results :
        Per-file :class:`Leman2000Result` values in input order (escape hatch
        for ``keep_*`` payloads). A failed file has ``None`` in its original
        position.
    failures :
        Structured details and original exceptions for failed files, ordered
        by input position.
    """

    workers: int
    files: pd.DataFrame
    local_global_comparison: pd.DataFrame
    windowed_local_global_comparison: pd.DataFrame | None = None
    results: tuple[Leman2000Result | None, ...] = ()
    failures: tuple[Leman2000BatchFailure, ...] = ()

    def __post_init__(self) -> None:
        """Detach mutable output objects from caller-owned inputs."""
        object.__setattr__(self, "files", _copy_dataframe(self.files))
        object.__setattr__(
            self,
            "local_global_comparison",
            _copy_dataframe(self.local_global_comparison),
        )
        if self.windowed_local_global_comparison is not None:
            object.__setattr__(
                self,
                "windowed_local_global_comparison",
                _copy_dataframe(self.windowed_local_global_comparison),
            )
        object.__setattr__(self, "results", tuple(self.results))
        object.__setattr__(self, "failures", tuple(self.failures))

    def __repr__(self) -> str:
        """Return a compact summary that avoids dumping large payloads."""
        windowed = self.windowed_local_global_comparison
        windowed_summary = (
            "None"
            if windowed is None
            else f"DataFrame(shape={tuple(windowed.shape)})"
        )
        return (
            "Leman2000BatchResult("
            f"workers={self.workers!r}, "
            f"files=DataFrame(shape={tuple(self.files.shape)}), "
            "local_global_comparison="
            f"DataFrame(shape={tuple(self.local_global_comparison.shape)}), "
            f"windowed_local_global_comparison={windowed_summary}, "
            f"results=({len(self.results)} results), "
            f"failures=({len(self.failures)} failures))"
        )


def combine_results(
    input_files: Sequence[str | Path],
    results: Sequence[Leman2000Result | None],
    *,
    workers: int,
    errors: Sequence[BaseException | None] | None = None,
) -> Leman2000BatchResult:
    """Stack per-file results into a :class:`Leman2000BatchResult`.

    Parameters
    ----------
    input_files :
        Input paths in the same order as ``results``.
    results :
        Per-file model outputs. Failed files are represented by ``None``.
    workers :
        Worker count to record on the batch result.
    errors :
        Exceptions aligned with ``input_files`` and ``results``. Required for
        each failed result and omitted for successful results.

    Returns
    -------
    Leman2000BatchResult
        Combined tables plus the original per-file results. The windowed table
        includes only files whose result carried windows; if some results are
        windowed and others are not, the missing files simply have no windowed
        rows (no error is raised).
    """
    if len(input_files) != len(results):
        raise ValueError(
            "input_files and results must have the same length, got "
            f"{len(input_files)} and {len(results)}"
        )
    if errors is None:
        errors = [None] * len(results)
    if len(errors) != len(results):
        raise ValueError(
            "errors and results must have the same length, got "
            f"{len(errors)} and {len(results)}"
        )

    file_rows: list[dict[str, Any]] = []
    local_frames: list[pd.DataFrame] = []
    windowed_frames: list[pd.DataFrame] = []
    failures: list[Leman2000BatchFailure] = []
    any_windowed = False

    for index, (path, result, error) in enumerate(
        zip(input_files, results, errors, strict=True)
    ):
        file_id = index + 1
        resolved = str(Path(path).expanduser().resolve())
        if (result is None) == (error is None):
            raise ValueError(
                "each file must have exactly one result or error; "
                f"file_id {file_id} has result={result is not None} and "
                f"error={error is not None}"
            )
        if result is None:
            assert error is not None
            file_rows.append(
                {
                    "file_id": file_id,
                    "input_file": resolved,
                    "status": "error",
                    "audio_length_sec": None,
                    "num_channels": None,
                    "sample_rate": None,
                }
            )
            failures.append(
                Leman2000BatchFailure(
                    file_id=file_id,
                    input_file=resolved,
                    error_type=type(error).__name__,
                    message=str(error),
                    exception=error,
                )
            )
            continue

        file_rows.append(
            {
                "file_id": file_id,
                "input_file": resolved,
                "status": "ok",
                "audio_length_sec": result.audio_length_sec,
                "num_channels": result.num_channels,
                "sample_rate": result.sample_rate,
            }
        )
        local = result.local_global_comparison.copy(deep=True)
        local.insert(0, "input_file", resolved)
        local.insert(0, "file_id", file_id)
        local_frames.append(local)

        windowed = result.windowed_local_global_comparison
        if windowed is not None:
            any_windowed = True
            framed = windowed.copy(deep=True)
            framed.insert(0, "input_file", resolved)
            framed.insert(0, "file_id", file_id)
            windowed_frames.append(framed)

    files = pd.DataFrame(file_rows, columns=FILE_COLUMNS).astype(
        {
            "audio_length_sec": "Float64",
            "num_channels": "Int64",
            "sample_rate": "Float64",
        }
    )
    if local_frames:
        local_global = pd.concat(local_frames, ignore_index=True)
    else:
        local_global = pd.DataFrame(
            columns=[
                "file_id",
                "input_file",
                "local_decay_sec",
                "global_decay_sec",
                "time_sec",
                "running_correlation",
            ]
        )

    windowed_local_global = None
    if any_windowed:
        windowed_local_global = (
            pd.concat(windowed_frames, ignore_index=True)
            if windowed_frames
            else pd.DataFrame(
                columns=[
                    "file_id",
                    "input_file",
                    "local_decay_sec",
                    "global_decay_sec",
                    "window_id",
                    "window_start",
                    "window_end",
                    "local_global_correlation",
                ]
            )
        )

    return Leman2000BatchResult(
        workers=workers,
        files=files,
        local_global_comparison=local_global,
        windowed_local_global_comparison=windowed_local_global,
        results=tuple(results),
        failures=tuple(failures),
    )
