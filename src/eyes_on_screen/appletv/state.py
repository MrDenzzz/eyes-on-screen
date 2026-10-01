"""The player as the rest of the app sees it, independent of pyatv."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol


class Playback(StrEnum):
    PLAYING = "playing"
    PAUSED = "paused"
    IDLE = "idle"
    LOADING = "loading"
    STOPPED = "stopped"
    SEEKING = "seeking"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class PlayerState:
    playback: Playback
    app: str | None = None
    title: str | None = None

    def __str__(self) -> str:
        details = " - ".join(part for part in (self.app, self.title) if part)
        return f"{self.playback.value} ({details})" if details else self.playback.value


class AppleTvError(Exception):
    """The Apple TV is unreachable or not paired. User-facing message."""


StateCallback = Callable[[PlayerState | None], None]


class Player(Protocol):
    """A media player the app pauses and resumes; AppleTvController is the real one.

    `on_state` gets every change of the player state, and None when the connection is
    lost. Commands raise AppleTvError while the player is unreachable.
    """

    name: str | None
    on_state: StateCallback | None

    @property
    def connected(self) -> bool: ...

    @property
    def state(self) -> PlayerState | None: ...

    async def run_forever(self) -> None:
        """Stay connected, reconnecting as needed, until cancelled."""
        ...

    async def play(self) -> None: ...

    async def pause(self) -> None: ...

    async def close(self) -> None: ...
