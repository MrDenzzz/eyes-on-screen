"""`eos pose`: live face analysis in an OpenCV window, plus head-pose calibration."""

from __future__ import annotations

import csv
import logging
import math
import time
from collections import deque
from pathlib import Path

import cv2
import numpy as np

from eyes_on_screen.attention.calibration import CalibrationError, calibrate_center
from eyes_on_screen.attention.classifier import Attention, classify
from eyes_on_screen.config import PoseConfig
from eyes_on_screen.video.source import SourceStats, VideoSource
from eyes_on_screen.vision.analyzer import FaceAnalyzer, FaceObservation, Roi
from eyes_on_screen.vision.head_pose import HeadPose
from eyes_on_screen.vision.target import select_target

log = logging.getLogger(__name__)

WINDOW = "eyes-on-screen pose"
DISPLAY_WIDTH = 1280
# The keyboard is usually not next to the sofa: time to walk over and sit down.
CALIBRATION_DELAY_S = 10.0
CALIBRATION_DURATION_S = 2.0
_KEY_ESC = 27
_STATUS_REFRESH_S = 0.5
_CALIBRATION_COLOR = (0, 220, 255)

# BGR
_COLORS = {
    Attention.LOOKING: (90, 200, 90),
    Attention.AWAY: (0, 150, 255),
    Attention.ABSENT: (170, 170, 170),
}
_OTHER_FACE = (200, 200, 200)
_ROI_COLOR = (255, 200, 0)
_FONT = cv2.FONT_HERSHEY_SIMPLEX


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
    screen, becomes the new centre. `record` writes every analysed frame to a CSV file.
    """
    period = 1.0 / process_fps
    analysis_times: deque[float] = deque(maxlen=20)
    seq = -1
    next_analysis = 0.0
    last_render = 0.0
    view: _View | None = None
    calibration: _Calibration | None = None
    recorder = _Recorder(record) if record else None

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
                    if calibration is not None and target is not None:
                        calibration.add(now, target.pose)
                    if recorder is not None:
                        recorder.write(now, faces, target, classify(target, pose))
                    view = _View(frame.image, faces, target, elapsed_ms)

            if calibration is not None and calibration.finished(now):
                pose = _finish_calibration(calibration.poses, pose)
                calibration = None

            if view is not None and (view.fresh or now - last_render > _STATUS_REFRESH_S):
                rate = _rate(analysis_times, now)
                status = calibration.status(now) if calibration else None
                cv2.imshow(WINDOW, _render(view, pose, roi, source.stats(), rate, status))
                view.fresh = False
                last_render = now

            key = cv2.waitKey(1) & 0xFF
            if key in (ord("q"), _KEY_ESC):
                break
            if key == ord("c"):
                calibration = _Calibration(now)
                log.info(
                    "Calibration starts in %.0fs: sit down and look at the screen",
                    CALIBRATION_DELAY_S,
                )
            if cv2.getWindowProperty(WINDOW, cv2.WND_PROP_VISIBLE) < 1:
                break
    finally:
        cv2.destroyWindow(WINDOW)
        if recorder is not None:
            recorder.close()


class _Calibration:
    def __init__(self, now: float) -> None:
        self.start = now + CALIBRATION_DELAY_S
        self.end = self.start + CALIBRATION_DURATION_S
        self.poses: list[HeadPose] = []

    def add(self, now: float, pose: HeadPose | None) -> None:
        if pose is not None and self.start <= now <= self.end:
            self.poses.append(pose)

    def finished(self, now: float) -> bool:
        return now > self.end

    def status(self, now: float) -> str:
        if now < self.start:
            return f"calibration in {math.ceil(self.start - now)}s: sit down, look at the screen"
        return "calibrating: keep looking at the screen"


class _Recorder:
    """Per-frame CSV of the target's pose, for tuning thresholds offline."""

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        # Line-buffered: a killed or crashed session still leaves its rows on disk.
        self._file = path.open("w", newline="", encoding="utf-8", buffering=1)
        self._writer = csv.writer(self._file)
        self._writer.writerow(["t", "faces", "score", "yaw", "pitch", "roll", "attention"])
        self._t0 = time.monotonic()
        log.info("Recording poses to %s", path)

    def write(
        self,
        now: float,
        faces: list[FaceObservation],
        target: FaceObservation | None,
        attention: Attention,
    ) -> None:
        pose = target.pose if target else None
        self._writer.writerow(
            [
                f"{now - self._t0:.2f}",
                len(faces),
                f"{target.score:.2f}" if target else "",
                f"{pose.yaw:.1f}" if pose else "",
                f"{pose.pitch:.1f}" if pose else "",
                f"{pose.roll:.1f}" if pose else "",
                attention.value,
            ]
        )

    def close(self) -> None:
        self._file.close()


class _View:
    def __init__(
        self,
        image: np.ndarray,
        faces: list[FaceObservation],
        target: FaceObservation | None,
        analysis_ms: float,
    ) -> None:
        scale = DISPLAY_WIDTH / image.shape[1]
        size = (DISPLAY_WIDTH, round(image.shape[0] * scale))
        self.image = cv2.resize(image, size, interpolation=cv2.INTER_AREA)
        self.faces = faces
        self.target = target
        self.analysis_ms = analysis_ms
        self.fresh = True


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


def _rate(times: deque[float], now: float) -> float:
    if len(times) < 2 or now - times[-1] > 1.0:
        return 0.0
    span = times[-1] - times[0]
    return (len(times) - 1) / span if span > 0 else 0.0


