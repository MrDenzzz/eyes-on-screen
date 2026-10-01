"""The events log, copied to the web UI's event feed."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from typing import Literal

from eyes_on_screen.events import event_of
from eyes_on_screen.web.messages import EventInfo
from eyes_on_screen.web.server import WebServer

EventKind = Literal["pause", "resume", "player", "calibration", "other"]

# Pause and resume are eos's own commands (they get markers on the attention timeline);
# a pause from the remote is a player event.
_KINDS: dict[str, EventKind] = {
    "paused": "pause",
    "would_pause": "pause",
    "resumed": "resume",
    "would_resume": "resume",
    "player": "player",
    "player_lost": "player",
    "paused_elsewhere": "player",
    "started_elsewhere": "player",
    "calibrated": "calibration",
    "calibration_failed": "calibration",
}


class EventForwarder(logging.Handler):
    """Copies event log records to the web UI (from whatever thread logs them)."""

    def __init__(self, web: WebServer, loop: asyncio.AbstractEventLoop) -> None:
        super().__init__(level=logging.INFO)
        self._web = web
        self._loop = loop

    def emit(self, record: logging.LogRecord) -> None:
        code, params = event_of(record)
        event = EventInfo(
            ts=round(record.created * 1000),
            time=time.strftime("%H:%M:%S", time.localtime(record.created)),
            level="warning" if record.levelno >= logging.WARNING else "info",
            kind=_KINDS.get(code, "other"),
            code=code,
            params=params,
            text=record.getMessage(),
        )
        with contextlib.suppress(RuntimeError):  # loop already closed at shutdown
            self._loop.call_soon_threadsafe(self._web.publish_event, event)
