"""Result types for the Leman (2000) model."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd


def _copy_dataframe(frame: pd.DataFrame) -> pd.DataFrame:
    """Return a DataFrame detached from caller-owned mutable values."""
    copied = frame.copy(deep=True)
    for column in copied.columns:
        series = copied[column]
        if pd.api.types.is_object_dtype(series.dtype):
            copied[column] = [deepcopy(value) for value in series.to_list()]
    return copied


def _values_equal(left: Any, right: Any) -> bool:
    """Recursively compare nested values, including NumPy arrays."""
    if left is right:
        return True
    if isinstance(left, pd.DataFrame) and isinstance(right, pd.DataFrame):
        return left.equals(right)
    if isinstance(left, pd.Series) and isinstance(right, pd.Series):
        return left.equals(right)
    if isinstance(left, np.ndarray) and isinstance(right, np.ndarray):
        return left.shape == right.shape and np.array_equal(
            left, right, equal_nan=True
        )
    if isinstance(left, dict) and isinstance(right, dict):
        if left.keys() != right.keys():
            return False
        return all(_values_equal(left[key], right[key]) for key in left)
    if isinstance(left, (list, tuple)) and isinstance(right, (list, tuple)):
        if len(left) != len(right):
            return False
        return all(
            _values_equal(left_item, right_item)
            for left_item, right_item in zip(left, right, strict=True)
        )
    if isinstance(left, (float, np.floating)) and isinstance(
        right, (float, np.floating)
    ):
        if np.isnan(left) and np.isnan(right):
            return True
    try:
        equal = left == right
    except (TypeError, ValueError):
        return False
    if isinstance(equal, np.ndarray):
        return bool(np.all(equal))
    return bool(equal)


@dataclass(frozen=True, eq=False)
class Leman2000Result:
    """Structured output from :func:`pyleman2000.leman2000`.

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

    def __eq__(self, other: object) -> bool:
        """Compare result values, including pandas objects and arrays."""
        if not isinstance(other, Leman2000Result):
            return NotImplemented
        return (
            self.audio_length_sec == other.audio_length_sec
            and self.num_channels == other.num_channels
            and self.sample_rate == other.sample_rate
            and _values_equal(
                self.local_global_comparison, other.local_global_comparison
            )
            and _values_equal(
                self.windowed_local_global_comparison,
                other.windowed_local_global_comparison,
            )
            and _values_equal(self.auditory_nerve, other.auditory_nerve)
            and _values_equal(self.periodicity_pitch, other.periodicity_pitch)
        )

    __hash__ = None
