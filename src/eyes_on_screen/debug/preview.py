"""Raw stream preview in an OpenCV window: confirms frames arrive before any detection runs."""

from __future__ import annotations

import cv2
import numpy as np

from eyes_on_screen.video.source import SourceStats, VideoSource

WINDOW = "eyes-on-screen preview"
_MAX_WINDOW_WIDTH = 1280
_PLACEHOLDER_SIZE = (720, 1280)  # (H, W) shown until the first frame arrives
_KEY_ESC = 27


def run_preview(source: VideoSource) -> None:
    """Show frames with a stream-health HUD until q/Esc is pressed or the window is closed."""
    cv2.namedWindow(WINDOW, cv2.WINDOW_NORMAL)
    window_sized = False
    seq = -1
    last_image: np.ndarray | None = None
    try:
        while True:
            frame = source.wait_for_frame(seq, timeout=0.05)
            if frame is not None:
                seq = frame.seq
                last_image = frame.image

            stats = source.stats()
            canvas = _render(last_image, stats)
            cv2.imshow(WINDOW, canvas)
            if last_image is not None and not window_sized:
                _fit_window(canvas)
                window_sized = True

            key = cv2.waitKey(1) & 0xFF
            if key in (ord("q"), _KEY_ESC):
                break
            if cv2.getWindowProperty(WINDOW, cv2.WND_PROP_VISIBLE) < 1:
                break
    finally:
        cv2.destroyWindow(WINDOW)


def _render(image: np.ndarray | None, stats: SourceStats) -> np.ndarray:
    if image is None:
        canvas = np.zeros((*_PLACEHOLDER_SIZE, 3), np.uint8)
    elif stats.connected:
        canvas = image.copy()
    else:
        # Keep the last frame visible but dimmed, so a drop is obvious at a glance.
        canvas = (image * 0.35).astype(np.uint8)

    lines = [stats.description]
    if stats.connected:
        lines.append(
            f"{stats.width}x{stats.height}  {stats.codec or '?'}  {stats.fps:.1f} fps  "
            f"frames {stats.frames}  reconnects {stats.reconnects}"
        )
    else:
        lines.append("connecting..." if stats.last_error is None else "reconnecting...")
        if stats.last_error:
            lines.append(stats.last_error)
    _draw_hud(canvas, lines)
    return canvas


def _draw_hud(canvas: np.ndarray, lines: list[str]) -> None:
    # Scale text with the frame: the window is shrunk to fit the screen, 2.5K text would vanish.
    scale = max(0.5, canvas.shape[1] / 1600)
    thickness = max(1, round(scale * 1.5))
    line_height = int(32 * scale)
    pad = int(12 * scale)

    width = max(
        cv2.getTextSize(line, cv2.FONT_HERSHEY_SIMPLEX, scale, thickness)[0][0] for line in lines
    )
    box_bottom = pad * 2 + line_height * len(lines)
    overlay = canvas.copy()
    cv2.rectangle(overlay, (0, 0), (width + pad * 2, box_bottom), (0, 0, 0), cv2.FILLED)
    cv2.addWeighted(overlay, 0.55, canvas, 0.45, 0, dst=canvas)

    for i, line in enumerate(lines):
        y = pad + line_height * (i + 1) - int(8 * scale)
        cv2.putText(
            canvas,
            line,
            (pad, y),
            cv2.FONT_HERSHEY_SIMPLEX,
            scale,
            (255, 255, 255),
            thickness,
            cv2.LINE_AA,
        )


def _fit_window(canvas: np.ndarray) -> None:
    height, width = canvas.shape[:2]
    if width > _MAX_WINDOW_WIDTH:
        height = round(height * _MAX_WINDOW_WIDTH / width)
        width = _MAX_WINDOW_WIDTH
    cv2.resizeWindow(WINDOW, width, height)
