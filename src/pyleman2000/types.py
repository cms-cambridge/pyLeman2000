"""Result types for the Leman (2000) model."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any

import pandas as pd


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
        Auditory nerve simulation outputs, if requested.
    periodicity_pitch :
        Periodicity pitch outputs, if requested.
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
            self.local_global_comparison.copy(deep=True),
        )
        if self.windowed_local_global_comparison is not None:
            object.__setattr__(
                self,
                "windowed_local_global_comparison",
                self.windowed_local_global_comparison.copy(deep=True),
            )
        object.__setattr__(self, "auditory_nerve", deepcopy(self.auditory_nerve))
        object.__setattr__(
            self,
            "periodicity_pitch",
            deepcopy(self.periodicity_pitch),
        )

    def __eq__(self, other: object) -> bool:
        """Compare result values, including pandas objects."""
        if not isinstance(other, Leman2000Result):
            return NotImplemented
        windowed_equal = (
            self.windowed_local_global_comparison is None
            and other.windowed_local_global_comparison is None
        ) or (
            self.windowed_local_global_comparison is not None
            and other.windowed_local_global_comparison is not None
            and self.windowed_local_global_comparison.equals(
                other.windowed_local_global_comparison
            )
        )
        return (
            self.audio_length_sec == other.audio_length_sec
            and self.num_channels == other.num_channels
            and self.sample_rate == other.sample_rate
            and self.local_global_comparison.equals(
                other.local_global_comparison
            )
            and windowed_equal
            and self.auditory_nerve == other.auditory_nerve
            and self.periodicity_pitch == other.periodicity_pitch
        )

    __hash__ = None
