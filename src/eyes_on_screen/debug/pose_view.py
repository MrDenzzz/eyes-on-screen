"""`eos pose`: live face analysis in an OpenCV window, plus head-pose calibration."""

from __future__ import annotations

import csv
import logging
import math
import time
from collections import deque
from pathlib import Path

import cv2

from eyes_on_screen.attention.calibration import (
    CalibrationError,
    CalibrationSession,
    calibrate_center,
)
from eyes_on_screen.attention.classifier import Attention, classify
from eyes_on_screen.config import PoseConfig
from eyes_on_screen.debug.overlay import HIGHLIGHT, MUTED, Line, View, rate, render
from eyes_on_screen.video.source import VideoSource
from eyes_on_screen.vision.analyzer import FaceAnalyzer, FaceObservation, Roi
from eyes_on_screen.vision.head_pose import HeadPose
from eyes_on_screen.vision.target import select_target

log = logging.getLogger(__name__)

WINDOW = "eyes-on-screen pose"
# The keyboard is usually not next to the sofa: time to walk over and sit down.
CALIBRATION_DELAY_S = 10.0
CALIBRATION_DURATION_S = 2.0
_KEY_ESC = 27
_STATUS_REFRESH_S = 0.5
# While recording, these keys label what the viewer is doing, to tune thresholds
# against it offline.
_LABEL_KEYS = {ord("1"): "screen", ord("2"): "phone", ord("3"): "elsewhere", ord("0"): ""}
_LABEL_HINT = "1 screen  2 phone  3 elsewhere  0 none"


def run_pose_view(
    source: VideoSource,
    analyzer: FaceAnalyzer,
    pose: PoseConfig,
    roi: Roi,
    process_fps: float,
    record: Path | None = None,
) -> None:
    """Analyse frames at `process_fps` and show the result until q/Esc or window close.

    `c` starts a calibration: after a countdown the viewer's pose, while looking at the
    screen, becomes the new centre. `record` writes every analysed frame to a CSV file,
    labelled with what the keys 1-3 say the viewer is doing.
    """
    period = 1.0 / process_fps
    analysis_times: deque[float] = deque(maxlen=20)
    seq = -1
    next_analysis = 0.0
    last_render = 0.0
    view: View | None = None
    calibration: CalibrationSession | None = None
    recorder = _Recorder(record) if record else None
    label = ""

    cv2.namedWindow(WINDOW, cv2.WINDOW_NORMAL)
    try:
        while True:
            frame = source.wait_for_frame(seq, timeout=0.05)
            now = time.monotonic()
            if frame is not None:
                seq = frame.seq
                if now >= next_analysis:
                    next_analysis = now + period
                    started = time.perf_counter()
                    faces = analyzer.analyze(frame.image)
                    elapsed_ms = (time.perf_counter() - started) * 1000
                    analysis_times.append(now)

                    target = select_target(faces)
                    attention = classify(target, pose)
                    if calibration is not None and target is not None:
                        calibration.add(now, target.pose)
                    if recorder is not None:
                        recorder.write(now, faces, target, attention, label)
                    states = [attention if face is target else None for face in faces]
                    view = View(frame.image, faces, states, attention, target, elapsed_ms)

            if calibration is not None and calibration.finished(now):
                pose = _finish_calibration(calibration.poses, pose)
                calibration = None

            if view is not None and (view.fresh or now - last_render > _STATUS_REFRESH_S):
                footer: list[Line] = [
                    (_calibration_text(calibration, now), HIGHLIGHT, 0.6)
                    if calibration
                    else ("c: calibrate (10 s countdown)   q: quit", MUTED, 0.45)
                ]
                if recorder is not None:
                    footer.append(
                        (
                            f"recording, label: {label or '-'}   ({_LABEL_HINT})",
                            HIGHLIGHT if label else MUTED,
                            0.5,
                        )
                    )
                fps = rate(analysis_times, now)
                cv2.imshow(WINDOW, render(view, pose, roi, source.stats(), fps, footer))
                view.fresh = False
                last_render = now

            key = cv2.waitKey(1) & 0xFF
            if key in (ord("q"), _KEY_ESC):
                break
            if key == ord("c"):
                calibration = CalibrationSession(now, CALIBRATION_DELAY_S, CALIBRATION_DURATION_S)
                log.info(
                    "Calibration starts in %.0fs: sit down and look at the screen",
                    CALIBRATION_DELAY_S,
                )
            if recorder is not None and key in _LABEL_KEYS:
                label = _LABEL_KEYS[key]
                log.info("Label: %s", label or "none")
            if cv2.getWindowProperty(WINDOW, cv2.WND_PROP_VISIBLE) < 1:
                break
    finally:
        cv2.destroyWindow(WINDOW)
        if recorder is not None:
            recorder.close()


def _calibration_text(session: CalibrationSession, now: float) -> str:
    if session.counting_down(now):
        return (
            f"calibration in {math.ceil(session.remaining_s(now))}s: sit down, look at the screen"
        )
    return "calibrating: keep looking at the screen"


class _Recorder:
    """Per-frame CSV of the target's pose, for tuning thresholds offline."""

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        # Line-buffered: a killed or crashed session still leaves its rows on disk.
        self._file = path.open("w", newline="", encoding="utf-8", buffering=1)
        self._writer = csv.writer(self._file)
        self._writer.writerow(
            [
                "t",
                "faces",
                "unconfirmed",
                "score",
                "yaw",
                "pitch",
                "roll",
                "eye_down",
                "eye_up",
                "eye_closed",
                "eye_squint",
                "attention",
                "label",
            ]
        )
        self._t0 = time.monotonic()
        log.info("Recording poses to %s", path)

    def write(
        self,
        now: float,
        faces: list[FaceObservation],
        target: FaceObservation | None,
        attention: Attention,
        label: str,
    ) -> None:
        pose = target.pose if target else None
        eyes = target.eyes if target else None
        self._writer.writerow(
            [
                f"{now - self._t0:.2f}",
                len(faces),
                sum(face.pose is None for face in faces),
                f"{target.score:.2f}" if target else "",
                f"{pose.yaw:.1f}" if pose else "",
                f"{pose.pitch:.1f}" if pose else "",
                f"{pose.roll:.1f}" if pose else "",
                f"{eyes.look_down:.3f}" if eyes else "",
                f"{eyes.look_up:.3f}" if eyes else "",
                f"{eyes.closed:.3f}" if eyes else "",
                f"{eyes.squint:.3f}" if eyes else "",
                attention.value,
                label,
            ]
        )

    def close(self) -> None:
        self._file.close()


def _finish_calibration(poses: list[HeadPose], pose: PoseConfig) -> PoseConfig:
    try:
        calibrated = calibrate_center(poses, pose)
    except CalibrationError as exc:
        log.warning("Calibration failed: %s", exc)
        return pose
    log.info(
        "Calibrated from %d poses. Put this into config.yaml:\n"
        "pose:\n  yaw_center_deg: %.1f\n  pitch_center_deg: %.1f",
        len(poses),
        calibrated.yaw_center_deg,
        calibrated.pitch_center_deg,
    )
    return calibrated
