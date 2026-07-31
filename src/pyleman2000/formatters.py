"""Post-processing helpers for Docker model JSON output."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

import numpy as np
import pandas as pd


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
    records = normalize_local_global_comparison(local_global_comparison)
    frames: list[pd.DataFrame] = []

    for record in records:
        running_correlation = np.asarray(record["running_correlation"], dtype=float)
        n = len(running_correlation)
        time_sec = np.linspace(0.0, float(audio_length_sec), num=n)
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
        return pd.DataFrame(
            columns=[
                "local_decay_sec",
                "global_decay_sec",
                "time_sec",
                "running_correlation",
            ]
        )

    return pd.concat(frames, ignore_index=True)


def window_local_global_comparison(
    local_global_comparison: pd.DataFrame,
    windows: Sequence[Sequence[float]],
    windowing_function: Callable[[np.ndarray], float] = np.mean,
) -> pd.DataFrame:
    """Average running correlations within specified time windows.

    Averaging uses the half-open interval ``[window_start, window_end)``.

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
        One row per decay-parameter pair and window.
    """
    if not windows:
        raise ValueError("windows must contain at least one (start, end) pair")

    validated: list[tuple[float, float]] = []
    for window in windows:
        if len(window) != 2:
            raise ValueError(
                f"Each window must have length 2, got {window!r}"
            )
        start, end = float(window[0]), float(window[1])
        if end < start:
            raise ValueError(
                f"window_end must be >= window_start, got ({start}, {end})"
            )
        validated.append((start, end))

    local_vals = sorted(local_global_comparison["local_decay_sec"].unique())
    global_vals = sorted(local_global_comparison["global_decay_sec"].unique())
    rows: list[dict[str, Any]] = []

    for local_decay_sec in local_vals:
        for global_decay_sec in global_vals:
            subset = local_global_comparison[
                (local_global_comparison["local_decay_sec"] == local_decay_sec)
                & (local_global_comparison["global_decay_sec"] == global_decay_sec)
            ]
            for window_id, (window_start, window_end) in enumerate(validated, start=1):
                mask = (subset["time_sec"] >= window_start) & (
                    subset["time_sec"] < window_end
                )
                values = subset.loc[mask, "running_correlation"].to_numpy(dtype=float)
                if values.size == 0:
                    aggregated = float("nan")
                else:
                    aggregated = float(windowing_function(values))
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

    return pd.DataFrame(rows)
