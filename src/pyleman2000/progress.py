"""Human-readable progress reporting for Docker image pulls and model runs."""

from __future__ import annotations

import shutil
import sys
import time
from collections.abc import Mapping
from typing import Any, TextIO

_DOWNLOADED_STATUSES = frozenset(
    {
        "Verifying Checksum",
        "Download complete",
        "Pull complete",
        "Already exists",
    }
)
_EXTRACTED_STATUSES = frozenset({"Pull complete", "Already exists"})


def format_bytes(num_bytes: float) -> str:
    """Return a compact human-readable size.

    Parameters
    ----------
    num_bytes :
        Size in bytes.

    Returns
    -------
    str
        Size rounded to a sensible unit, for example ``"1.1 GB"``.
    """
    value = float(num_bytes)
    for unit in ("B", "kB", "MB", "GB", "TB"):
        if abs(value) < 1024 or unit == "TB":
            return f"{value:.0f} B" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    raise AssertionError("unreachable")


def _as_int(value: Any) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


class PullProgress:
    """Render Docker image pull events as a progress display.

    Docker reports pull progress per image layer. This class aggregates those
    per-layer events into a single status line so that the ~1 GB first pull
    does not look stalled.

    Parameters
    ----------
    image :
        Image reference being pulled. Any ``@sha256:...`` digest is trimmed
        from the displayed name.
    stream :
        Destination for progress output. Defaults to :data:`sys.stderr`,
        looked up at write time.
    min_interval_sec :
        Smallest delay between redraws on an interactive terminal.
    step_percent :
        Overall percentage increase that triggers a new line when the
        destination is not an interactive terminal.
    """

    def __init__(
        self,
        image: str,
        stream: TextIO | None = None,
        *,
        min_interval_sec: float = 0.2,
        step_percent: int = 10,
    ) -> None:
        self._image = image.split("@", 1)[0]
        self._stream = stream
        self._min_interval_sec = min_interval_sec
        self._step_percent = step_percent
        self._layers: dict[str, dict[str, int]] = {}
        self._last_draw_sec = 0.0
        self._last_percent: int | None = None
        self._line_length = 0

    def update(self, event: Any) -> None:
        """Record one decoded event from the Docker pull stream.

        Parameters
        ----------
        event :
            Decoded JSON object emitted by the Docker daemon. Objects without
            a layer identifier (such as the initial ``"Pulling from ..."``
            message) are ignored.
        """
        if not isinstance(event, Mapping):
            return
        layer_id = event.get("id")
        status = event.get("status")
        if not isinstance(layer_id, str) or not layer_id:
            return
        if not isinstance(status, str):
            return

        layer = self._layers.setdefault(
            layer_id, {"total": 0, "downloaded": 0, "extracted": 0}
        )
        detail = event.get("progressDetail")
        detail = detail if isinstance(detail, Mapping) else {}
        layer["total"] = max(layer["total"], _as_int(detail.get("total")))
        current = _as_int(detail.get("current"))

        if status == "Downloading":
            layer["downloaded"] = current
        elif status == "Extracting":
            layer["downloaded"] = layer["total"]
            layer["extracted"] = current
        elif status in _DOWNLOADED_STATUSES:
            layer["downloaded"] = layer["total"]
            if status in _EXTRACTED_STATUSES:
                layer["extracted"] = layer["total"]
        else:
            return

        self._draw()

    def close(self) -> None:
        """Finish the display, leaving the cursor on a fresh line."""
        if self._layers:
            self._draw(final=True)

    def __enter__(self) -> PullProgress:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def _totals(self) -> tuple[int, int, int]:
        total = sum(layer["total"] for layer in self._layers.values())
        downloaded = sum(
            min(layer["downloaded"], layer["total"]) for layer in self._layers.values()
        )
        extracted = sum(
            min(layer["extracted"], layer["total"]) for layer in self._layers.values()
        )
        return total, downloaded, extracted

    def _draw(self, *, final: bool = False) -> None:
        out = self._stream if self._stream is not None else sys.stderr
        if out is None:
            return

        total, downloaded, extracted = self._totals()
        if total <= 0:
            percent = 0
            text = f"Pulling {self._image}: preparing"
        else:
            # Downloading and extracting each count for half of the pull.
            percent = int(100 * (downloaded + extracted) / (2 * total))
            text = (
                f"Pulling {self._image}: {percent}% "
                f"(downloaded {format_bytes(downloaded)} / {format_bytes(total)}, "
                f"extracted {format_bytes(extracted)})"
            )

        if getattr(out, "isatty", lambda: False)():
            now = time.monotonic()
            if not final and now - self._last_draw_sec < self._min_interval_sec:
                return
            self._last_draw_sec = now
            text = text[: max(20, shutil.get_terminal_size().columns - 1)]
            padding = max(0, self._line_length - len(text))
            self._line_length = len(text)
            out.write(f"\r{text}{' ' * padding}")
            if final:
                out.write("\n")
        else:
            advanced = (
                self._last_percent is None
                or percent - self._last_percent >= self._step_percent
            )
            if not advanced and not (final and percent != self._last_percent):
                return
            self._last_percent = percent
            out.write(f"{text}\n")
        out.flush()


