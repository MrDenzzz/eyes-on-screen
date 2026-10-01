import asyncio

import pytest

from eyes_on_screen.appletv.state import Playback, PlayerState


class FakeClock:
    """Manually advanced time, in seconds; implements attention.clock.Clock."""

    def __init__(self, start: float = 1000.0) -> None:
        self._now = start

    def now(self) -> float:
        return self._now

    def advance(self, seconds: float) -> float:
        self._now += seconds
        return self._now


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


class FakePlayer:
    """An Apple TV that plays until told otherwise; commands are confirmed at once, the
    way push updates confirm them on the real one."""

    def __init__(self) -> None:
        self.name = "Test TV"
        self.on_state = None
        self.connected = False
        self.state: PlayerState | None = None
        self.commands: list[str] = []

    async def run_forever(self) -> None:
        self.connected = True
        self._set(Playback.PLAYING)
        await asyncio.Event().wait()

    async def play(self) -> None:
        self.commands.append("play")
        self._set(Playback.PLAYING)

    async def pause(self) -> None:
        self.commands.append("pause")
        self._set(Playback.PAUSED)

    async def close(self) -> None:
        self.connected = False

    def _set(self, playback: Playback) -> None:
        self.state = PlayerState(playback, app="TV", title="Show")
        if self.on_state:
            self.on_state(self.state)


@pytest.fixture
def player() -> FakePlayer:
    return FakePlayer()
