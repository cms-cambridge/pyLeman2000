"""Post-processing helpers for Docker model JSON output."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

import numpy as np
import pandas as pd

LOCAL_GLOBAL_COLUMNS = [
    "local_decay_sec",
    "global_decay_sec",
    "time_sec",
    "running_correlation",
]
WINDOWED_COLUMNS = [
    "local_decay_sec",
    "global_decay_sec",
    "window_id",
    "window_start",
    "window_end",
    "local_global_correlation",
]


def normalize_local_global_comparison(
    local_global_comparison: Any,
) -> list[dict[str, Any]]:
    """Normalize raw JSON local-global comparison payloads to a list of dicts.

    Parameters
    ----------
    local_global_comparison :
        Raw ``local_global_comparison`` field from the model JSON. May be a
        dict, a list of dicts, or a singly nested list (MATLAB/jsonlab quirk).

    Returns
    -------
    list of dict
        One entry per local/global decay combination.
    """
    if isinstance(local_global_comparison, dict):
        return [local_global_comparison]

    if not isinstance(local_global_comparison, list):
        raise TypeError(
            "Expected local_global_comparison to be a dict or list, "
            f"got {type(local_global_comparison)!r}"
        )

    if (
        len(local_global_comparison) == 1
        and isinstance(local_global_comparison[0], list)
    ):
        local_global_comparison = local_global_comparison[0]

    if all(isinstance(item, dict) for item in local_global_comparison):
        return list(local_global_comparison)

    raise TypeError(
        "Could not normalize local_global_comparison; "
        f"unexpected structure: {type(local_global_comparison)!r}"
    )


def validate_windows(
    windows: Sequence[Sequence[float]],
) -> list[tuple[float, float]]:
    """Validate and normalize window ``(start, end)`` pairs.

    Parameters
    ----------
    windows :
        Sequence of ``(start_sec, end_sec)`` pairs.

    Returns
    -------
    list of tuple
        Finite ``(start, end)`` pairs with ``end >= start``.
    """
    if len(windows) == 0:
        raise ValueError("windows must contain at least one (start, end) pair")

    validated: list[tuple[float, float]] = []
    for window in windows:
        if len(window) != 2:
            raise ValueError(
                f"Each window must have length 2, got {window!r}"
            )
        start, end = float(window[0]), float(window[1])
        if not np.isfinite(start) or not np.isfinite(end):
            raise ValueError(
                f"window boundaries must be finite, got ({start}, {end})"
            )
        if end < start:
            raise ValueError(
                "window_end must be greater than or equal to window_start, "
                f"got ({start}, {end})"
            )
        validated.append((start, end))
    return validated


def format_local_global_comparison(
    local_global_comparison: Any,
    audio_length_sec: float,
) -> pd.DataFrame:
    """Expand local-global comparison records into a long DataFrame.

    Parameters
    ----------
    local_global_comparison :
        Raw model output for local/global running correlations.
    audio_length_sec :
        Audio duration in seconds; used to build the ``time_sec`` axis.

    Returns
    -------
    pandas.DataFrame
        Columns ``local_decay_sec``, ``global_decay_sec``, ``time_sec``,
        ``running_correlation``.
    """
    audio_length_sec = float(audio_length_sec)
    if not np.isfinite(audio_length_sec) or audio_length_sec < 0:
        raise ValueError("audio_length_sec must be a finite, non-negative number")

    records = normalize_local_global_comparison(local_global_comparison)
    frames: list[pd.DataFrame] = []

    for record in records:
        running_correlation = np.asarray(record["running_correlation"], dtype=float)
        if running_correlation.ndim != 1:
            raise ValueError("running_correlation must be one-dimensional")
        n = len(running_correlation)
        time_sec = np.linspace(0.0, audio_length_sec, num=n)
        frames.append(
            pd.DataFrame(
                {
                    "local_decay_sec": float(record["local_decay_sec"]),
                    "global_decay_sec": float(record["global_decay_sec"]),
                    "time_sec": time_sec,
                    "running_correlation": running_correlation,
                }
            )
        )

    if not frames:
        return pd.DataFrame(columns=LOCAL_GLOBAL_COLUMNS)

    return pd.concat(frames, ignore_index=True)


def window_local_global_comparison(
    local_global_comparison: pd.DataFrame,
    windows: Sequence[Sequence[float]],
    windowing_function: Callable[[np.ndarray], float] = np.mean,
) -> pd.DataFrame:
    """Aggregate running correlations within specified time windows.

    Windows are closed intervals: both ``window_start`` and ``window_end``
    are included. A boundary shared by adjacent windows is therefore included
    in both. This intentionally diverges from ``leman2000R``, which uses
    half-open intervals ``[start, end)``.

    Parameters
    ----------
    local_global_comparison :
        Long-form DataFrame from :func:`format_local_global_comparison`.
    windows :
        Sequence of ``(start_sec, end_sec)`` pairs.
    windowing_function :
        Reduction applied to correlations inside each window. Defaults to
        the mean.

    Returns
    -------
    pandas.DataFrame
        One row per decay-parameter pair and window. Rows are ordered
        window-major (``window_id`` slowest to change within each window
        block of parameter pairs). ``window_id`` is 1-based.
    """
    if not callable(windowing_function):
        raise TypeError("windowing_function must be callable")

    validated = validate_windows(windows)

    pairs = list(
        local_global_comparison[
            ["local_decay_sec", "global_decay_sec"]
        ]
        .drop_duplicates()
        .itertuples(index=False, name=None)
    )
    grouped = {
        (local_decay_sec, global_decay_sec): group[
            ["time_sec", "running_correlation"]
        ].to_numpy(dtype=float)
        for (local_decay_sec, global_decay_sec), group in (
            local_global_comparison.groupby(
                ["local_decay_sec", "global_decay_sec"],
                sort=False,
            )
        )
    }
    rows: list[dict[str, Any]] = []

    # Window-major ordering matches leman2000R's expand.grid output.
    for window_id, (window_start, window_end) in enumerate(validated, start=1):
        for local_decay_sec, global_decay_sec in pairs:
            samples = grouped[(local_decay_sec, global_decay_sec)]
            mask = (samples[:, 0] >= window_start) & (
                samples[:, 0] <= window_end
            )
            values = samples[mask, 1]
            aggregated = (
                float(windowing_function(values))
                if values.size
                else float("nan")
            )
            rows.append(
                {
                    "local_decay_sec": float(local_decay_sec),
                    "global_decay_sec": float(global_decay_sec),
                    "window_id": window_id,
                    "window_start": window_start,
                    "window_end": window_end,
                    "local_global_correlation": aggregated,
                }
            )

    return pd.DataFrame(rows, columns=WINDOWED_COLUMNS)
