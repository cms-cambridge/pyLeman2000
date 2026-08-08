"""Tests for the Docker image pull and model-run progress displays."""

from __future__ import annotations

import io

from pyleman2000.progress import BatchProgress, PullProgress, RunProgress, format_bytes


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


def test_run_progress_rewrites_on_terminal(monkeypatch) -> None:
    monkeypatch.setenv("COLUMNS", "200")
    stream = _Terminal()
    progress = RunProgress(stream, min_interval_sec=0)

    progress.preparing()
    progress.running(0)
    progress.running(3)
    progress.reading()
    progress.close()

    assert stream.getvalue().startswith("\r")
    assert stream.getvalue().endswith("\n")
    assert "Running Leman (2000) model: 3s" in stream.getvalue()
    final = stream.getvalue().split("\r")[-1]
    assert final.startswith("Reading Leman (2000) results")


def test_run_progress_writes_stepped_lines_when_not_a_terminal() -> None:
    stream = io.StringIO()
    progress = RunProgress(stream, step_sec=5)

    progress.preparing()
    progress.running(0)
    progress.running(2)
    progress.running(5)
    progress.running(9)
    progress.running(10)
    progress.reading()
    progress.close()

    assert stream.getvalue().splitlines() == [
        "Preparing Leman (2000) container",
        "Running Leman (2000) model: 0s",
        "Running Leman (2000) model: 5s",
        "Running Leman (2000) model: 10s",
        "Reading Leman (2000) results",
    ]


def test_batch_progress_rewrites_on_terminal(monkeypatch) -> None:
    monkeypatch.setenv("COLUMNS", "200")
    stream = _Terminal()
    progress = BatchProgress(stream, min_interval_sec=0)

    progress.start(n_files=3, n_workers=2)
    progress.update(1)
    progress.update(3)
    progress.close()

    assert stream.getvalue().startswith("\r")
    assert stream.getvalue().endswith("\n")
    assert "Leman (2000) batch: 3/3 files (2 workers)" in stream.getvalue()


def test_batch_progress_writes_lines_when_not_a_terminal() -> None:
    stream = io.StringIO()
    progress = BatchProgress(stream, step_files=2)

    progress.start(n_files=4, n_workers=2)
    progress.update(1)
    progress.update(2)
    progress.update(3)
    progress.update(4)
    progress.close()

    assert stream.getvalue().splitlines() == [
        "Leman (2000) batch: 0/4 files (2 workers)",
        "Leman (2000) batch: 2/4 files (2 workers)",
        "Leman (2000) batch: 4/4 files (2 workers)",
    ]
