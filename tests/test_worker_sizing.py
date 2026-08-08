"""Tests for audio-duration-driven worker sizing."""

from __future__ import annotations

import wave
from pathlib import Path

import pytest

from pyleman2000 import example_wav_path
from pyleman2000.worker_sizing import (
    MATLAB_AUDIO_SEC_PER_WORKER,
    WORKERS_ENV,
    choose_worker_count,
    is_likely_emulated_amd64,
    ram_per_worker_bytes,
    wav_duration_sec,
    wav_durations_sec,
)

PLENTY_RAM = 100 * 1024**3


def _choose(n_files: int, audio_sec: float | None, **kwargs) -> int:
    """Call choose_worker_count with generous, deterministic caps."""
    defaults = {
        "total_audio_sec": audio_sec,
        "available_ram": PLENTY_RAM,
        "cpu_count": 64,
        "emulated": False,
        "environ": {},
    }
    defaults.update(kwargs)
    return choose_worker_count(n_files, **defaults)


def test_short_audio_stays_sequential() -> None:
    # 4 x 5 s: benchmarked as slower with extra workers.
    assert _choose(4, 20.0) == 1


def test_long_audio_scales_up() -> None:
    # 4 x 30 s: benchmarked 1.67x faster at 4 workers.
    assert _choose(4, 120.0) == 4


def test_workers_track_audio_per_worker_budget() -> None:
    assert _choose(100, 3 * MATLAB_AUDIO_SEC_PER_WORKER) == 3


def test_octave_short_audio_parallelizes() -> None:
    # 4 x 0.37 s: benchmarked 2.5x faster at 4 workers.
    assert _choose(4, 4 * 0.37, max_audio_sec=0.37, backend="octave") == 4


def test_octave_long_audio_is_ram_limited() -> None:
    # Spool path ~1 GB/worker at 30 s; a tight budget still permits only one.
    budget = ram_per_worker_bytes("octave", max_audio_sec=30.0)
    assert (
        _choose(
            4,
            120.0,
            max_audio_sec=30.0,
            backend="octave",
            available_ram=budget,
        )
        == 1
    )


def test_unknown_duration_falls_back_to_one_worker() -> None:
    assert _choose(8, None) == 1


def test_capped_by_file_count() -> None:
    assert _choose(2, 1000.0) == 2


def test_capped_by_cpu_count() -> None:
    assert _choose(100, 1000.0, cpu_count=2) == 2


def test_capped_by_available_ram() -> None:
    ram = 2 * ram_per_worker_bytes("matlab", max_audio_sec=30.0)
    assert (
        _choose(
            100,
            1000.0,
            max_audio_sec=30.0,
            available_ram=ram,
            backend="matlab",
        )
        == 2
    )


def test_ram_budget_grows_with_audio_length() -> None:
    short = ram_per_worker_bytes("matlab", max_audio_sec=5.0)
    long = ram_per_worker_bytes("matlab", max_audio_sec=300.0)
    assert long > short
    # Spool-path peak was ~806 MB PSS at 120 s; budget must cover it with
    # safety (see artifacts/benchmark/path_memory_compare.md).
    assert ram_per_worker_bytes("matlab", max_audio_sec=120.0) >= 900 * 1024**2
    assert ram_per_worker_bytes("matlab", max_audio_sec=120.0) < 2 * 1024**3


def test_octave_spool_ram_budget_matches_matlab_order() -> None:
    # Both backends use the disk-spool path for detail<=1.
    octave = ram_per_worker_bytes("octave", 30.0)
    matlab = ram_per_worker_bytes("matlab", 30.0)
    assert octave == matlab
    assert octave < 2 * 1024**3


def test_detail_ram_budget_uses_full_matrix_path() -> None:
    spool = ram_per_worker_bytes("matlab", max_audio_sec=30.0, detail=0)
    detail = ram_per_worker_bytes("matlab", max_audio_sec=30.0, detail=5)
    assert detail > spool
    # Classic Octave path remains much hungrier than spool.
    assert ram_per_worker_bytes("octave", 30.0, detail=5) >= 11.6 * 1024**3
    assert (
        _choose(
            4,
            120.0,
            max_audio_sec=30.0,
            backend="matlab",
            detail=5,
            available_ram=2 * detail,
        )
        == 2
    )


def test_explicit_workers_override_duration() -> None:
    assert _choose(8, 10.0, workers=4) == 4


def test_explicit_workers_capped_by_file_count() -> None:
    assert _choose(3, 1000.0, workers=8) == 3


def test_explicit_workers_bypass_ram_and_cpu_caps() -> None:
    # An explicit request is honoured even when auto-sizing would cap it.
    assert (
        choose_worker_count(
            8,
            total_audio_sec=10.0,
            workers=8,
            available_ram=1,
            cpu_count=1,
            emulated=True,
        )
        == 8
    )


def test_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(WORKERS_ENV, "5")
    assert choose_worker_count(
        20,
        total_audio_sec=10.0,
        available_ram=PLENTY_RAM,
        cpu_count=64,
        emulated=False,
    ) == 5


def test_emulated_hard_cap() -> None:
    assert _choose(20, 10_000.0, emulated=True) == 4


def test_available_ram_respects_cgroup_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import pyleman2000.worker_sizing as ws

    monkeypatch.setattr(ws, "_host_available_ram_bytes", lambda: 64 * 1024**3)
    # cgroup limit far below host RAM (e.g. a small k8s pod).
    monkeypatch.setattr(
        ws, "cgroup_available_ram_bytes", lambda: 3 * 1024**3
    )
    assert ws.available_ram_bytes() == 3 * 1024**3


def test_available_ram_ignores_unset_cgroup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import pyleman2000.worker_sizing as ws

    monkeypatch.setattr(ws, "_host_available_ram_bytes", lambda: 8 * 1024**3)
    monkeypatch.setattr(ws, "cgroup_available_ram_bytes", lambda: None)
    assert ws.available_ram_bytes() == 8 * 1024**3


def test_rejects_invalid_workers() -> None:
    with pytest.raises(ValueError, match="workers"):
        _choose(3, 100.0, workers=0)


def test_is_likely_emulated_amd64() -> None:
    assert is_likely_emulated_amd64("arm64")
    assert is_likely_emulated_amd64("aarch64")
    assert not is_likely_emulated_amd64("x86_64")


def test_wav_duration_reads_header() -> None:
    duration = wav_duration_sec(example_wav_path())
    assert duration == pytest.approx(0.3708, abs=1e-3)


def test_wav_duration_returns_none_for_non_wav(tmp_path: Path) -> None:
    bogus = tmp_path / "not_audio.wav"
    bogus.write_bytes(b"definitely not a wav")
    assert wav_duration_sec(bogus) is None


def test_durations_reported_per_file(tmp_path: Path) -> None:
    source = example_wav_path()
    with wave.open(str(source), "rb") as handle:
        params = handle.getparams()
        frames = handle.readframes(params.nframes)
    doubled = tmp_path / "doubled.wav"
    with wave.open(str(doubled), "wb") as handle:
        handle.setparams(params)
        handle.writeframes(frames * 2)

    single = wav_duration_sec(source)
    durations = wav_durations_sec([source, doubled])
    assert durations == pytest.approx([single, single * 2], rel=1e-6)


def test_durations_are_none_when_any_file_unreadable(tmp_path: Path) -> None:
    bogus = tmp_path / "bad.wav"
    bogus.write_bytes(b"nope")
    assert wav_durations_sec([example_wav_path(), bogus]) is None
