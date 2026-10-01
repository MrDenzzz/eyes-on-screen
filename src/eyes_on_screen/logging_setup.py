"""Logging: console output for the app plus a separate file for pause/resume events."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from eyes_on_screen.config import LoggingConfig

PACKAGE_LOGGER = "eyes_on_screen"
# Pause/resume decisions and their reasons go here; they are also mirrored to the console.
EVENTS_LOGGER = "eyes_on_screen.events"

_CONSOLE_FORMAT = "%(asctime)s.%(msecs)03d %(levelname)-7s %(name)s: %(message)s"
_EVENTS_FORMAT = "%(asctime)s %(message)s"


def setup_logging(config: LoggingConfig, *, verbose: bool = False) -> None:
    """Configure logging once at process start."""
    console = logging.StreamHandler()
    console.setFormatter(logging.Formatter(_CONSOLE_FORMAT, datefmt="%H:%M:%S"))

    root = logging.getLogger()
    root.addHandler(console)
    # Third-party libraries (pyatv, zeroconf, asyncio) only get to report problems.
    root.setLevel(logging.WARNING)
    logging.getLogger(PACKAGE_LOGGER).setLevel(logging.DEBUG if verbose else config.level)

    events = logging.getLogger(EVENTS_LOGGER)
    # Events are the point of the app: keep them even when the console level is WARNING.
    events.setLevel(logging.INFO)
    if config.events_file is not None:
        config.events_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            config.events_file, maxBytes=1_000_000, backupCount=3, encoding="utf-8"
        )
        file_handler.setFormatter(logging.Formatter(_EVENTS_FORMAT))
        events.addHandler(file_handler)
