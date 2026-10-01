"""Player state as the rest of the app sees it, independent of pyatv."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


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
