"""Contract shared by all video sources."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import numpy as np


@dataclass(frozen=True, slots=True)
class Frame:
    image: np.ndarray
    """BGR uint8 array of shape (H, W, 3), OpenCV convention."""
    timestamp: float
    """time.monotonic() when the frame was read from the stream."""
    seq: int
    """Frame number since the source started; keeps growing across reconnects."""


@dataclass(frozen=True, slots=True)
class SourceStats:
    description: str
    """Human-readable source name, safe to log (credentials removed)."""
    connected: bool
    width: int | None
    height: int | None
    codec: str | None
    fps: float
    """Measured incoming frame rate; 0 when frames stopped arriving."""
    frames: int
    reconnects: int
    """How many times an established stream was lost."""
    last_error: str | None


class VideoSource(Protocol):
    """Grabs frames in the background and hands out only the freshest one.

    The stream runs faster than the ~10 fps we analyse, so implementations must drop
    stale frames rather than queue them: a queue turns into seconds of latency, and
    the pause would fire long after the viewer looked away.
    """

    def start(self) -> None:
        """Start capturing in the background; reconnect on its own if the stream drops."""

    def stop(self) -> None:
        """Stop capturing and release the stream or device."""

    def wait_for_frame(self, newer_than: int, timeout: float) -> Frame | None:
        """Return the newest frame with `seq > newer_than`, waiting up to `timeout` seconds.

        Returns None if nothing newer arrived in time (stream stalled or reconnecting).
        Pass -1 to get whatever frame is available.
        """

    def stats(self) -> SourceStats:
        """Snapshot of the stream health, cheap enough to call on every frame."""
