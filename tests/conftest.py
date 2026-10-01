import pytest


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
