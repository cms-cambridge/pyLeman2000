"""Result types for the Leman (2000) model."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd


@dataclass(frozen=True)
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
