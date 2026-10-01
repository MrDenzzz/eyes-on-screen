import asyncio
import logging
import threading
import time
from collections.abc import Callable

import numpy as np
import pytest

from eyes_on_screen.app import App
from eyes_on_screen.appletv.state import AppleTvError
from eyes_on_screen.config import load_config
from eyes_on_screen.logging_setup import EVENTS_LOGGER
from eyes_on_screen.settings import SettingsError
from eyes_on_screen.video.source import Frame, SourceStats
from eyes_on_screen.vision.analyzer import Box, FaceAnalyzer, FaceEstimate
from eyes_on_screen.vision.head_pose import HeadPose

LOOKING = HeadPose(yaw=0.0, pitch=0.0, roll=0.0)
AWAY = HeadPose(yaw=60.0, pitch=0.0, roll=0.0)


class LiveSource:
    """A camera that always has a fresh frame, stamped with the real clock."""

    def __init__(self) -> None:
        self._seq = 0
        self._lock = threading.Lock()

    def start(self):
        pass

    def stop(self):
        pass

    def wait_for_frame(self, newer_than, timeout):
        with self._lock:
            self._seq += 1
            return Frame(np.zeros((360, 640, 3), np.uint8), time.monotonic(), self._seq)

    def stats(self):
        return SourceStats("live", True, 640, 360, None, 20.0, self._seq, 0, None)


class Viewer:
    """One face in the middle of the frame whose head pose the test sets."""

    def __init__(self) -> None:
        self.pose: HeadPose | None = LOOKING

    def analyzer(self) -> FaceAnalyzer:
        return FaceAnalyzer(
            (0, 0, 1, 1),
            lambda image: [(Box(300, 160, 40, 40), 0.9)] if self.pose else [],
            lambda crop: FaceEstimate(self.pose) if self.pose else None,
            max_faces=3,
        )


def write_config(tmp_path, extra: str = ""):
    path = tmp_path / "config.yaml"
    path.write_text(
        "# mine\nvideo: {source: webcam, process_fps: 20}\n"
        "behavior: {pause_after_s: 0.3, resume_after_s: 0.2, face_lost_after_s: 0.5}\n" + extra,
        encoding="utf-8",
    )
    return path


def make_app(tmp_path, viewer=None, player=None, **kwargs) -> App:
    path = write_config(tmp_path)
    viewer = viewer or Viewer()
    return App(load_config(path), path, LiveSource(), viewer.analyzer(), player, **kwargs)


async def until(condition: Callable[[], bool], timeout: float = 3.0) -> None:
    deadline = time.monotonic() + timeout
    while not condition():
        assert time.monotonic() < deadline, "timed out"
        await asyncio.sleep(0.02)


def run_app(app: App, scenario) -> None:
    async def main():
        task = asyncio.create_task(app.run())
        try:
            await scenario()
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    asyncio.run(asyncio.wait_for(main(), 20))


class TestPipeline:
    def test_looking_away_pauses_and_looking_back_resumes(self, tmp_path, player):
        viewer = Viewer()
        app = make_app(tmp_path, viewer, player)

        async def scenario():
            await until(lambda: player.state is not None and app.room.viewers == 1)
            viewer.pose = AWAY
            await until(lambda: player.commands == ["pause"])
            viewer.pose = LOOKING
            await until(lambda: player.commands == ["pause", "play"])

        run_app(app, scenario)
        assert player.connected is False  # closed on the way out

    def test_nobody_there_pauses_too(self, tmp_path, player):
        viewer = Viewer()
        app = make_app(tmp_path, viewer, player)

        async def scenario():
            await until(lambda: player.state is not None and app.room.viewers == 1)
            viewer.pose = None
            await until(lambda: player.commands == ["pause"])

        run_app(app, scenario)

    def test_dry_run_only_logs(self, tmp_path, caplog, player):
        viewer = Viewer()
        app = make_app(tmp_path, viewer, player, dry_run=True)

        async def scenario():
            await until(lambda: player.state is not None and app.room.viewers == 1)
            viewer.pose = AWAY
            await until(lambda: "would pause" in caplog.text)
            await asyncio.sleep(0.5)

        with caplog.at_level(logging.INFO, logger=EVENTS_LOGGER):
            run_app(app, scenario)
        assert player.commands == []
        assert caplog.text.count("would pause") == 1

    def test_without_a_player_it_only_watches(self, tmp_path):
        viewer = Viewer()
        app = make_app(tmp_path, viewer)
        scenes = []

        class Listener:
            async def scene(self, scene):
                scenes.append(scene)

            def tick(self):
                pass

        app.listeners.append(Listener())

        async def scenario():
            await until(lambda: len(scenes) >= 3)

        run_app(app, scenario)
        assert scenes[-1].room.viewers == 1
        assert scenes[-1].focus is not None


class TestOperations:
    def test_settings_are_applied_live_and_saved(self, tmp_path):
        app = make_app(tmp_path)

        config = app.change_settings(
            {"behavior": {"pause_after_s": 2.5}, "target": {"roi": [0, 0, 0.5, 0.5]}}
        )

        assert config.behavior.pause_after_s == 2.5
        assert app.config is config
        assert app._analyzer.roi == (0, 0, 0.5, 0.5)
        saved = (tmp_path / "config.yaml").read_text(encoding="utf-8")
        assert "# mine" in saved
        assert "pause_after_s: 2.5" in saved

    def test_invalid_settings_are_rejected_and_nothing_changes(self, tmp_path):
        app = make_app(tmp_path)

        with pytest.raises(SettingsError, match=r"behavior\.pause_after_s"):
            app.change_settings({"behavior": {"pause_after_s": 0}})
        assert app.config.behavior.pause_after_s == 0.3

    def test_automation_switch(self, tmp_path):
        app = make_app(tmp_path)

        app.set_automation(False)

        assert app.automation is False

    def test_calibration_starts_with_a_countdown(self, tmp_path):
        app = make_app(tmp_path)

        app.start_calibration()

        assert app.calibration is not None
        assert app.calibration.counting_down(time.monotonic())

    def test_player_buttons_need_an_apple_tv(self, tmp_path):
        app = make_app(tmp_path)

        with pytest.raises(AppleTvError, match="no Apple TV is set up"):
            asyncio.run(app.press("pause"))

    def test_guided_recording_lasts_until_finished(self, tmp_path):
        app = make_app(tmp_path)

        app.start_recording_step(2)
        assert app.recording is not None
        progress = app.recording.progress(time.monotonic())
        assert progress is not None
        assert (progress.index, progress.phase) == (2, "countdown")

        app.finish_recording()
        assert app.recording is None
        [saved] = (tmp_path / "logs" / "recordings").glob("gaze-*.csv")
        assert app.shown_path(saved).startswith("logs/recordings/gaze-")