class RunProgress:
    """Render model-run status as a progress display.

    Reports phase messages (preparing, running with elapsed time, reading
    results) so a long ``container.wait`` does not look stalled. Interactive
    terminals rewrite a single line; non-TTY destinations get a new line every
    ``step_sec`` seconds while running.

    Parameters
    ----------
    stream :
        Destination for progress output. Defaults to :data:`sys.stderr`,
        looked up at write time.
    min_interval_sec :
        Smallest delay between redraws on an interactive terminal.
    step_sec :
        Elapsed-time increase that triggers a new line when the destination
        is not an interactive terminal.
    """

    def __init__(
        self,
        stream: TextIO | None = None,
        *,
        min_interval_sec: float = 0.2,
        step_sec: float = 5.0,
    ) -> None:
        self._stream = stream
        self._min_interval_sec = min_interval_sec
        self._step_sec = step_sec
        self._last_draw_sec = 0.0
        self._last_elapsed_reported: float | None = None
        self._line_length = 0
        self._text = ""
        self._closed = False

    def preparing(self) -> None:
        """Report that the container is being prepared."""
        self._set_text("Preparing Leman (2000) container")
        self._draw(force=True)

    def running(self, elapsed_sec: float) -> None:
        """Report that the model is running.

        Parameters
        ----------
        elapsed_sec :
            Seconds since the container started.
        """
        elapsed = max(0.0, float(elapsed_sec))
        text = f"Running Leman (2000) model: {elapsed:.0f}s"
        force = not self._text.startswith("Running Leman (2000) model:")
        self._set_text(text)
        self._draw(elapsed_sec=elapsed, force=force)

    def reading(self) -> None:
        """Report that model output is being copied out of the container."""
        self._set_text("Reading Leman (2000) results")
        self._draw(force=True)

    def close(self) -> None:
        """Finish the display, leaving the cursor on a fresh line."""
        if self._closed:
            return
        self._closed = True
        out = self._stream if self._stream is not None else sys.stderr
        if out is None:
            return
        # Non-TTY messages already end with a newline; only TTY needs a final
        # newline to leave the cursor below the rewritten status line.
        if getattr(out, "isatty", lambda: False)() and self._line_length > 0:
            out.write("\n")
            out.flush()
            self._line_length = 0

    def __enter__(self) -> RunProgress:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def _set_text(self, text: str) -> None:
        self._text = text

    def _draw(
        self,
        *,
        elapsed_sec: float | None = None,
        force: bool = False,
    ) -> None:
        out = self._stream if self._stream is not None else sys.stderr
        if out is None or not self._text or self._closed:
            return

        text = self._text
        if getattr(out, "isatty", lambda: False)():
            now = time.monotonic()
            if not force and now - self._last_draw_sec < self._min_interval_sec:
                return
            self._last_draw_sec = now
            text = text[: max(20, shutil.get_terminal_size().columns - 1)]
            padding = max(0, self._line_length - len(text))
            self._line_length = len(text)
            out.write(f"\r{text}{' ' * padding}")
        else:
            if not force:
                if elapsed_sec is None:
                    return
                last = self._last_elapsed_reported
                if last is not None and elapsed_sec - last < self._step_sec:
                    return
            if elapsed_sec is not None:
                self._last_elapsed_reported = elapsed_sec
            out.write(f"{text}\n")
        out.flush()
