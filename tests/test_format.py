"""Unit tests for formatting and windowing helpers."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from pyleman2000.formatters import (
    format_local_global_comparison,
    normalize_local_global_comparison,
    window_local_global_comparison,
)

FIXTURE = Path(__file__).parent / "fixtures" / "sample_result.json"


@pytest.fixture
def raw_result() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_format_expands_parameter_combinations(raw_result: dict) -> None:
    df = format_local_global_comparison(
        raw_result["local_global_comparison"],
        raw_result["audio_length_sec"],
    )

    combos = (
        df[["local_decay_sec", "global_decay_sec"]]
        .drop_duplicates()
        .sort_values(["global_decay_sec", "local_decay_sec"])
        .reset_index(drop=True)
    )
    expected = pd.DataFrame(
        {
            "local_decay_sec": [0.1, 0.2, 0.1, 0.2],
            "global_decay_sec": [1.0, 1.0, 2.0, 2.0],
        }
    )
    pd.testing.assert_frame_equal(combos, expected)

    times = np.unique(df["time_sec"])
    expected_times = np.linspace(
        0.0,
        raw_result["audio_length_sec"],
        num=len(df) // 4,
    )
    np.testing.assert_allclose(times, expected_times)


def test_normalize_handles_single_dict() -> None:
    records = normalize_local_global_comparison(
        {
            "local_decay_sec": 0.1,
            "global_decay_sec": 1.0,
            "running_correlation": [0.5],
        }
    )
    assert len(records) == 1
    assert records[0]["local_decay_sec"] == 0.1


def test_normalize_handles_singly_nested_list() -> None:
    inner = [
        {
            "local_decay_sec": 0.1,
            "global_decay_sec": 1.0,
            "running_correlation": [0.5, 0.6],
        }
    ]
    records = normalize_local_global_comparison([inner])
    assert records == inner


def test_windowed_averages(raw_result: dict) -> None:
    df = format_local_global_comparison(
        raw_result["local_global_comparison"],
        raw_result["audio_length_sec"],
    )
    windows = [(0.0, 0.1), (0.1, 0.2), (0.2, 0.3)]
    windowed = window_local_global_comparison(df, windows)

    unique_windows = (
        windowed[["window_start", "window_end"]]
        .drop_duplicates()
        .reset_index(drop=True)
    )
    expected = pd.DataFrame(
        {
            "window_start": [0.0, 0.1, 0.2],
            "window_end": [0.1, 0.2, 0.3],
        }
    )
    pd.testing.assert_frame_equal(unique_windows, expected)
    assert len(windowed) == 4 * 3  # 4 param combos × 3 windows


def test_custom_windowing_function(raw_result: dict) -> None:
    df = format_local_global_comparison(
        raw_result["local_global_comparison"],
        raw_result["audio_length_sec"],
    )
    windowed = window_local_global_comparison(
        df,
        windows=[(0.0, 0.3)],
        windowing_function=np.median,
    )
    assert windowed["local_global_correlation"].notna().all()


def test_empty_window_yields_nan(raw_result: dict) -> None:
    df = format_local_global_comparison(
        raw_result["local_global_comparison"],
        raw_result["audio_length_sec"],
    )
    windowed = window_local_global_comparison(df, windows=[(10.0, 11.0)])
    assert windowed["local_global_correlation"].isna().all()
