"""When to pause and resume: hysteresis timers plus ownership of the pause.

Pure logic: the current time comes in as an argument, so tests drive it with fake time.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import StrEnum

from eyes_on_screen.appletv.state import Playback, PlayerState
from eyes_on_screen.attention.classifier import Attention
from eyes_on_screen.config import BehaviorConfig, FaceLostAction
from eyes_on_screen.logging_setup import EVENTS_LOGGER

events = logging.getLogger(EVENTS_LOGGER)

# A command the Apple TV has not confirmed by then is considered lost and may be resent.
COMMAND_TIMEOUT_S = 3.0
# Observations further apart than this (stream stalled or reconnecting) restart the
# timers: a gap in the video is not evidence that the viewer kept looking away.
MAX_OBSERVATION_GAP_S = 2.0
# Playing after one of these was a person's doing. Playing after LOADING or SEEKING is
# just the player moving on (next episode autoplay, scrubbing) and changes nothing.
_DELIBERATE_START_FROM = {Playback.PAUSED, Playback.STOPPED, Playback.IDLE}


class Command(StrEnum):
    PAUSE = "pause"
    RESUME = "resume"


@dataclass(frozen=True, slots=True)
class Decision:
    command: Command
    reason: str


@dataclass(frozen=True, slots=True)
class MachineStatus:
    """Snapshot for debug views."""

    attention: Attention | None
    streak_s: float
    """How long the current attention value has lasted."""
    playback: Playback | None
    player_connected: bool
    paused_by_us: bool
    armed: bool
    pending: Command | None


class PlaybackStateMachine:
    """Turns attention observations and player updates into pause/resume decisions.

    Rules:
    - Pause while playing once the room looked away for `pause_after_s`, or had no
      viewer for `face_lost_after_s` when `on_face_lost` is `pause`.
    - Resume only a pause we made, once the room looked at the screen for
      `resume_after_s`. A pause from the remote or an app is never touched.
    - After someone else starts playback, stay passive until a viewer is seen looking
      at the screen. Otherwise starting a show and walking off to listen from the
      kitchen would be paused right away.
    """

    def __init__(self, behavior: BehaviorConfig) -> None:
        self._behavior = behavior
        self._attention: Attention | None = None
        self._since = 0.0
        self._last_observation: float | None = None
        self._playback: Playback | None = None
        self._player_connected = False
        self._paused_by_us = False
        self._armed = True
        self._pending: tuple[Command, float] | None = None

    def observe(self, attention: Attention, now: float) -> Decision | None:
        """Feed one analysed frame; returns a command to send, if it is time for one."""
        gap = None if self._last_observation is None else now - self._last_observation
        if gap is None or gap > MAX_OBSERVATION_GAP_S or attention is not self._attention:
            self._attention = attention
            self._since = now
        self._last_observation = now
        if attention is Attention.LOOKING:
            self._armed = True

        self._expire_pending(now)
        if self._pending is not None or not self._player_connected:
            return None
        return self._decide(attention, now - self._since, now)

    def player_changed(self, state: PlayerState | None, now: float) -> None:
        """Feed a player update; None means the Apple TV connection is gone."""
        if state is None:
            # Keep the last known playback: after a reconnect the same state comes
            # back and must not look like someone else's action.
            self._player_connected = False
            return
        self._player_connected = True
        previous, self._playback = self._playback, state.playback
        pending = self._pending[0] if self._pending else None

        if state.playback is Playback.PAUSED:
            if pending is Command.PAUSE:
                self._paused_by_us = True
                self._pending = None
            elif previous is not Playback.PAUSED:
                if self._paused_by_us or previous is not None:
                    events.info("paused by someone else: will not resume it")
                self._paused_by_us = False
        elif state.playback is Playback.PLAYING:
            if pending is Command.RESUME:
                self._pending = None
            elif previous in _DELIBERATE_START_FROM:
                events.info("playback started by someone else: waiting for a viewer to look")
                self._armed = False
            self._paused_by_us = False
        elif previous is Playback.PAUSED and self._paused_by_us:
            # Stopped, idle, another app...: our pause is over either way.
            self._paused_by_us = False

    def status(self, now: float) -> MachineStatus:
        return MachineStatus(
            attention=self._attention,
            streak_s=now - self._since if self._attention is not None else 0.0,
            playback=self._playback,
            player_connected=self._player_connected,
            paused_by_us=self._paused_by_us,
            armed=self._armed,
            pending=self._pending[0] if self._pending else None,
        )

    def _decide(self, attention: Attention, streak: float, now: float) -> Decision | None:
        behavior = self._behavior
        if self._playback is Playback.PLAYING and self._armed:
            if attention is Attention.AWAY and streak >= behavior.pause_after_s:
                return self._send(Command.PAUSE, f"looked away for {streak:.1f}s", now)
            if (
                attention is Attention.ABSENT
                and behavior.on_face_lost is FaceLostAction.PAUSE
                and streak >= behavior.face_lost_after_s
            ):
                return self._send(Command.PAUSE, f"no viewer for {streak:.1f}s", now)
        if (
            self._playback is Playback.PAUSED
            and self._paused_by_us
            and attention is Attention.LOOKING
            and streak >= behavior.resume_after_s
        ):
            return self._send(Command.RESUME, f"looking at the screen for {streak:.1f}s", now)
        return None

    def _send(self, command: Command, reason: str, now: float) -> Decision:
        self._pending = (command, now)
        return Decision(command, reason)

    def _expire_pending(self, now: float) -> None:
        if self._pending is not None and now - self._pending[1] > COMMAND_TIMEOUT_S:
            events.warning("%s was not confirmed by the Apple TV; may retry", self._pending[0])
            self._pending = None
