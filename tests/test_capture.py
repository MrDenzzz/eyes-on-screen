import threading
import time
from collections.abc import Callable

import cv2
import numpy as np
import pytest

from eyes_on_screen.config import VideoConfig
from eyes_on_screen.video import capture as capture_module
from eyes_on_screen.video.capture import CaptureError, CaptureSource, create_source, redact_url

FRAME_SHAPE = (4, 6, 3)
HEVC = float(int.from_bytes(b"hevc", "little"))


class FakeCapture:
    """Delivers `frames` frames (None = endless), then reports a failed read.

    With `stall_at=n`, the read of the n-th frame blocks for `stall_s` first.
    """

    def __init__(
        self,
        frames: int | None,
        fourcc: float = HEVC,
        stall_at: int | None = None,
        stall_s: float = 0.0,
    ) -> None:
        self.remaining = frames
        self.fourcc = fourcc
        self.stall_at = stall_at
        self.stall_s = stall_s
        self.reads = 0
        self.released = False

    def read(self) -> tuple[bool, np.ndarray | None]:
        self.reads += 1
        time.sleep(self.stall_s if self.reads == self.stall_at else 0.001)
        if self.remaining is not None:
            if self.remaining <= 0:
                return False, None
            self.remaining -= 1
        return True, np.zeros(FRAME_SHAPE, np.uint8)

    def get(self, prop_id: int) -> float:
        return self.fourcc if prop_id == cv2.CAP_PROP_FOURCC else 0.0

    def release(self) -> None:
        self.released = True


class ScriptedOpener:
    """Opens the given captures in order; raises CaptureError for `None` and when exhausted."""

    def __init__(self, *captures: FakeCapture | None) -> None:
        self.script = list(captures)
        self.opened: list[FakeCapture] = []
        self.attempts = 0
        self.lock = threading.Lock()

    def __call__(self) -> FakeCapture:
        with self.lock:
            self.attempts += 1
            capture = self.script.pop(0) if self.script else None
        if capture is None:
            raise CaptureError("camera offline")
        self.opened.append(capture)
        return capture


def wait_until(predicate: Callable[[], bool], timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() > deadline:
            pytest.fail("condition not reached in time")
        time.sleep(0.005)


@pytest.fixture
def make_source():
    sources: list[CaptureSource] = []

    def make(opener: ScriptedOpener) -> CaptureSource:
        source = CaptureSource("fake", opener, reconnect_delay_s=0.01)
        sources.append(source)
        source.start()
        return source

    yield make
    for source in sources:
        source.stop()


def test_returns_only_frames_newer_than_requested(make_source):
    source = make_source(ScriptedOpener(FakeCapture(frames=5)))

    first = source.wait_for_frame(newer_than=-1, timeout=1)
    assert first is not None
    wait_until(lambda: source.stats().frames == 5)

    latest = source.wait_for_frame(newer_than=first.seq, timeout=1)
    assert latest is not None
    assert latest.seq == 5  # stale frames in between are skipped, not queued
    assert source.wait_for_frame(newer_than=latest.seq, timeout=0.05) is None


def test_reconnects_after_stream_loss_and_keeps_seq_growing(make_source):
    opener = ScriptedOpener(FakeCapture(frames=3), None, FakeCapture(frames=3))
    source = make_source(opener)

    # The 5th attempt only starts after the 4th failure has been fully recorded.
    wait_until(lambda: source.stats().frames == 6 and opener.attempts >= 5)

    stats = source.stats()
    assert stats.reconnects == 2
    assert not stats.connected
    assert stats.last_error == "camera offline"
    assert all(capture.released for capture in opener.opened)


def test_frame_after_a_stall_is_dropped_and_the_stream_reopened(make_source, monkeypatch, caplog):
    monkeypatch.setattr(capture_module, "READ_TIMEOUT_S", 0.05)
    opener = ScriptedOpener(FakeCapture(frames=None, stall_at=3, stall_s=0.3))
    source = make_source(opener)

    wait_until(lambda: opener.attempts >= 3)

    stats = source.stats()
    assert stats.frames == 2  # the 3rd frame came after the stall: stale, never published
    assert stats.reconnects == 1
    assert "stream stalled" in caplog.text


def test_retries_until_the_camera_comes_online(make_source):
    source = make_source(ScriptedOpener(None, None, FakeCapture(frames=None)))

    assert source.wait_for_frame(newer_than=-1, timeout=1) is not None
    stats = source.stats()
    assert stats.connected
    assert stats.last_error is None
    assert stats.reconnects == 0


def test_stats_describe_the_stream(make_source):
    source = make_source(ScriptedOpener(FakeCapture(frames=None)))

    # fps needs frames spread over more than one clock tick (~15 ms on Windows).
    wait_until(lambda: source.stats().fps > 0)

    stats = source.stats()
    assert (stats.width, stats.height) == (FRAME_SHAPE[1], FRAME_SHAPE[0])
    assert stats.codec == "hevc"


def test_unknown_codec_is_reported_as_none(make_source):
    source = make_source(ScriptedOpener(FakeCapture(frames=None, fourcc=0.0)))

    wait_until(lambda: source.stats().connected)

    assert source.stats().codec is None


def test_stop_ends_the_reader_thread_and_releases_the_capture():
    capture = FakeCapture(frames=None)
    source = CaptureSource("fake", ScriptedOpener(capture), reconnect_delay_s=0.01)
    source.start()
    wait_until(lambda: source.stats().connected)

    source.stop()

    assert capture.released
    assert not source.stats().connected
    assert not any(t.name == "video-capture" and t.is_alive() for t in threading.enumerate())


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("rtsp://127.0.0.1:8554/c400", "rtsp://127.0.0.1:8554/c400"),
        ("rtsp://admin:secret@10.0.0.5:554/live", "rtsp://admin:***@10.0.0.5:554/live"),
        ("rtsp://admin:p%40ss@cam/live?x=1", "rtsp://admin:***@cam/live?x=1"),
        ("rtsp://user@cam/live", "rtsp://user@cam/live"),
    ],
)
def test_redact_url_hides_only_the_password(url, expected):
    assert redact_url(url) == expected


def test_create_source_describes_the_configured_source():
    rtsp = create_source(VideoConfig(source="rtsp", rtsp_url="rtsp://u:pw@cam/s"))
    webcam = create_source(VideoConfig(source="webcam", webcam_index=1))

    assert rtsp.stats().description == "rtsp://u:***@cam/s"
    assert webcam.stats().description == "webcam #1"
