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
    """Frame counter since the source started; increases by one per decoded frame."""


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

    def next_frame(self, timeout: float) -> Frame | None:
        """Return the newest frame not returned before, waiting up to `timeout` seconds.

        Returns None if nothing new arrived in time (stream stalled or reconnecting).
        """

    @property
    def connected(self) -> bool:
        """Whether the stream is currently open and delivering frames."""
