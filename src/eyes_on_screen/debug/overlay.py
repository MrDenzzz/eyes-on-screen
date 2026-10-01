"""Drawing analysis results over a frame; shared by `eos pose` and `eos run --debug`."""

from __future__ import annotations

import math
from collections import deque
from collections.abc import Sequence

import cv2
import numpy as np

from eyes_on_screen.attention.classifier import Attention
from eyes_on_screen.config import PoseConfig
from eyes_on_screen.video.source import SourceStats
from eyes_on_screen.vision.analyzer import FaceObservation, Roi

DISPLAY_WIDTH = 1280

Color = tuple[int, int, int]  # BGR
Line = tuple[str, Color, float]  # text, colour, font scale

COLORS: dict[Attention, Color] = {
    Attention.LOOKING: (90, 200, 90),
    Attention.AWAY: (0, 150, 255),
    Attention.ABSENT: (170, 170, 170),
}
TEXT: Color = (255, 255, 255)
MUTED: Color = (200, 200, 200)
HIGHLIGHT: Color = (0, 220, 255)
_OTHER_FACE: Color = (200, 200, 200)
_ROI_COLOR: Color = (255, 200, 0)
_FONT = cv2.FONT_HERSHEY_SIMPLEX


class View:
    """One analysed frame, downscaled for display, with what to say about each face."""

    def __init__(
        self,
        image: np.ndarray,
        faces: Sequence[FaceObservation],
        face_states: Sequence[Attention | None],
        attention: Attention,
        focus: FaceObservation | None,
        analysis_ms: float,
    ) -> None:
        """`face_states`: per face, its attention, or None for faces that do not count
        (other people in `eos pose`, decor in `eos run`). `focus`: the face whose pose
        is spelled out and shown zoomed in."""
        scale = DISPLAY_WIDTH / image.shape[1]
        size = (DISPLAY_WIDTH, round(image.shape[0] * scale))
        self.image = cv2.resize(image, size, interpolation=cv2.INTER_AREA)
        self.faces = list(faces)
        self.face_states = list(face_states)
        self.attention = attention
        self.focus = focus
        self.analysis_ms = analysis_ms
        self.fresh = True


def rate(times: deque[float], now: float) -> float:
    """Events per second over the timestamps in `times`; 0 once they stopped."""
    if len(times) < 2 or now - times[-1] > 1.0:
        return 0.0
    span = times[-1] - times[0]
    return (len(times) - 1) / span if span > 0 else 0.0


def render(
    view: View,
    pose: PoseConfig,
    roi: Roi,
    stats: SourceStats,
    analysed_fps: float,
    footer: Sequence[Line] = (),
) -> np.ndarray:
    canvas = view.image.copy()
    height, width = canvas.shape[:2]

    # Spotlight the ROI: everything outside it is dimmed.
    x1, y1, x2, y2 = (
        round(value * size) for value, size in zip(roi, (width, height, width, height), strict=True)
    )
    dimmed = (canvas * 0.45).astype(np.uint8)
    dimmed[y1:y2, x1:x2] = canvas[y1:y2, x1:x2]
    canvas = dimmed
    cv2.rectangle(canvas, (x1, y1), (x2, y2), _ROI_COLOR, 1, cv2.LINE_AA)

    for face, state in zip(view.faces, view.face_states, strict=True):
        color = COLORS[state] if state is not None else _OTHER_FACE
        _draw_face(canvas, face, color, emphasized=face is view.focus)

    if not stats.connected:
        canvas = (canvas * 0.4).astype(np.uint8)

    lines: list[Line] = [
        (view.attention.value.upper(), COLORS[view.attention], 0.9),
        (_pose_line(view.focus, pose), TEXT, 0.5),
        (
            f"centre yaw {pose.yaw_center_deg:+.1f} pitch {pose.pitch_center_deg:+.1f}"
            f"  tolerance +-{pose.yaw_tolerance_deg:.0f} / +-{pose.pitch_tolerance_deg:.0f}",
            TEXT,
            0.5,
        ),
        (_stream_line(stats, analysed_fps, view.analysis_ms), MUTED, 0.45),
        *footer,
    ]
    _draw_panel(canvas, lines)

    if view.focus is not None and view.focus.crop is not None:
        focus_state = view.face_states[view.faces.index(view.focus)]
        _draw_inset(canvas, view.focus.crop, COLORS[focus_state] if focus_state else _OTHER_FACE)
    return canvas


def _pose_line(face: FaceObservation | None, pose: PoseConfig) -> str:
    if face is None:
        return "no face in the ROI"
    if face.pose is None:
        return f"face found (score {face.score:.2f}), no landmarks: turned away or covered"
    p = face.pose
    line = (
        f"yaw {p.yaw:+.0f} pitch {p.pitch:+.0f} roll {p.roll:+.0f}"
        f"   offset {p.yaw - pose.yaw_center_deg:+.0f} / {p.pitch - pose.pitch_center_deg:+.0f}"
    )
    if face.eyes is not None:
        eyes = face.eyes
        line += f"   eyes down {eyes.look_down:.2f} up {eyes.look_up:.2f} closed {eyes.closed:.2f}"
    return line


def _stream_line(stats: SourceStats, analysed_fps: float, analysis_ms: float) -> str:
    if not stats.connected:
        return f"STREAM LOST: {stats.last_error or 'connecting...'}"
    return (
        f"{stats.width}x{stats.height} {stats.fps:.0f} fps in, "
        f"{analysed_fps:.1f} fps analysed, {analysis_ms:.0f} ms per frame"
    )


def _draw_face(canvas: np.ndarray, face: FaceObservation, color: Color, emphasized: bool) -> None:
    height, width = canvas.shape[:2]
    x1, y1, x2, y2 = face.box
    p1 = (round(x1 * width), round(y1 * height))
    p2 = (round(x2 * width), round(y2 * height))
    cv2.rectangle(canvas, p1, p2, color, 2 if emphasized else 1, cv2.LINE_AA)

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


def _draw_panel(canvas: np.ndarray, lines: Sequence[Line]) -> None:
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


def _draw_inset(canvas: np.ndarray, crop: np.ndarray, color: Color) -> None:
    """The zoomed face the pose was estimated on, in the top-right corner."""
    size, margin = 160, 10
    inset = cv2.resize(crop, (size, size), interpolation=cv2.INTER_AREA)
    x = canvas.shape[1] - size - margin
    canvas[margin : margin + size, x : x + size] = inset
    cv2.rectangle(canvas, (x - 1, margin - 1), (x + size, margin + size), color, 2)
