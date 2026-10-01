"""Apple TV control over pyatv: play/pause and live player state from push updates."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from pathlib import Path

import pyatv
from pyatv import exceptions
from pyatv.const import DeviceState
from pyatv.interface import AppleTV, DeviceListener, Playing, PushListener

from eyes_on_screen.appletv.pairing import load_storage, scan
from eyes_on_screen.appletv.state import Playback, PlayerState

log = logging.getLogger(__name__)

# Waits between reconnection attempts; the last one repeats. The Apple TV sleeps
# when the TV is off, so "unreachable" is a normal, long-lasting state.
RECONNECT_DELAYS_S = (2, 5, 10, 30, 60)

_PLAYBACK = {
    DeviceState.Playing: Playback.PLAYING,
    DeviceState.Paused: Playback.PAUSED,
    DeviceState.Idle: Playback.IDLE,
    DeviceState.Loading: Playback.LOADING,
    DeviceState.Stopped: Playback.STOPPED,
    DeviceState.Seeking: Playback.SEEKING,
}

StateCallback = Callable[[PlayerState | None], None]

_AUTH_ERRORS = (
    exceptions.AuthenticationError,
    exceptions.InvalidCredentialsError,
    exceptions.NoCredentialsError,
)
_CONNECTION_ERRORS = (
    exceptions.ConnectionFailedError,
    exceptions.ConnectionLostError,
    exceptions.OperationTimeoutError,
    exceptions.ProtocolError,
    exceptions.HttpError,
    OSError,
    TimeoutError,
)


class AppleTvError(Exception):
    """The Apple TV is unreachable or not paired. User-facing message."""


class AppleTvController(PushListener, DeviceListener):
    """One Apple TV: commands, plus the player state kept current by push updates.

    `on_state` gets every change, and None when the connection is lost. pyatv keeps
    listeners as weak references; the controller is its own listener, so it stays
    registered for as long as the controller lives.
    """

    def __init__(
        self,
        identifier: str,
        credentials_file: Path,
        on_state: StateCallback | None = None,
    ) -> None:
        self._identifier = identifier
        self._credentials_file = credentials_file
        self._on_state = on_state
        self._atv: AppleTV | None = None
        self._state: PlayerState | None = None
        self._lost: asyncio.Event | None = None
        self.name: str | None = None

    @property
    def connected(self) -> bool:
        return self._atv is not None

    @property
    def state(self) -> PlayerState | None:
        return self._state

    async def connect(self) -> None:
        storage = await load_storage(self._credentials_file)
        devices = await scan(storage, identifier=self._identifier)
        if not devices:
            raise AppleTvError(f"Apple TV {self._identifier} not found (asleep, off or offline?)")
        config = devices[0]
        if not any(service.credentials for service in config.services):
            raise AppleTvError(f"{config.name} is not paired yet: run `eos atv pair`")

        try:
            atv = await pyatv.connect(config, asyncio.get_running_loop(), storage=storage)
            self._atv = atv
            self._lost = asyncio.Event()
            self.name = config.name
            atv.listener = self
            initial = await atv.metadata.playing()
        except _AUTH_ERRORS as exc:
            await self.close()
            raise AppleTvError(
                f"{config.name} rejected the stored credentials, run `eos atv pair` again: {exc}"
            ) from exc
        except _CONNECTION_ERRORS as exc:
            await self.close()
            raise AppleTvError(f"cannot connect to {config.name}: {exc}") from exc

        atv.push_updater.listener = self
        atv.push_updater.start()
        log.info("Connected to Apple TV %s (%s)", config.name, config.address)
        self._set_state(self._convert(initial))

    async def run_forever(self) -> None:
        """Stay connected: connect, wait for a loss, reconnect with growing delays.

        Runs until cancelled.
        """
        attempt = 0
        while True:
            try:
                await self.connect()
            except AppleTvError as exc:
                delay = RECONNECT_DELAYS_S[min(attempt, len(RECONNECT_DELAYS_S) - 1)]
                attempt += 1
                # Loud once, then quiet: an Apple TV asleep for hours is normal.
                level = logging.WARNING if attempt == 1 else logging.DEBUG
                log.log(level, "Apple TV unavailable: %s; retrying in %ds", exc, delay)
                await asyncio.sleep(delay)
                continue
            attempt = 0
            assert self._lost is not None
            await self._lost.wait()

    async def play(self) -> None:
        await self._require().remote_control.play()

    async def pause(self) -> None:
        await self._require().remote_control.pause()

    async def close(self) -> None:
        atv, self._atv = self._atv, None
        if atv is not None:
            if atv.push_updater.active:
                atv.push_updater.stop()
            await asyncio.gather(*atv.close())

    # PushListener

    def playstatus_update(self, updater: object, playstatus: Playing) -> None:
        self._set_state(self._convert(playstatus))

    def playstatus_error(self, updater: object, exception: Exception) -> None:
        log.warning("Apple TV push updates failed: %s", exception)

    # DeviceListener

    def connection_lost(self, exception: Exception) -> None:
        log.warning("Lost connection to Apple TV: %s", exception)
        self._on_disconnect()

    def connection_closed(self) -> None:
        self._on_disconnect()

    def _on_disconnect(self) -> None:
        self._atv = None
        self._set_state(None)
        if self._lost is not None:
            self._lost.set()

    def _require(self) -> AppleTV:
        if self._atv is None:
            raise AppleTvError("not connected to the Apple TV")
        return self._atv

    def _convert(self, playing: Playing) -> PlayerState:
        return PlayerState(
            playback=_PLAYBACK.get(playing.device_state, Playback.UNKNOWN),
            app=self._current_app(),
            title=playing.title,
        )

    def _current_app(self) -> str | None:
        if self._atv is None:
            return None
        try:
            app = self._atv.metadata.app
        except exceptions.NotSupportedError:
            # Only available while something plays.
            return None
        return app.name if app else None

    def _set_state(self, state: PlayerState | None) -> None:
        if state == self._state:
            return
        self._state = state
        if self._on_state is not None:
            self._on_state(state)
