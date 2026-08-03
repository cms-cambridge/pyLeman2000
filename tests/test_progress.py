"""Tests for the Docker image pull progress display."""

from __future__ import annotations

import io

from pyleman2000.progress import PullProgress, format_bytes


class _Terminal(io.StringIO):
    def isatty(self) -> bool:
        return True


def _download_events(layer: str, total: int, current: int) -> dict[str, object]:
    return {
        "id": layer,
        "status": "Downloading",
        "progressDetail": {"current": current, "total": total},
    }


def test_format_bytes_uses_readable_units() -> None:
    assert format_bytes(512) == "512 B"
    assert format_bytes(1536) == "1.5 kB"
    assert format_bytes(1024**3) == "1.0 GB"


def test_progress_reports_totals_across_layers(monkeypatch) -> None:
    monkeypatch.setenv("COLUMNS", "200")
    stream = _Terminal()
    progress = PullProgress("example.org/model@sha256:abc", stream, min_interval_sec=0)

    progress.update(_download_events("a", total=1000, current=500))
    progress.update(_download_events("b", total=1000, current=0))
    progress.update({"id": "b", "status": "Pull complete", "progressDetail": {}})
    progress.close()

    line = stream.getvalue().split("\r")[-1]
    assert line.startswith("Pulling example.org/model: ")
    assert "@sha256" not in line
    assert "62% (downloaded 1.5 kB / 2.0 kB, extracted 1000 B)" in line


def test_progress_writes_periodic_lines_when_not_a_terminal() -> None:
    stream = io.StringIO()
    progress = PullProgress("example.org/model", stream, step_percent=25)

    for current in range(0, 1001, 100):
        progress.update(_download_events("a", total=1000, current=current))
    progress.update({"id": "a", "status": "Pull complete", "progressDetail": {}})
    progress.close()

    lines = stream.getvalue().splitlines()
    assert "\r" not in stream.getvalue()
    assert [line.split()[2] for line in lines] == ["0%", "25%", "50%", "100%"]
