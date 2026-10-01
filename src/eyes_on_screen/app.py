"""`eos run`: camera -> faces -> room attention -> state machine -> player.

The app knows nothing about the web UI. web/bridge.py watches it through `listeners`
and its read-only properties, and drives it through the operations at the bottom:
settings, calibration, automation, player buttons and guided recordings.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal, Protocol

from eyes_on_screen.appletv.state import AppleTvError, Player, PlayerState
from eyes_on_screen.attention.calibration import (
    CalibrationError,
    CalibrationSession,
    calibrate_center,
)
from eyes_on_screen.attention.classifier import Attention, classify
from eyes_on_screen.attention.state_machine import (
    Decision,
    MachineStatus,
    PlaybackCommand,
    PlaybackStateMachine,
)
from eyes_on_screen.attention.viewers import RoomAttention, ViewerFilter, room_attention
from eyes_on_screen.config import AppConfig
from eyes_on_screen.logging_setup import EVENTS_LOGGER
from eyes_on_screen.recording import GuidedRecording, RecordingError
from eyes_on_screen.settings import Changes, SettingsError, apply_changes, save_changes
from eyes_on_screen.video.source import Frame, SourceStats, VideoSource
from eyes_on_screen.vision.analyzer import FaceAnalyzer, FaceObservation
from eyes_on_screen.vision.target import select_target

log = logging.getLogger(__name__)
events = logging.getLogger(EVENTS_LOGGER)

# The viewer holds the phone or laptop when calibrating: a short countdown is enough.
CALIBRATION_DELAY_S = 3.0
CALIBRATION_DURATION_S = 2.0
_FRAME_WAIT_S = 0.5
_RATE_WINDOW = 20


@dataclass(frozen=True, slots=True)
class Scene:
    """One analysed frame, as the app understood it."""

    frame: Frame
    faces: list[FaceObservation]
    states: list[Attention | None]
    """Per face: its attention, or None for face-like decor that is not a viewer."""
    focus: FaceObservation | None
    """The viewer the pose readouts follow (largest confirmed face)."""
    room: RoomAttention


class AppListener(Protocol):
    async def scene(self, scene: Scene) -> None:
        """Called for every analysed frame."""
        ...

    def tick(self) -> None:
        """Called on every turn of the analysis loop, with or without a new frame."""
        ...


class App:
    def __init__(
        self,
        config: AppConfig,
        config_path: Path,
        source: VideoSource,
        analyzer: FaceAnalyzer,
        player: Player | None = None,
        *,
        dry_run: bool = False,
    ) -> None:
        """`player` None: watch only, nothing is ever paused (no Apple TV set up yet)."""
        self._config = config
        self._config_path = config_path
        self._source = source
        self._analyzer = analyzer
        self._player = player
        self.dry_run = dry_run
        self.automation = True
        self.listeners: list[AppListener] = []
        self.analysis_ms = 0.0
        self._machine = PlaybackStateMachine(config.behavior)
        self._viewers = ViewerFilter()
        self._room = RoomAttention(Attention.ABSENT, viewers=0, looking=0)
        self._analysis_times: deque[float] = deque(maxlen=_RATE_WINDOW)
        self._calibration: CalibrationSession | None = None
        self._recording: GuidedRecording | None = None
        # MediaPipe and OpenCV work stays on one dedicated thread, off the event loop
        # that serves the Apple TV connection and the web UI.
        self._worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="analysis")
        if player is not None:
            player.on_state = self._on_player

    async def run(self) -> None:
        """Run until cancelled (Ctrl+C)."""
        events.info("started%s", " (dry run: commands are only logged)" if self.dry_run else "")
        player_task = (
            asyncio.create_task(self._player.run_forever(), name="player")
            if self._player is not None
            else None
        )
        try:
            await self._analysis_loop()
        finally:
            if player_task is not None and self._player is not None:
                player_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await player_task
                await self._player.close()
            self._worker.shutdown(wait=True)
            self.finish_recording()
            events.info("stopped")

    # The pipeline

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
                self.analysis_ms = (time.perf_counter() - started) * 1000
                self._analysis_times.append(time.monotonic())
                await self._observe(frame, faces)
            self._tick_recording(time.monotonic())
            for listener in self.listeners:
                listener.tick()

    async def _observe(self, frame: Frame, faces: list[FaceObservation]) -> None:
        now = frame.timestamp
        config = self._config
        viewers = self._viewers.viewers(faces, now)
        room = room_attention(viewers, config.pose, config.behavior.multiple_viewers)
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
        if self._recording is not None:
            self._recording.add(now, faces, focus, classify(focus, config.pose))

        if self.automation:
            decision = self._machine.observe(room.attention, now)
            if decision is not None:
                await self._execute(decision)

        scene = Scene(
            frame=frame,
            faces=faces,
            states=[classify(face, config.pose) if face in viewers else None for face in faces],
            focus=focus,
            room=room,
        )
        for listener in self.listeners:
            await listener.scene(scene)

    async def _execute(self, decision: Decision) -> None:
        if self.dry_run or self._player is None:
            self._machine.skip()
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

    # What the UI shows

    @property
    def config(self) -> AppConfig:
        return self._config

    @property
    def player(self) -> Player | None:
        return self._player

    @property
    def room(self) -> RoomAttention:
        return self._room

    @property
    def calibration(self) -> CalibrationSession | None:
        return self._calibration

    @property
    def recording(self) -> GuidedRecording | None:
        return self._recording

    def source_stats(self) -> SourceStats:
        return self._source.stats()

    def machine_status(self, now: float) -> MachineStatus:
        return self._machine.status(now)

    def analysis_fps(self, now: float) -> float:
        times = self._analysis_times
        if len(times) < 2 or now - times[-1] > 1.0:
            return 0.0
        span = times[-1] - times[0]
        return (len(times) - 1) / span if span > 0 else 0.0

    def shown_path(self, path: Path) -> str:
        """`path` relative to the config folder, where logs and recordings usually are."""
        try:
            return path.relative_to(self._config_path.resolve().parent).as_posix()
        except ValueError:
            return str(path)

    # Operations

    def change_settings(self, changes: Changes) -> AppConfig:
        """Validate, save to config.yaml and apply live; raises SettingsError."""
        updated = apply_changes(self._config, changes)
        try:
            save_changes(self._config_path, updated, changes)
        except OSError as exc:
            raise SettingsError(f"cannot save {self._config_path}: {exc}") from exc
        self._config = updated
        self._analyzer.roi = updated.target.roi
        self._machine.behavior = updated.behavior
        return updated

    def start_calibration(self) -> None:
        """After a countdown, the viewer's pose becomes the screen direction."""
        self._calibration = CalibrationSession(
            time.monotonic(), CALIBRATION_DELAY_S, CALIBRATION_DURATION_S
        )

    def set_automation(self, enabled: bool) -> None:
        if enabled != self.automation:
            self.automation = enabled
            events.info("automation %s", "on" if enabled else "off")

    async def press(self, action: Literal["play", "pause"]) -> None:
        """Raises AppleTvError when the player is unreachable or not set up."""
        if self._player is None:
            raise AppleTvError("no Apple TV is set up: run `eos atv scan` and `eos atv pair`")
        await (self._player.play() if action == "play" else self._player.pause())
        events.info("%s pressed", action)

    def start_recording_step(self, index: int) -> None:
        """Start (or redo) a step of the guided recording; raises RecordingError."""
        now = time.monotonic()
        recording = self._recording or GuidedRecording(
            self._config.logging.recordings_dir
            / datetime.now().strftime("gaze-%Y-%m-%d_%H-%M-%S.csv")
        )
        try:
            recording.start(index, now)
        except OSError as exc:
            raise RecordingError(f"cannot write {recording.path}: {exc}") from exc
        if self._recording is None:
            self._recording = recording
            events.info("recording to %s", self.shown_path(recording.path))

    def cancel_recording_step(self) -> None:
        if self._recording is not None:
            self._recording.cancel()

    def finish_recording(self) -> None:
        recording, self._recording = self._recording, None
        if recording is not None:
            recording.close()
            events.info("recording saved: %s", self.shown_path(recording.path))

    # Calibration and recording internals

    def _finish_calibration(self) -> None:
        assert self._calibration is not None
        poses, self._calibration = self._calibration.poses, None
        try:
            centre = calibrate_center(poses, self._config.pose)
            self.change_settings(
                {
                    "pose": {
                        "yaw_center_deg": centre.yaw_center_deg,
                        "pitch_center_deg": centre.pitch_center_deg,
                    }
                }
            )
        except (CalibrationError, SettingsError) as exc:
            events.warning("calibration failed: %s", exc)
            return
        events.info(
            "calibrated: screen at yaw %+.1f, pitch %+.1f (from %d poses)",
            centre.yaw_center_deg,
            centre.pitch_center_deg,
            len(poses),
        )

    def _tick_recording(self, now: float) -> None:
        if self._recording is None:
            return
        result = self._recording.update(now)
        if result is not None:
            step = self._recording.steps[result.index]
            share = result.with_face / result.frames if result.frames else 0.0
            events.info(
                'recorded step %d "%s": %d frames, face measured in %.0f%%',
                result.index + 1,
                step.title,
                result.frames,
                share * 100,
            )