def _render(
    view: _View,
    pose: PoseConfig,
    roi: Roi,
    stats: SourceStats,
    rate: float,
    calibration_status: str | None = None,
) -> np.ndarray:
    canvas = view.image.copy()
    height, width = canvas.shape[:2]
    attention = classify(view.target, pose)

    # Spotlight the ROI: everything outside it is dimmed.
    x1, y1, x2, y2 = (
        round(value * size) for value, size in zip(roi, (width, height, width, height), strict=True)
    )
    dimmed = (canvas * 0.45).astype(np.uint8)
    dimmed[y1:y2, x1:x2] = canvas[y1:y2, x1:x2]
    canvas = dimmed
    cv2.rectangle(canvas, (x1, y1), (x2, y2), _ROI_COLOR, 1, cv2.LINE_AA)

    for face in view.faces:
        is_target = face is view.target
        _draw_face(canvas, face, _COLORS[attention] if is_target else _OTHER_FACE, is_target)

    if not stats.connected:
        canvas = (canvas * 0.4).astype(np.uint8)

    lines = [
        (attention.value.upper(), _COLORS[attention], 0.9),
        (_pose_line(view.target, pose), (255, 255, 255), 0.5),
        (
            f"centre yaw {pose.yaw_center_deg:+.1f} pitch {pose.pitch_center_deg:+.1f}"
            f"  tolerance +-{pose.yaw_tolerance_deg:.0f} / +-{pose.pitch_tolerance_deg:.0f}",
            (255, 255, 255),
            0.5,
        ),
        (_stream_line(stats, rate, view.analysis_ms), (200, 200, 200), 0.45),
        (
            calibration_status or "c: calibrate (10 s countdown)   q: quit",
            _CALIBRATION_COLOR if calibration_status else (200, 200, 200),
            0.6 if calibration_status else 0.45,
        ),
    ]
    _draw_panel(canvas, lines)

    if view.target is not None and view.target.crop is not None:
        _draw_inset(canvas, view.target.crop, _COLORS[attention])
    return canvas


def _pose_line(target: FaceObservation | None, pose: PoseConfig) -> str:
    if target is None:
        return "no face in the ROI"
    if target.pose is None:
        return f"face found (score {target.score:.2f}), no landmarks: turned away or covered"
    p = target.pose
    return (
        f"yaw {p.yaw:+.0f} pitch {p.pitch:+.0f} roll {p.roll:+.0f}"
        f"   offset {p.yaw - pose.yaw_center_deg:+.0f} / {p.pitch - pose.pitch_center_deg:+.0f}"
    )


def _stream_line(stats: SourceStats, rate: float, analysis_ms: float) -> str:
    if not stats.connected:
        return f"STREAM LOST: {stats.last_error or 'connecting...'}"
    return (
        f"{stats.width}x{stats.height} {stats.fps:.0f} fps in, "
        f"{rate:.1f} fps analysed, {analysis_ms:.0f} ms per frame"
    )


def _draw_face(canvas: np.ndarray, face: FaceObservation, color, is_target: bool) -> None:
    height, width = canvas.shape[:2]
    x1, y1, x2, y2 = face.box
    p1 = (round(x1 * width), round(y1 * height))
    p2 = (round(x2 * width), round(y2 * height))
    cv2.rectangle(canvas, p1, p2, color, 2 if is_target else 1, cv2.LINE_AA)

    if face.pose is not None:
        # Arrow where the face points: right for +yaw, up for +pitch.
        cx, cy = (p1[0] + p2[0]) / 2, (p1[1] + p2[1]) / 2
        length = 2.5 * (p2[0] - p1[0])
        end = (
            round(cx + length * math.sin(math.radians(face.pose.yaw))),
            round(cy - length * math.sin(math.radians(face.pose.pitch))),
        )
        cv2.arrowedLine(canvas, (round(cx), round(cy)), end, color, 2, cv2.LINE_AA, tipLength=0.25)
        label = f"{face.pose.yaw:+.0f} / {face.pose.pitch:+.0f}"
    else:
        label = "no landmarks"
    cv2.putText(canvas, label, (p1[0], p1[1] - 6), _FONT, 0.45, color, 1, cv2.LINE_AA)


def _draw_panel(canvas: np.ndarray, lines: list[tuple[str, tuple[int, int, int], float]]) -> None:
    pad, gap = 10, 8
    sizes = [cv2.getTextSize(text, _FONT, scale, 1)[0] for text, _, scale in lines]
    panel_w = max(w for w, _ in sizes) + 2 * pad
    panel_h = sum(h for _, h in sizes) + gap * (len(lines) - 1) + 2 * pad
    overlay = canvas.copy()
    cv2.rectangle(overlay, (0, 0), (panel_w, panel_h), (0, 0, 0), cv2.FILLED)
    cv2.addWeighted(overlay, 0.6, canvas, 0.4, 0, dst=canvas)

    y = pad
    for (text, color, scale), (_, h) in zip(lines, sizes, strict=True):
        y += h
        thickness = 2 if scale >= 0.8 else 1
        cv2.putText(canvas, text, (pad, y), _FONT, scale, color, thickness, cv2.LINE_AA)
        y += gap


def _draw_inset(canvas: np.ndarray, crop: np.ndarray, color) -> None:
    """The zoomed face the pose was estimated on, in the top-right corner."""
    size, margin = 160, 10
    inset = cv2.resize(crop, (size, size), interpolation=cv2.INTER_AREA)
    x = canvas.shape[1] - size - margin
    canvas[margin : margin + size, x : x + size] = inset
    cv2.rectangle(canvas, (x - 1, margin - 1), (x + size, margin + size), color, 2)
