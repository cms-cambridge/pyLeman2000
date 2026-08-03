"""Tests for public result value semantics."""

from __future__ import annotations

import pandas as pd

from pyleman2000 import Leman2000Result


def _result(
    frame: pd.DataFrame,
    payload: dict | None = None,
) -> Leman2000Result:
    return Leman2000Result(
        audio_length_sec=1.0,
        num_channels=1,
        sample_rate=44_100.0,
        local_global_comparison=frame,
        auditory_nerve=payload,
    )


def test_result_copies_mutable_inputs() -> None:
    frame = pd.DataFrame({"running_correlation": [0.5]})
    payload = {"images": [[1, 2]]}

    result = _result(frame, payload)
    frame.iloc[0, 0] = 0.0
    payload["images"][0][0] = 9

    assert result.local_global_comparison.iloc[0, 0] == 0.5
    assert result.auditory_nerve == {"images": [[1, 2]]}


def test_result_copies_object_dtype_cells() -> None:
    nested = [1, 2]
    frame = pd.DataFrame({"payload": [nested]})

    result = _result(frame)
    nested[0] = 9

    assert result.local_global_comparison.iloc[0, 0] == [1, 2]


def test_result_repr_is_compact() -> None:
    result = _result(
        pd.DataFrame({"running_correlation": [0.5, 0.6]}),
        {"images": [[1, 2]]},
    )

    text = repr(result)
    assert "DataFrame(shape=(2, 1))" in text
    assert "auditory_nerve=set" in text
    assert "[[1, 2]]" not in text
