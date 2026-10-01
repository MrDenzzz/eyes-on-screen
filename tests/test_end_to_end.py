"""Video file -> real face models -> state machine -> player, end to end.

The clip is generated from a public-domain portrait (tests/data): the painted face is
"looking at the screen", its mirror image is the same head turned the other way. The
models come from `eos download-models`; without them these tests are skipped, unless
EOS_REQUIRE_MODELS is set (CI), where a missing model is a failure.
"""

import asyncio
import contextlib
import logging
import os
import time
from pathlib import Path

import cv2
import numpy as np
import pytest

from eyes_on_screen.app import App
from eyes_on_screen.config import DetectionConfig, load_config
from eyes_on_screen.logging_setup import EVENTS_LOGGER
from eyes_on_screen.video.capture import create_source
from eyes_on_screen.vision.backends import create_face_analyzer
from eyes_on_screen.vision.models import missing_models

REPO_ROOT = Path(__file__).resolve().parents[1]
MODELS_DIR = REPO_ROOT / "models"
FACE = Path(__file__).parent / "data" / "face.jpg"
FPS = 10
SIZE = (640, 360)
FACE_HEIGHT = 120

if missing_models(MODELS_DIR) and not os.environ.get("EOS_REQUIRE_MODELS"):
    pytest.skip("face models not downloaded (eos download-models)", allow_module_level=True)


def frame_with(face: np.ndarray | None) -> np.ndarray:
    width, height = SIZE
    canvas = np.full((height, width, 3), 70, np.uint8)
    if face is not None:
        h, w = face.shape[:2]
        y, x = (height - h) // 2, (width - w) // 2
        canvas[y : y + h, x : x + w] = face
    return canvas


def poses():
    image = cv2.imread(str(FACE))
    scale = FACE_HEIGHT / image.shape[0]
    looking = cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    return {"looking": looking, "away": cv2.flip(looking, 1), "nobody": None}


def write_clip(path: Path, segments: list[tuple[str, float]]) -> None:
    faces = poses()
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter.fourcc(*"MJPG"), FPS, SIZE)
    for kind, seconds in segments:
        image = frame_with(faces[kind])
        for _ in range(round(seconds * FPS)):
            writer.write(image)
    writer.release()


def measured_yaw(face: np.ndarray) -> float:
    analyzer = create_face_analyzer(DetectionConfig(models_dir=MODELS_DIR), (0, 0, 1, 1))
    with contextlib.closing(analyzer):
        [found] = analyzer.analyze(frame_with(face))
    assert found.pose is not None
    return found.pose.yaw


@pytest.fixture(scope="module")
def screen_yaw() -> tuple[float, float]:
    """Yaw of the face as painted (the screen direction) and of its mirror image."""
    faces = poses()
    looking, away = measured_yaw(faces["looking"]), measured_yaw(faces["away"])
    assert abs(away - looking) > 30, "the mirrored face must read as a turned head"
    return looking, away


def run_eos(tmp_path: Path, segments, screen_yaw, player, until) -> None:
    write_clip(tmp_path / "clip.avi", segments)
    looking, away = screen_yaw
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        f"""
video: {{source: file, file: clip.avi, process_fps: {FPS}}}
detection: {{models_dir: "{MODELS_DIR.as_posix()}"}}
pose:
  yaw_center_deg: {looking:.1f}
  yaw_tolerance_deg: {abs(away - looking) / 2:.1f}
  pitch_tolerance_deg: 25
behavior: {{pause_after_s: 0.8, resume_after_s: 0.5, face_lost_after_s: 1.0}}
web: {{enabled: false}}
logging: {{events_file: null}}
""",
        encoding="utf-8",
    )
    config = load_config(config_path)
    analyzer = create_face_analyzer(config.detection, config.target.roi)
    source = create_source(config.video)
    app = App(config, config_path, source, analyzer, player)

    async def main() -> None:
        task = asyncio.create_task(app.run())
        deadline = time.monotonic() + 30
        try:
            while not until():
                assert not task.done(), "eos stopped on its own"
                assert time.monotonic() < deadline, f"timed out; commands: {player.commands}"
                await asyncio.sleep(0.05)
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    source.start()
    try:
        asyncio.run(main())
    finally:
        source.stop()
        analyzer.close()


def test_looking_away_pauses_and_looking_back_resumes(tmp_path, screen_yaw, player, caplog):
    segments = [("looking", 2.0), ("away", 2.5), ("looking", 3.0)]

    with caplog.at_level(logging.INFO, logger=EVENTS_LOGGER):
        run_eos(tmp_path, segments, screen_yaw, player, lambda: len(player.commands) >= 2)

    assert player.commands[:2] == ["pause", "play"]
    assert "paused: looked away" in caplog.text
    assert "resumed: looking at the screen" in caplog.text


def test_leaving_the_sofa_pauses(tmp_path, screen_yaw, player, caplog):
    segments = [("looking", 2.0), ("nobody", 3.0)]

    with caplog.at_level(logging.INFO, logger=EVENTS_LOGGER):
        run_eos(tmp_path, segments, screen_yaw, player, lambda: len(player.commands) >= 1)

    assert player.commands[0] == "pause"
    assert "paused: no viewer" in caplog.text
