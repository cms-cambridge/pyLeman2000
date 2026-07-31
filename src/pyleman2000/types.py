"""Result types for the Leman (2000) model."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
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
