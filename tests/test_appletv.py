import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest
from pyatv.const import DeviceState, OperatingSystem, PairingRequirement, Protocol

from eyes_on_screen.appletv import controller as controller_module
from eyes_on_screen.appletv import pairing as pairing_module
from eyes_on_screen.appletv.controller import AppleTvController, AppleTvError
from eyes_on_screen.appletv.pairing import (
    REMOTE_NAME,
    PairingError,
    pair_device,
    pick_device,
)
from eyes_on_screen.appletv.state import Playback, PlayerState


def service(protocol, pairing=PairingRequirement.Mandatory, credentials=None):
    return SimpleNamespace(protocol=protocol, pairing=pairing, credentials=credentials)


def device(identifier, os=OperatingSystem.TvOS, services=()):
    services = list(services)
    return SimpleNamespace(
        identifier=identifier,
        all_identifiers=[identifier],
        name=f"device {identifier}",
        device_info=SimpleNamespace(operating_system=os),
        services=services,
        get_service=lambda protocol: next((s for s in services if s.protocol is protocol), None),
    )


class TestPickDevice:
    MAC = device("mac", os=OperatingSystem.MacOS)

    def test_explicit_identifier(self):
        tv = device("tv")

        assert pick_device([self.MAC, tv], "tv") is tv

    def test_unknown_identifier(self):
        with pytest.raises(PairingError, match="no device with identifier"):
            pick_device([self.MAC], "tv")

    def test_the_only_apple_tv_is_picked_automatically(self):
        tv = device("tv")

        assert pick_device([self.MAC, tv], None) is tv

    def test_no_apple_tv(self):
        with pytest.raises(PairingError, match="no Apple TV found"):
            pick_device([self.MAC], None)

    def test_several_apple_tvs_need_an_identifier(self):
        with pytest.raises(PairingError, match="--id"):
            pick_device([device("a"), device("b")], None)


class FakeHandler:
    device_provides_pin = True

    def __init__(self, succeeds: bool = True) -> None:
        self.succeeds = succeeds
        self.pins: list[str] = []
        self.closed = False

    async def begin(self) -> None:
        pass

    def pin(self, pin: str) -> None:
        self.pins.append(pin)

    async def finish(self) -> None:
        pass

    @property
    def has_paired(self) -> bool:
        return self.succeeds

    async def close(self) -> None:
        self.closed = True


class FakeStorage:
    def __init__(self) -> None:
        self.saves = 0

    async def save(self) -> None:
        self.saves += 1


@pytest.fixture
def fake_pair(monkeypatch):
    calls: list[tuple[Protocol, str]] = []
    handlers: list[FakeHandler] = []

    def install(succeeds: bool = True):
        async def pair(config, protocol, loop, storage, name):
            calls.append((protocol, name))
            handlers.append(FakeHandler(succeeds))
            return handlers[-1]

        monkeypatch.setattr(pairing_module.pyatv, "pair", pair)
        return calls, handlers

    return install


async def answer_pin(prompt: str) -> str:
    return "1234"


def test_pairs_airplay_and_companion_with_the_pin_and_saves_each(fake_pair):
    calls, handlers = fake_pair()
    tv = device(
        "tv",
        services=[service(Protocol.Companion), service(Protocol.AirPlay), service(Protocol.RAOP)],
    )
    storage = FakeStorage()

    asyncio.run(pair_device(tv, storage, answer_pin))

    assert calls == [(Protocol.AirPlay, REMOTE_NAME), (Protocol.Companion, REMOTE_NAME)]
    assert all(h.pins == ["1234"] and h.closed for h in handlers)
    assert storage.saves == 2


def test_already_paired_and_pairing_free_protocols_are_skipped(fake_pair):
    calls, _ = fake_pair()
    tv = device(
        "tv",
        services=[
            service(Protocol.AirPlay, credentials="stored"),
            service(Protocol.Companion, pairing=PairingRequirement.NotNeeded),
        ],
    )

    asyncio.run(pair_device(tv, FakeStorage(), answer_pin))

    assert calls == []


def test_failed_pairing_is_reported_and_cleaned_up(fake_pair):
    _, handlers = fake_pair(succeeds=False)
    storage = FakeStorage()

    with pytest.raises(PairingError, match="AirPlay failed"):
        asyncio.run(
            pair_device(device("tv", services=[service(Protocol.AirPlay)]), storage, answer_pin)
        )

    assert handlers[0].closed
    assert storage.saves == 0


def playing(state=DeviceState.Playing, title="Severance"):
    return SimpleNamespace(device_state=state, title=title)


class TestController:
    def make(self):
        seen: list[PlayerState | None] = []
        return AppleTvController("tv", Path("creds.conf"), on_state=seen.append), seen

    def test_push_updates_become_player_states_and_repeats_are_dropped(self):
        ctl, seen = self.make()

        ctl.playstatus_update(None, playing(DeviceState.Playing))
        ctl.playstatus_update(None, playing(DeviceState.Playing))
        ctl.playstatus_update(None, playing(DeviceState.Paused))

        assert [s.playback for s in seen] == [Playback.PLAYING, Playback.PAUSED]
        assert ctl.state == PlayerState(Playback.PAUSED, title="Severance")

    def test_unknown_device_state(self):
        ctl, _ = self.make()

        ctl.playstatus_update(None, playing(state=None))

        assert ctl.state.playback is Playback.UNKNOWN

    def test_connection_loss_clears_the_state(self):
        ctl, seen = self.make()
        ctl.playstatus_update(None, playing())

        ctl.connection_lost(OSError("wifi"))

        assert seen[-1] is None
        assert not ctl.connected

    def test_commands_need_a_connection(self):
        ctl, _ = self.make()

        with pytest.raises(AppleTvError, match="not connected"):
            asyncio.run(ctl.pause())

    def test_run_forever_retries_and_reconnects_after_a_loss(self, monkeypatch):
        monkeypatch.setattr(controller_module, "RECONNECT_DELAYS_S", (0,))
        ctl, _ = self.make()
        attempts = []

        async def connect():
            attempts.append(1)
            if len(attempts) <= 2:
                raise AppleTvError("asleep")
            ctl._lost = asyncio.Event()

        ctl.connect = connect

        async def scenario():
            task = asyncio.create_task(ctl.run_forever())
            while len(attempts) < 3:
                await asyncio.sleep(0.01)
            ctl.connection_lost(OSError("wifi"))
            while len(attempts) < 4:
                await asyncio.sleep(0.01)
            task.cancel()

        asyncio.run(asyncio.wait_for(scenario(), 5))

        assert len(attempts) == 4


def test_player_state_text():
    assert str(PlayerState(Playback.PAUSED, app="Kinopoisk", title="Film")) == (
        "paused (Kinopoisk - Film)"
    )
    assert str(PlayerState(Playback.IDLE)) == "idle"
