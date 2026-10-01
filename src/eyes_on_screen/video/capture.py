"""OpenCV-backed video sources (RTSP from go2rtc, a webcam, a video file), read on a thread."""

from __future__ import annotations

import logging
import os
import threading
import time
from collections import deque
from collections.abc import Callable
from pathlib import Path
from typing import Protocol
from urllib.parse import urlsplit, urlunsplit

import cv2
import numpy as np

from eyes_on_screen.config import VideoConfig, VideoSourceKind
from eyes_on_screen.video.source import Frame, SourceStats

log = logging.getLogger(__name__)

OPEN_TIMEOUT_S = 10.0
# A dead stream must not block the reader forever, otherwise reconnect never happens.
# Also the longest gap between frames we accept: when the RTSP feed dies, OpenCV's read
# times out and then hands out frames still buffered in the decoder, stamped as new.
# A frame arriving after such a gap is stale, so the session is reopened instead.
READ_TIMEOUT_S = 3.0
# A live HEVC stream joined between key frames decodes to flat grey until the next key
# frame (up to 3 s on the C400). Such frames are skipped after every (re)connect, but
# for no longer than this, so a genuinely grey scene can never block the stream.
WARMUP_MAX_S = 8.0
# Frames older than this mean the stream stalled, so the measured fps drops to 0.
_STALL_AFTER_S = 1.0
_FPS_WINDOW = 30
_DEFAULT_FILE_FPS = 25.0


class CaptureError(Exception):
    """The stream or device could not be opened."""


class Capture(Protocol):
    """The part of cv2.VideoCapture used here; tests substitute a fake."""

    def read(self) -> tuple[bool, np.ndarray | None]: ...

    def get(self, prop_id: int) -> float: ...

    def set(self, prop_id: int, value: float) -> bool: ...

    def release(self) -> None: ...


