import re
from pathlib import Path

import pytest

from eyes_on_screen import cli
from eyes_on_screen.config import ConfigError, FaceLostAction, VideoSourceKind, load_config

REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_CONFIG = REPO_ROOT / "config.example.yaml"

MINIMAL = "video: {source: webcam}\n"


def write_config(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "config.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_example_config_is_valid():
    config = load_config(EXAMPLE_CONFIG)

    assert config.video.source is VideoSourceKind.RTSP
    assert config.behavior.pause_after_s == 1.5
    assert config.behavior.resume_after_s == 0.5
    assert config.behavior.on_face_lost is FaceLostAction.PAUSE
    assert config.apple_tv.identifier is None


def test_missing_sections_get_defaults(tmp_path):
    config = load_config(write_config(tmp_path, MINIMAL))

    assert config.video.process_fps == 10
    assert config.target.roi == (0.0, 0.0, 1.0, 1.0)
    assert config.behavior.on_face_lost is FaceLostAction.PAUSE


def test_relative_paths_are_resolved_against_config_folder(tmp_path):
    config = load_config(write_config(tmp_path, MINIMAL))

    base = tmp_path.resolve()
    assert config.detection.models_dir == base / "models"
    assert config.apple_tv.credentials_file == base / "data" / "pyatv.conf"
    assert config.logging.events_file == base / "logs" / "events.log"


def test_absolute_paths_are_kept(tmp_path):
    models = (tmp_path / "elsewhere" / "models").resolve()
    text = MINIMAL + f"detection: {{models_dir: '{models.as_posix()}'}}\n"

    config = load_config(write_config(tmp_path, text))

    assert config.detection.models_dir == models


def test_events_file_can_be_disabled(tmp_path):
    config = load_config(write_config(tmp_path, MINIMAL + "logging: {events_file: null}\n"))

    assert config.logging.events_file is None


def test_blank_identifier_means_not_set_and_value_is_trimmed(tmp_path):
    blank = load_config(write_config(tmp_path, MINIMAL + "apple_tv: {identifier: '  '}\n"))
    padded = load_config(write_config(tmp_path, MINIMAL + "apple_tv: {identifier: ' AA:BB '}\n"))

    assert blank.apple_tv.identifier is None
    assert padded.apple_tv.identifier == "AA:BB"


def test_log_level_is_case_insensitive(tmp_path):
    config = load_config(write_config(tmp_path, MINIMAL + "logging: {level: debug}\n"))

    assert config.logging.level == "DEBUG"


@pytest.mark.parametrize(
    ("text", "location"),
    [
        pytest.param("{}", "video", id="video-section-required"),
        pytest.param("video: {source: rtsp}", "video", id="rtsp-without-url"),
        pytest.param(
            "video: {source: rtsp, rtsp_url: 'http://cam/stream'}",
            "video.rtsp_url",
            id="url-not-rtsp",
        ),
        pytest.param("video: {source: hdmi}", "video.source", id="unknown-source"),
        pytest.param(MINIMAL + "target: {roi: [0.6, 0, 0.4, 1]}", "target.roi", id="roi-flipped"),
        pytest.param(MINIMAL + "target: {roi: [0, 0, 1.2, 1]}", "target.roi", id="roi-outside"),
        pytest.param(MINIMAL + "target: {roi: [0, 0, 1]}", "target.roi", id="roi-short"),
        pytest.param(
            MINIMAL + "behavior: {on_face_lost: stop}",
            "behavior.on_face_lost",
            id="unknown-face-lost-action",
        ),
        pytest.param(
            MINIMAL + "behavior: {pause_after_s: 0}", "behavior.pause_after_s", id="zero-delay"
        ),
        pytest.param(MINIMAL + "behaviour: {}", "behaviour", id="typo-in-section"),
        pytest.param(
            "video: {source: rtsp, rtsp_url: 'rtsp://10.0.0.5:8554/cam'}\n"
            "go2rtc: {autostart: true}",
            "<root>",
            id="go2rtc-autostart-for-remote-stream",
        ),
        pytest.param(MINIMAL + "pose: {yaw_tolerence_deg: 5}", "pose.yaw_tolerence_deg", id="typo"),
    ],
)
def test_invalid_config_names_the_offending_key(tmp_path, text, location):
    # The key may be followed by an item index, e.g. "target.roi.3: Field required".
    with pytest.raises(ConfigError, match=re.escape(f"- {location}") + r"[.:]"):
        load_config(write_config(tmp_path, text))


def test_missing_file_is_reported(tmp_path):
    with pytest.raises(ConfigError, match="not found"):
        load_config(tmp_path / "nope.yaml")


@pytest.mark.parametrize(
    "text", [pytest.param("video: [unclosed", id="bad-yaml"), pytest.param("- a\n- b", id="list")]
)
def test_malformed_file_is_reported(tmp_path, text):
    with pytest.raises(ConfigError, match="invalid"):
        load_config(write_config(tmp_path, text))


def test_config_is_immutable(tmp_path):
    config = load_config(write_config(tmp_path, MINIMAL))

    with pytest.raises(ValueError, match="frozen"):
        config.video.process_fps = 30  # type: ignore[misc]


class TestConfigCheckCommand:
    @pytest.fixture(autouse=True)
    def _no_logging_setup(self, monkeypatch):
        # Global logging handlers would outlive the test and hold files in tmp_path open.
        monkeypatch.setattr(cli, "setup_logging", lambda *args, **kwargs: None)

    def test_valid_config_prints_effective_values(self, tmp_path, capsys):
        path = write_config(tmp_path, MINIMAL)

        exit_code = cli.main(["--config", str(path), "config-check"])

        out = capsys.readouterr().out
        assert exit_code == cli.EXIT_OK
        assert "Config OK" in out
        assert "video:\n  source: webcam\n" in out  # sections stay block-style
        assert "  roi: [0.0, 0.0, 1.0, 1.0]\n" in out  # lists stay inline
        assert "apple_tv.identifier is not set" in out

    def test_invalid_config_fails_with_message(self, tmp_path, capsys):
        path = write_config(tmp_path, "video: {source: rtsp}")

        exit_code = cli.main(["--config", str(path), "config-check"])

        assert exit_code == cli.EXIT_CONFIG_ERROR
        assert "rtsp_url is required" in capsys.readouterr().err
