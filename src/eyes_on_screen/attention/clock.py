"""Time source abstraction, so the state machine can be tested with a fake clock."""

from __future__ import annotations

import time
from typing import Protocol


class Clock(Protocol):
    def now(self) -> float:
        """Seconds since an arbitrary fixed point; never goes backwards."""


class MonotonicClock:
    """Real clock; same time base as `Frame.timestamp`."""

    def now(self) -> float:
        return time.monotonic()