class CaptureSource:
    """VideoSource over an OpenCV capture: keeps only the newest frame, reopens on failure."""

    def __init__(
        self,
        description: str,
        open_capture: Callable[[], Capture],
        reconnect_delay_s: float,
    ) -> None:
        self._description = description
        self._open_capture = open_capture
        self._reconnect_delay_s = reconnect_delay_s
        self._stopping = threading.Event()
        self._thread: threading.Thread | None = None
        self._consecutive_failures = 0  # reader thread only

        # Everything below is shared with consumers and guarded by _cond.
        self._cond = threading.Condition()
        self._latest: Frame | None = None
        self._seq = 0
        self._connected = False
        self._codec: str | None = None
        self._frame_times: deque[float] = deque(maxlen=_FPS_WINDOW)
        self._reconnects = 0
        self._last_error: str | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stopping.clear()
        self._thread = threading.Thread(target=self._run, name="video-capture", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stopping.set()
        with self._cond:
            self._cond.notify_all()
        if self._thread is not None:
            # Bounded by the read timeout; the thread is a daemon, so a hung open
            # cannot keep the process alive either.
            self._thread.join(timeout=READ_TIMEOUT_S + 1)
            self._thread = None

    def wait_for_frame(self, newer_than: int, timeout: float) -> Frame | None:
        def has_newer() -> bool:
            return self._latest is not None and self._latest.seq > newer_than

        with self._cond:
            if not self._cond.wait_for(has_newer, timeout):
                return None
            return self._latest

    def stats(self) -> SourceStats:
        with self._cond:
            latest = self._latest
            return SourceStats(
                description=self._description,
                connected=self._connected,
                width=latest.image.shape[1] if latest is not None else None,
                height=latest.image.shape[0] if latest is not None else None,
                codec=self._codec,
                fps=self._measured_fps(),
                frames=self._seq,
                reconnects=self._reconnects,
                last_error=self._last_error,
            )

    def _measured_fps(self) -> float:
        times = self._frame_times
        if len(times) < 2 or time.monotonic() - times[-1] > _STALL_AFTER_S:
            return 0.0
        # On Windows (Python 3.12) monotonic() ticks every ~15 ms, so frames can share a timestamp.
        span = times[-1] - times[0]
        return (len(times) - 1) / span if span > 0 else 0.0

    def _run(self) -> None:
        while not self._stopping.is_set():
            try:
                capture = self._open_capture()
            except CaptureError as exc:
                error = str(exc)
            else:
                try:
                    error = self._read_until_failure(capture)
                finally:
                    capture.release()

            if self._stopping.is_set():
                break
            self._on_failure(error)
            self._stopping.wait(self._reconnect_delay_s)

        with self._cond:
            self._connected = False

    def _read_until_failure(self, capture: Capture) -> str:
        """Publish frames until reading fails; return the reason."""
        previous: float | None = None
        warmup_until: float | None = time.monotonic() + WARMUP_MAX_S
        skipped = 0
        while not self._stopping.is_set():
            ok, image = capture.read()
            now = time.monotonic()
            if not ok or image is None:
                return "no frame received (stream ended or read timed out)"
            if previous is not None and now - previous > READ_TIMEOUT_S:
                return f"stream stalled for {now - previous:.1f}s"
            previous = now

            if warmup_until is not None:
                if now < warmup_until and _looks_undecoded(image):
                    skipped += 1
                    continue
                warmup_until = None
                if skipped:
                    log.debug("Skipped %d undecoded frames before the first key frame", skipped)

            with self._cond:
                if not self._connected:
                    self._on_connected(capture, image)
                self._seq += 1
                self._latest = Frame(image=image, timestamp=now, seq=self._seq)
                self._frame_times.append(now)
                self._cond.notify_all()
        return "stopped"

    def _on_connected(self, capture: Capture, image: np.ndarray) -> None:
        # Called with _cond held.
        self._connected = True
        self._last_error = None
        self._consecutive_failures = 0
        self._codec = _fourcc_to_str(capture.get(cv2.CAP_PROP_FOURCC))
        height, width = image.shape[:2]
        log.info(
            "Connected to %s (%dx%d, codec %s)",
            self._description,
            width,
            height,
            self._codec or "unknown",
        )

    def _on_failure(self, error: str) -> None:
        with self._cond:
            if self._connected:
                self._reconnects += 1
            self._connected = False
            self._last_error = error
            self._frame_times.clear()
        self._consecutive_failures += 1
        # Report the first failure loudly; a camera that stays offline should not
        # flood the log with the same warning every few seconds.
        level = logging.WARNING if self._consecutive_failures == 1 else logging.DEBUG
        log.log(
            level,
            "%s: %s; retrying every %.1fs",
            self._description,
            error,
            self._reconnect_delay_s,
        )


def open_rtsp(url: str) -> cv2.VideoCapture:
    # TCP instead of UDP: a lost packet corrupts HEVC reference frames for the whole GOP.
    # Must be set before the first capture is opened; an explicit user setting wins.
    os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", "rtsp_transport;tcp")
    params = [
        cv2.CAP_PROP_OPEN_TIMEOUT_MSEC,
        int(OPEN_TIMEOUT_S * 1000),
        cv2.CAP_PROP_READ_TIMEOUT_MSEC,
        int(READ_TIMEOUT_S * 1000),
    ]
    capture = cv2.VideoCapture(url, cv2.CAP_FFMPEG, params)
    if not capture.isOpened():
        capture.release()
        raise CaptureError(f"cannot open {redact_url(url)}")
    return capture


def open_webcam(index: int) -> cv2.VideoCapture:
    capture = cv2.VideoCapture(index)
    if not capture.isOpened():
        capture.release()
        raise CaptureError(f"cannot open webcam #{index}")
    return capture


class PacedFile:
    """A video file read like a camera: at its own frame rate, from the start again at the end."""

    def __init__(self, capture: Capture, clock: Callable[[], float] = time.monotonic) -> None:
        self._capture = capture
        self._clock = clock
        fps = capture.get(cv2.CAP_PROP_FPS)
        self._period = 1.0 / (fps if fps > 0 else _DEFAULT_FILE_FPS)
        self._due: float | None = None

    def read(self) -> tuple[bool, np.ndarray | None]:
        now = self._clock()
        if self._due is not None and now < self._due:
            time.sleep(self._due - now)
        # Falling behind (slow decode) drops the backlog instead of rushing to catch up.
        self._due = max((self._due or now) + self._period, self._clock())
        ok, image = self._capture.read()
        if not ok:
            self._capture.set(cv2.CAP_PROP_POS_FRAMES, 0)
            ok, image = self._capture.read()
        return ok, image

    def get(self, prop_id: int) -> float:
        return self._capture.get(prop_id)

    def set(self, prop_id: int, value: float) -> bool:
        return self._capture.set(prop_id, value)

    def release(self) -> None:
        self._capture.release()


def open_file(path: Path) -> PacedFile:
    capture = cv2.VideoCapture(str(path))
    if not capture.isOpened():
        capture.release()
        raise CaptureError(f"cannot open video file {path}")
    return PacedFile(capture)


def create_source(config: VideoConfig) -> CaptureSource:
    if config.source is VideoSourceKind.RTSP:
        url = config.rtsp_url
        assert url is not None, "guaranteed by config validation"
        return CaptureSource(redact_url(url), lambda: open_rtsp(url), config.reconnect_delay_s)
    if config.source is VideoSourceKind.FILE:
        path = config.file
        assert path is not None, "guaranteed by config validation"
        return CaptureSource(
            f"video file {path.name}", lambda: open_file(path), config.reconnect_delay_s
        )

    index = config.webcam_index
    return CaptureSource(f"webcam #{index}", lambda: open_webcam(index), config.reconnect_delay_s)


def redact_url(url: str) -> str:
    """Hide the password in rtsp://user:password@host/... so the URL is safe to log."""
    parts = urlsplit(url)
    if parts.password is None:
        return url
    userinfo, _, hostport = parts.netloc.rpartition("@")
    user = userinfo.split(":", 1)[0]
    return urlunsplit(parts._replace(netloc=f"{user}:***@{hostport}"))


def _looks_undecoded(image: np.ndarray) -> bool:
    """True for the flat mid-grey picture a decoder emits while reference frames are missing."""
    sample = image[::8, ::8].astype(np.int16)
    colourless = (sample.max(axis=2) - sample.min(axis=2)) < 6
    mid_grey = np.abs(sample.mean(axis=2) - 128) < 10
    # Measured on the C400: ~0.98 before the first key frame, ~0.03 right after it.
    return bool(np.mean(colourless & mid_grey) > 0.9)


def _fourcc_to_str(value: float) -> str | None:
    code = int(value)
    text = "".join(chr((code >> (8 * i)) & 0xFF) for i in range(4)).strip("\x00 ")
    return text if text.isprintable() and text else None
