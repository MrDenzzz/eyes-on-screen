"""`eos run`: camera -> faces -> room attention -> state machine -> Apple TV, plus the web UI."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Literal

import cv2
import numpy as np

from eyes_on_screen.appletv.controller import AppleTvController
from eyes_on_screen.appletv.state import PlayerState
from eyes_on_screen.attention.calibration import (
    CalibrationError,
    CalibrationSession,
    calibrate_center,
)
from eyes_on_screen.attention.classifier import Attention, classify
from eyes_on_screen.attention.state_machine import Decision, PlaybackCommand, PlaybackStateMachine
from eyes_on_screen.attention.viewers import RoomAttention, ViewerFilter, room_attention
from eyes_on_screen.config import AppConfig
from eyes_on_screen.debug.overlay import HIGHLIGHT, MUTED, TEXT, Line, View, rate, render
from eyes_on_screen.logging_setup import EVENTS_LOGGER
from eyes_on_screen.settings import Changes, SettingsError, apply_changes, save_changes
from eyes_on_screen.video.source import Frame, VideoSource
from eyes_on_screen.vision.analyzer import FaceAnalyzer, FaceObservation
from eyes_on_screen.vision.target import select_target
from eyes_on_screen.web.messages import (
    AnalysisInfo,
    AutomationInfo,
    CalibrationInfo,
    EventInfo,
    FaceInfo,
    FrameHeader,
    MachineInfo,
    PlayerInfo,
    RoomInfo,
    SettingsChanges,
    SettingsInfo,
    StatusMessage,
    StreamInfo,
)
from eyes_on_screen.web.protocol import encode_frame
from eyes_on_screen.web.server import WebServer

log = logging.getLogger(__name__)
events = logging.getLogger(EVENTS_LOGGER)

WINDOW = "eyes-on-screen"
# From the web UI the viewer already holds the device: a short countdown is enough.
WEB_CALIBRATION_DELAY_S = 3.0
CALIBRATION_DURATION_S = 2.0
_FRAME_WAIT_S = 0.5
EventKind = Literal["pause", "resume", "player", "calibration", "other"]
_KEY_ESC = 27


class App:
    def __init__(
        self,
        config: AppConfig,
        config_path: Path,
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
        self._config_path = config_path
        self._source = source
        self._analyzer = analyzer
        self._dry_run = dry_run
        self._debug = debug
        self._automation = True
        self._machine = PlaybackStateMachine(config.behavior)
        self._viewers = ViewerFilter()
        self._player = AppleTvController(
            identifier, config.apple_tv.credentials_file, on_state=self._on_player
        )
        self._web = WebServer(config.web, self) if config.web.enabled else None
        # MediaPipe and OpenCV work stays on one dedicated thread, off the event loop
        # that serves the Apple TV connection and the web UI.
        self._worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="analysis")
        self._room = RoomAttention(Attention.ABSENT, viewers=0, looking=0)
        self._analysis_times: deque[float] = deque(maxlen=20)
        self._analysis_ms = 0.0
        self._calibration: CalibrationSession | None = None

    async def run(self) -> None:
        """Run until cancelled (Ctrl+C) or, in debug mode, until the window is closed."""
        events.info("started%s", " (dry run: commands are only logged)" if self._dry_run else "")
        forwarder = await self._start_web()
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
            if self._web is not None:
                events.removeHandler(forwarder)
                await self._web.stop()

    async def _start_web(self) -> logging.Handler | None:
        if self._web is None:
            return None
        try:
            await self._web.start()
        except OSError as exc:
            log.error("Web UI disabled: cannot listen on %s: %s", self._web.url, exc)
            self._web = None
            return None
        forwarder = _EventForwarder(self._web, asyncio.get_running_loop())
        events.addHandler(forwarder)
        log.info("Web UI: %s", self._web.url)
        return forwarder

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
                self._analysis_ms = (time.perf_counter() - started) * 1000
                self._analysis_times.append(time.monotonic())
                await self._observe(frame, faces)
            if self._web is not None:
                self._web.publish_status(self._status())
            if self._debug and not self._poll_window():
                return

    async def _observe(self, frame: Frame, faces: list[FaceObservation]) -> None:
        now = frame.timestamp
        pose = self._config.pose
        viewers = self._viewers.viewers(faces, now)
        room = room_attention(viewers, pose, self._config.behavior.multiple_viewers)
        if room.attention is not self._room.attention:
            log.debug(
                "Room: %s (%d viewers, %d looking)", room.attention, room.viewers, room.looking
            )
        self._room = room
        focus = select_target(viewers)

        if self._calibration is not None:
            self._calibration.add(now, focus.pose if focus else None)
            if self._calibration.finished(now):
                self._finish_calibration()

        if self._automation:
            decision = self._machine.observe(room.attention, now)
            if decision is not None:
                await self._execute(decision)

        states: list[Attention | None] = [
            classify(face, pose) if face in viewers else None for face in faces
        ]
        if self._web is not None and self._web.has_clients:
            await self._publish_frame(frame, faces, states, focus)
        if self._debug:
            view = View(frame.image, faces, states, room.attention, focus, self._analysis_ms)
            cv2.imshow(WINDOW, self._render(view))

    async def _execute(self, decision: Decision) -> None:
        if self._dry_run:
            events.info("would %s: %s", decision.command.value, decision.reason)
            return
        try:
            if decision.command is PlaybackCommand.PAUSE:
                await self._player.pause()
            else:
                await self._player.play()
        except Exception as exc:  # network trouble must not stop the app
            # The state machine resends once the command times out unconfirmed.
            events.warning("%s failed: %s", decision.command.value, exc)
            return
        verb = "paused" if decision.command is PlaybackCommand.PAUSE else "resumed"
        events.info("%s: %s", verb, decision.reason)

    def _on_player(self, state: PlayerState | None) -> None:
        events.info("player: %s", state or "disconnected")
        self._machine.player_changed(state, time.monotonic())

    # Settings and calibration

    def _change_settings(self, changes: Changes) -> None:
        """Validate, persist to config.yaml, and apply to the running app."""
        updated = apply_changes(self._config, changes)
        save_changes(self._config_path, updated, changes)
        self._config = updated
        self._analyzer.roi = updated.target.roi
        self._machine.behavior = updated.behavior

    def _finish_calibration(self) -> None:
        assert self._calibration is not None
        poses, self._calibration = self._calibration.poses, None
        try:
            centre = calibrate_center(poses, self._config.pose)
            self._change_settings(
                {
                    "pose": {
                        "yaw_center_deg": centre.yaw_center_deg,
                        "pitch_center_deg": centre.pitch_center_deg,
                    }
                }
            )
        except (CalibrationError, SettingsError, OSError) as exc:
            events.warning("calibration failed: %s", exc)
            return
        events.info(
            "calibrated: screen at yaw %+.1f, pitch %+.1f (from %d poses)",
            centre.yaw_center_deg,
            centre.pitch_center_deg,
            len(poses),
        )

    # Web UI

    # Controls for the web UI (see web/server.py)

    def status(self) -> StatusMessage:
        return self._status()

    def change_settings(self, changes: SettingsChanges) -> SettingsInfo:
        """Validate, persist to config.yaml and apply live; raises SettingsError."""
        as_dict = changes.as_changes()
        try:
            self._change_settings(as_dict)
        except OSError as exc:
            raise SettingsError(f"cannot save {self._config_path}: {exc}") from exc
        summary = ", ".join(f"{s}.{k}" for s, values in as_dict.items() for k in values)
        log.info("Settings changed from the web UI: %s", summary)
        return self._settings_info()

    def start_calibration(self) -> None:
        self._calibration = CalibrationSession(
            time.monotonic(), WEB_CALIBRATION_DELAY_S, CALIBRATION_DURATION_S
        )

    def set_automation(self, enabled: bool) -> AutomationInfo:
        if enabled != self._automation:
            self._automation = enabled
            events.info("automation %s from the web UI", "on" if enabled else "off")
        return AutomationInfo(enabled=self._automation, dry_run=self._dry_run)

    async def press(self, action: Literal["play", "pause"]) -> None:
        await (self._player.play() if action == "play" else self._player.pause())
        events.info("%s pressed in the web UI", action)

    def _settings_info(self) -> SettingsInfo:
        config = self._config
        return SettingsInfo(roi=config.target.roi, pose=config.pose, behavior=config.behavior)

    async def _publish_frame(
        self,
        frame: Frame,
        faces: list[FaceObservation],
        states: list[Attention | None],
        focus: FaceObservation | None,
    ) -> None:
        assert self._web is not None
        header = FrameHeader(
            seq=frame.seq,
            # Wall-clock milliseconds, the same clock as the events' timestamps.
            ts=round((time.time() - (time.monotonic() - frame.timestamp)) * 1000),
            attention=self._room.attention,
            faces=[
                _face_info(face, state, face is focus)
                for face, state in zip(faces, states, strict=True)
            ],
        ).model_dump(mode="json")
        web = self._config.web
        packet = await asyncio.get_running_loop().run_in_executor(
            self._worker,
            lambda: encode_frame(
                frame.image, header, max_width=web.max_width, quality=web.jpeg_quality
            ),
        )
        self._web.publish_frame(packet)

    def _status(self) -> StatusMessage:
        now = time.monotonic()
        stats = self._source.stats()
        machine = self._machine.status(now)
        player = self._player.state
        calibration = self._calibration
        return StatusMessage(
            stream=StreamInfo(
                connected=stats.connected,
                width=stats.width,
                height=stats.height,
                fps=round(stats.fps, 1),
                error=stats.last_error,
            ),
            analysis=AnalysisInfo(
                fps=round(rate(self._analysis_times, now), 1), ms=round(self._analysis_ms, 1)
            ),
            player=PlayerInfo(
                connected=self._player.connected,
                name=self._player.name,
                playback=player.playback if player else None,
                app=player.app if player else None,
                title=player.title if player else None,
            ),
            room=RoomInfo(
                attention=self._room.attention,
                viewers=self._room.viewers,
                looking=self._room.looking,
            ),
            machine=MachineInfo(
                streak_s=round(machine.streak_s, 2),
                paused_by_us=machine.paused_by_us,
                armed=machine.armed,
                pending=machine.pending,
            ),
            automation=AutomationInfo(enabled=self._automation, dry_run=self._dry_run),
            calibration=None
            if calibration is None
            else CalibrationInfo(
                phase="countdown" if calibration.counting_down(now) else "collecting",
                remaining_s=round(calibration.remaining_s(now), 2),
                phase_s=calibration.delay_s
                if calibration.counting_down(now)
                else calibration.duration_s,
            ),
            settings=self._settings_info(),
        )

    # Debug window

    def _render(self, view: View) -> np.ndarray:
        status = self._machine.status(time.monotonic())
        room = self._room
        behavior = self._config.behavior
        player = self._player.state
        footer: list[Line] = [
            (
                f"viewers {room.viewers}, looking {room.looking}"
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
        if not self._automation:
            footer.append(("AUTOMATION OFF (web UI)", HIGHLIGHT, 0.5))
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


def _face_info(face: FaceObservation, state: Attention | None, focus: bool) -> FaceInfo:
    return FaceInfo(
        box=(
            round(face.box[0], 4),
            round(face.box[1], 4),
            round(face.box[2], 4),
            round(face.box[3], 4),
        ),
        state=state.value if state is not None else "ignored",
        yaw=round(face.pose.yaw, 1) if face.pose else None,
        pitch=round(face.pose.pitch, 1) if face.pose else None,
        eyes_down=round(face.eyes.look_down, 3) if face.eyes else None,
        focus=focus,
    )


_EVENT_KINDS: tuple[tuple[str, EventKind], ...] = (
    ("paused", "pause"),
    ("would pause", "pause"),
    ("resumed", "resume"),
    ("would resume", "resume"),
    ("player:", "player"),
    ("calibrat", "calibration"),
)


class _EventForwarder(logging.Handler):
    """Copies event log records to the web UI (from whatever thread logs them)."""

    def __init__(self, web: WebServer, loop: asyncio.AbstractEventLoop) -> None:
        super().__init__(level=logging.INFO)
        self._web = web
        self._loop = loop

    def emit(self, record: logging.LogRecord) -> None:
        text = record.getMessage()
        kind: EventKind = next(
            (k for prefix, k in _EVENT_KINDS if text.startswith(prefix)), "other"
        )
        event = EventInfo(
            ts=round(record.created * 1000),
            time=time.strftime("%H:%M:%S", time.localtime(record.created)),
            level="warning" if record.levelno >= logging.WARNING else "info",
            kind=kind,
            text=text,
        )
        with contextlib.suppress(RuntimeError):  # loop already closed at shutdown
            self._loop.call_soon_threadsafe(self._web.publish_event, event)
