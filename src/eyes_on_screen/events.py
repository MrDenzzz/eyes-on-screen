"""What eos did and why: the events log.

Every event is a line of English for logs/events.log, plus a code and parameters that
the web UI turns into a sentence in the viewer's language.
"""

from __future__ import annotations

import logging

from eyes_on_screen.logging_setup import EVENTS_LOGGER

Param = str | int | float | bool | None

_log = logging.getLogger(EVENTS_LOGGER)


def emit(
    code: str,
    message: str,
    *args: object,
    level: int = logging.INFO,
    params: dict[str, Param] | None = None,
) -> None:
    """Log `message % args` as event `code`; `params` carry its values for the web UI."""
    _log.log(level, message, *args, extra={"event": code, "params": params or {}})


def event_of(record: logging.LogRecord) -> tuple[str, dict[str, Param]]:
    """The code and parameters of a logged event; "other" for a plain log line."""
    return getattr(record, "event", "other"), getattr(record, "params", {})
