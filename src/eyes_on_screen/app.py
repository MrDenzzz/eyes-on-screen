"""`eos run`: camera -> faces -> room attention -> state machine -> Apple TV."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor

import cv2
import numpy as np

from eyes_on_screen.appletv.controller import AppleTvController
from eyes_on_screen.appletv.state import PlayerState
from eyes_on_screen.attention.classifier import classify
from eyes_on_screen.attention.state_machine import Command, Decision, PlaybackStateMachine
from eyes_on_screen.attention.viewers import RoomAttention, ViewerFilter, room_attention
from eyes_on_screen.config import AppConfig
from eyes_on_screen.debug.overlay import HIGHLIGHT, MUTED, TEXT, Line, View, rate, render
from eyes_on_screen.logging_setup import EVENTS_LOGGER
from eyes_on_screen.video.source import Frame, VideoSource
from eyes_on_screen.vision.analyzer import FaceAnalyzer, FaceObservation
from eyes_on_screen.vision.target import select_target

log = logging.getLogger(__name__)
events = logging.getLogger(EVENTS_LOGGER)

WINDOW = "eyes-on-screen"
_FRAME_WAIT_S = 0.5
_KEY_ESC = 27


class App:
    def __init__(
        self,
        config: AppConfig,
        source: VideoSource,
        analyzer: FaceAnalyzer,
        *,
        dry_run: bool = False,
        debug: bool = False,
    ) -> None:
        identifier = config.apple_tv.identifier
        if identifier is None:
            raise ValueError("apple_tv.identifier is required")
        self._config = config
        self._source = source
        self._analyzer = analyzer
        self._dry_run = dry_run
        self._debug = debug
        self._machine = PlaybackStateMachine(config.behavior)
        self._viewers = ViewerFilter()
        self._player = AppleTvController(
            identifier, config.apple_tv.credentials_file, on_state=self._on_player
        )
        # MediaPipe and OpenCV work stays on one dedicated thread, off the event loop
        # that serves the Apple TV connection.
        self._worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="analysis")
        self._room: RoomAttention | None = None
        self._analysis_times: deque[float] = deque(maxlen=20)

    async def run(self) -> None:
        """Run until cancelled (Ctrl+C) or, in debug mode, until the window is closed."""
        events.info("started%s", " (dry run: commands are only logged)" if self._dry_run else "")
        player_task = asyncio.create_task(self._player.run_forever(), name="apple-tv")
        if self._debug:
            cv2.namedWindow(WINDOW, cv2.WINDOW_NORMAL)
        try:
            await self._analysis_loop()
        finally:
            player_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await player_task
            await self._player.close()
            self._worker.shutdown(wait=True)
            if self._debug:
                cv2.destroyWindow(WINDOW)
            events.info("stopped")

    async def _analysis_loop(self) -> None:
        loop = asyncio.get_running_loop()
        period = 1.0 / self._config.video.process_fps
        next_tick = time.monotonic()
        seq = -1
        while True:
            delay = next_tick - time.monotonic()
            if delay > 0:
                await asyncio.sleep(delay)
            next_tick = max(next_tick + period, time.monotonic())

            frame = await loop.run_in_executor(
                self._worker, self._source.wait_for_frame, seq, _FRAME_WAIT_S
            )
            if frame is not None:
                seq = frame.seq
                started = time.perf_counter()
                faces = await loop.run_in_executor(
                    self._worker, self._analyzer.analyze, frame.image
                )
                analysis_ms = (time.perf_counter() - started) * 1000
                self._analysis_times.append(time.monotonic())
                await self._observe(frame, faces, analysis_ms)
            if self._debug and not self._poll_window():
                return

    async def _observe(
        self, frame: Frame, faces: list[FaceObservation], analysis_ms: float
    ) -> None:
        pose = self._config.pose
        viewers = self._viewers.viewers(faces, frame.timestamp)
        room = room_attention(viewers, pose, self._config.behavior.multiple_viewers)
        if self._room is None or room.attention is not self._room.attention:
            log.debug(
                "Room: %s (%d viewers, %d looking)", room.attention, room.viewers, room.looking
            )
        self._room = room

        decision = self._machine.observe(room.attention, frame.timestamp)
        if decision is not None:
            await self._execute(decision)

        if self._debug:
            states = [classify(face, pose) if face in viewers else None for face in faces]
            focus = select_target(viewers)
            view = View(frame.image, faces, states, room.attention, focus, analysis_ms)
            cv2.imshow(WINDOW, self._render(view))

    async def _execute(self, decision: Decision) -> None:
        if self._dry_run:
            events.info("would %s: %s", decision.command.value, decision.reason)
            return
        try:
            if decision.command is Command.PAUSE:
                await self._player.pause()
            else:
                await self._player.play()
        except Exception as exc:  # network trouble must not stop the app
            # The state machine resends once the command times out unconfirmed.
            events.warning("%s failed: %s", decision.command.value, exc)
            return
        verb = "paused" if decision.command is Command.PAUSE else "resumed"
        events.info("%s: %s", verb, decision.reason)

    def _on_player(self, state: PlayerState | None) -> None:
        events.info("player: %s", state or "disconnected")
        self._machine.player_changed(state, time.monotonic())

    def _render(self, view: View) -> np.ndarray:
        status = self._machine.status(time.monotonic())
        room = self._room
        behavior = self._config.behavior
        player = self._player.state
        footer: list[Line] = [
            (
                f"viewers {room.viewers if room else 0}, looking {room.looking if room else 0}"
                f"  ({behavior.multiple_viewers.value}),  {view.attention.value} for "
                f"{status.streak_s:.1f}s  (pause after {behavior.pause_after_s:.1f}s, "
                f"resume after {behavior.resume_after_s:.1f}s)",
                TEXT,
                0.5,
            ),
            (f"Apple TV: {player if player else 'not connected'}", TEXT, 0.5),
            (
                f"paused by us: {'yes' if status.paused_by_us else 'no'}   "
                f"armed: {'yes' if status.armed else 'no (waiting for a look)'}   "
                f"pending: {status.pending.value if status.pending else '-'}",
                MUTED,
                0.45,
            ),
        ]
        if self._dry_run:
            footer.append(("DRY RUN: commands are only logged", HIGHLIGHT, 0.5))
        footer.append(("q: quit", MUTED, 0.45))
        fps = rate(self._analysis_times, time.monotonic())
        return render(
            view, self._config.pose, self._config.target.roi, self._source.stats(), fps, footer
        )

    def _poll_window(self) -> bool:
        """Pump the debug window; False once the user asked to quit."""
        key = cv2.waitKey(1) & 0xFF
        if key in (ord("q"), _KEY_ESC):
            return False
        return cv2.getWindowProperty(WINDOW, cv2.WND_PROP_VISIBLE) >= 1
