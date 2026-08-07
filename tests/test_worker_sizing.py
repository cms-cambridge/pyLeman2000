"""Tests for RAM-aware worker sizing."""

from __future__ import annotations

import pytest

from pyleman2000.worker_sizing import (
    FALLBACK_WORKERS,
    MATLAB_RAM_PER_WORKER_BYTES,
    WORKERS_ENV,
    choose_worker_count,
    is_likely_emulated_amd64,
)


def test_explicit_workers_capped_by_file_count() -> None:
    assert choose_worker_count(3, workers=8, available_ram=64 * 1024**3) == 3


def test_ram_budget_selects_workers() -> None:
    ram = 3 * MATLAB_RAM_PER_WORKER_BYTES
    assert (
        choose_worker_count(
            10,
            backend="matlab",
            available_ram=ram,
            emulated=False,
            environ={},
        )
        == 3
    )


def test_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(WORKERS_ENV, "5")
    assert (
        choose_worker_count(
            20,
            available_ram=100 * 1024**3,
            emulated=False,
        )
        == 5
    )


def test_fallback_without_ram_info() -> None:
    assert (
        choose_worker_count(
            20,
            available_ram=None,
            emulated=False,
            environ={},
        )
        == FALLBACK_WORKERS
    )


def test_emulated_hard_cap() -> None:
    assert (
        choose_worker_count(
            20,
            available_ram=100 * 1024**3,
            emulated=True,
            environ={},
        )
        == 4
    )


def test_rejects_invalid_workers() -> None:
    with pytest.raises(ValueError, match="workers"):
        choose_worker_count(3, workers=0)


def test_is_likely_emulated_amd64() -> None:
    assert is_likely_emulated_amd64("arm64")
    assert is_likely_emulated_amd64("aarch64")
    assert not is_likely_emulated_amd64("x86_64")
