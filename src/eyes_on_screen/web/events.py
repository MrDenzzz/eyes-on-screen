"""The events log, copied to the web UI's event feed."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from typing import Literal

from eyes_on_screen.web.messages import EventInfo
from eyes_on_screen.web.server import WebServer

EventKind = Literal["pause", "resume", "player", "calibration", "other"]

_KINDS: tuple[tuple[str, EventKind], ...] = (
    ("paused", "pause"),
    ("would pause", "pause"),
    ("resumed", "resume"),
    ("would resume", "resume"),
    ("player:", "player"),
    ("calibrat", "calibration"),
)


def event_kind(text: str) -> EventKind:
    return next((kind for prefix, kind in _KINDS if text.startswith(prefix)), "other")


class EventForwarder(logging.Handler):
    """Copies event log records to the web UI (from whatever thread logs them)."""

    def __init__(self, web: WebServer, loop: asyncio.AbstractEventLoop) -> None:
        super().__init__(level=logging.INFO)
        self._web = web
        self._loop = loop

    def emit(self, record: logging.LogRecord) -> None:
        text = record.getMessage()
        event = EventInfo(
            ts=round(record.created * 1000),
            time=time.strftime("%H:%M:%S", time.localtime(record.created)),
            level="warning" if record.levelno >= logging.WARNING else "info",
            kind=event_kind(text),
            text=text,
        )
        with contextlib.suppress(RuntimeError):  # loop already closed at shutdown
            self._loop.call_soon_threadsafe(self._web.publish_event, event)
