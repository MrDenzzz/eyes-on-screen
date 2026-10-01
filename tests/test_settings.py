import re
from pathlib import Path

import pytest

from eyes_on_screen.config import MultipleViewers, load_config
from eyes_on_screen.settings import SettingsError, apply_changes, save_changes

CONFIG = """\
# my config
video:
  source: webcam
target:
  # the sofa
  roi: [0.1, 0.2, 0.8, 0.9]
behavior:
  pause_after_s: 1.5  # quick
"""


@pytest.fixture
def config_file(tmp_path) -> Path:
    path = tmp_path / "config.yaml"
    path.write_text(CONFIG, encoding="utf-8")
    return path


def test_valid_changes_give_a_new_validated_config(config_file):
    config = load_config(config_file)

    changed = apply_changes(
        config,
        {
            "behavior": {"pause_after_s": 2.5, "multiple_viewers": "all_away"},
            "target": {"roi": [0.0, 0.1, 0.5, 0.6]},
        },
    )

    assert changed.behavior.pause_after_s == 2.5
    assert changed.behavior.multiple_viewers is MultipleViewers.ALL_AWAY
    assert changed.target.roi == (0.0, 0.1, 0.5, 0.6)
    assert config.behavior.pause_after_s == 1.5  # the original is untouched


def test_only_ui_settings_can_be_changed(config_file):
    with pytest.raises(SettingsError, match=r"video\.rtsp_url cannot be changed"):
        apply_changes(load_config(config_file), {"video": {"rtsp_url": "rtsp://elsewhere/x"}})


def test_invalid_values_are_rejected_with_the_key(config_file):
    with pytest.raises(SettingsError, match=r"behavior\.pause_after_s"):
        apply_changes(load_config(config_file), {"behavior": {"pause_after_s": -1}})


def test_saving_keeps_comments_and_inline_lists_and_adds_missing_keys(config_file):
    changes = {
        "behavior": {"pause_after_s": 2.25, "multiple_viewers": "nearest"},
        "target": {"roi": [0.0, 0.1, 0.5, 0.6]},
        "pose": {"yaw_center_deg": 3.14159},
    }
    changed = apply_changes(load_config(config_file), changes)

    save_changes(config_file, changed, changes)

    text = config_file.read_text(encoding="utf-8")
    assert "# my config" in text
    assert "# the sofa" in text
    # ruamel keeps the comment's column, so a longer value eats a space before it.
    assert re.search(r"pause_after_s: 2\.25\s+# quick", text)
    assert "roi: [0.0, 0.1, 0.5, 0.6]" in text
    assert "multiple_viewers: nearest" in text
    assert "yaw_center_deg: 3.142" in text
    reloaded = load_config(config_file)
    assert reloaded.behavior.multiple_viewers is MultipleViewers.NEAREST
    assert reloaded.pose.yaw_center_deg == pytest.approx(3.142)
    assert not config_file.with_name("config.yaml.tmp").exists()
