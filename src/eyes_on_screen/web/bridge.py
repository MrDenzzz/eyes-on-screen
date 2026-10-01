"""Connects a running App to the web UI.

AppControls turns REST calls into App operations, WebUi pushes what the App sees
(status, annotated frames, events) to every open tab. The App itself never imports
anything from `web`.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Literal

from eyes_on_screen.app import App, Scene
from eyes_on_screen.attention.classifier import Attention
from eyes_on_screen.config import AppConfig, WebConfig
from eyes_on_screen.logging_setup import EVENTS_LOGGER
from eyes_on_screen.recording import GAZE_STEPS
from eyes_on_screen.vision.analyzer import FaceObservation
from eyes_on_screen.web.events import EventForwarder
from eyes_on_screen.web.messages import (
    AnalysisInfo,
    AutomationInfo,
    CalibrationInfo,
    FaceInfo,
    FrameHeader,
    MachineInfo,
    PlayerInfo,
    RecordingInfo,
    RecordingProgress,
    RecordingResult,
    RecordingStepInfo,
    RoomInfo,
    SettingsChanges,
    SettingsInfo,
    StatusMessage,
    StreamInfo,
)
from eyes_on_screen.web.protocol import encode_frame
from eyes_on_screen.web.server import WebServer

log = logging.getLogger(__name__)


class AppControls:
    """The web server's Controls, carried out by the App."""

    def __init__(self, app: App) -> None:
        self._app = app

    def status(self) -> StatusMessage:
        return status_message(self._app)

    def change_settings(self, changes: SettingsChanges) -> SettingsInfo:
        as_dict = changes.as_changes()
        config = self._app.change_settings(as_dict)
        summary = ", ".join(f"{s}.{k}" for s, values in as_dict.items() for k in values)
        log.info("Settings changed from the web UI: %s", summary)
        return settings_info(config)

    def start_calibration(self) -> None:
        self._app.start_calibration()

    def set_automation(self, enabled: bool) -> AutomationInfo:
        self._app.set_automation(enabled)
        return AutomationInfo(enabled=self._app.automation, dry_run=self._app.dry_run)

    async def press(self, action: Literal["play", "pause"]) -> None:
        await self._app.press(action)

    def recording_steps(self) -> list[RecordingStepInfo]:
        return [RecordingStepInfo.model_validate(s, from_attributes=True) for s in GAZE_STEPS]

    def start_recording_step(self, index: int) -> RecordingInfo:
        self._app.start_recording_step(index)
        info = recording_info(self._app, time.monotonic())
        assert info is not None
        return info

    def cancel_recording_step(self) -> None:
        self._app.cancel_recording_step()

    def finish_recording(self) -> None:
        self._app.finish_recording()


class WebUi:
    """Serves the web UI for an App and keeps every open tab up to date."""

    def __init__(self, config: WebConfig, app: App) -> None:
        self._config = config
        self._app = app
        self._server = WebServer(config, AppControls(app))
        self._forwarder: EventForwarder | None = None

    @property
    def server(self) -> WebServer:
        return self._server

    async def start(self) -> None:
        """Listen and start pushing; raises OSError if the port is taken."""
        await self._server.start()
        self._forwarder = EventForwarder(self._server, asyncio.get_running_loop())
        logging.getLogger(EVENTS_LOGGER).addHandler(self._forwarder)
        self._app.listeners.append(self)
        if lan_url := self._server.lan_url:
            log.info("Web UI: %s (from other devices: %s)", self._server.url, lan_url)
        else:
            log.info("Web UI: %s", self._server.url)

    async def stop(self) -> None:
        if self in self._app.listeners:
            self._app.listeners.remove(self)
        if self._forwarder is not None:
            logging.getLogger(EVENTS_LOGGER).removeHandler(self._forwarder)
            self._forwarder = None
        await self._server.stop()

    # AppListener

    async def scene(self, scene: Scene) -> None:
        if not self._server.has_clients:
            return  # nobody is watching: skip the JPEG encoding
        header = frame_header(scene).model_dump(mode="json")
        config = self._config
        packet = await asyncio.to_thread(
            encode_frame,
            scene.frame.image,
            header,
            max_width=config.max_width,
            quality=config.jpeg_quality,
        )
        self._server.publish_frame(packet)

    def tick(self) -> None:
        self._server.publish_status(status_message(self._app))


# App state -> messages


def status_message(app: App) -> StatusMessage:
    now = time.monotonic()
    stats = app.source_stats()
    machine = app.machine_status(now)
    player = app.player
    state = player.state if player else None
    calibration = app.calibration
    return StatusMessage(
        stream=StreamInfo(
            connected=stats.connected,
            width=stats.width,
            height=stats.height,
            fps=round(stats.fps, 1),
            error=stats.last_error,
        ),
        analysis=AnalysisInfo(fps=round(app.analysis_fps(now), 1), ms=round(app.analysis_ms, 1)),
        player=PlayerInfo(
            configured=player is not None,
            connected=player is not None and player.connected,
            name=player.name if player else None,
            playback=state.playback if state else None,
            app=state.app if state else None,
            title=state.title if state else None,
        ),
        room=RoomInfo(
            attention=app.room.attention, viewers=app.room.viewers, looking=app.room.looking
        ),
        machine=MachineInfo(
            streak_s=round(machine.streak_s, 2),
            paused_by_us=machine.paused_by_us,
            armed=machine.armed,
            pending=machine.pending,
            skipped=machine.skipped,
        ),
        automation=AutomationInfo(enabled=app.automation, dry_run=app.dry_run),
        calibration=None
        if calibration is None
        else CalibrationInfo(
            phase="countdown" if calibration.counting_down(now) else "collecting",
            remaining_s=round(calibration.remaining_s(now), 2),
            phase_s=calibration.delay_s
            if calibration.counting_down(now)
            else calibration.duration_s,
        ),
        recording=recording_info(app, now),
        settings=settings_info(app.config),
    )


def settings_info(config: AppConfig) -> SettingsInfo:
    return SettingsInfo(roi=config.target.roi, pose=config.pose, behavior=config.behavior)


def recording_info(app: App, now: float) -> RecordingInfo | None:
    recording = app.recording
    if recording is None:
        return None
    progress = recording.progress(now)
    return RecordingInfo(
        file=app.shown_path(recording.path),
        current=None
        if progress is None
        else RecordingProgress.model_validate(progress, from_attributes=True),
        done=[RecordingResult.model_validate(r, from_attributes=True) for r in recording.results],
        last=recording.last,
    )


def frame_header(scene: Scene) -> FrameHeader:
    frame = scene.frame
    return FrameHeader(
        seq=frame.seq,
        # Wall-clock milliseconds, the same clock as the events' timestamps.
        ts=round((time.time() - (time.monotonic() - frame.timestamp)) * 1000),
        attention=scene.room.attention,
        faces=[
            face_info(face, state, face is scene.focus)
            for face, state in zip(scene.faces, scene.states, strict=True)
        ],
    )


def face_info(face: FaceObservation, state: Attention | None, focus: bool) -> FaceInfo:
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
