"""Changing settings at runtime (from the web UI) and writing them back to config.yaml."""

from __future__ import annotations

import os
from collections.abc import Mapping
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import ValidationError
from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap

from eyes_on_screen.config import AppConfig

Changes = Mapping[str, Mapping[str, Any]]
"""{"section": {"key": value}}, e.g. {"behavior": {"pause_after_s": 2.0}}."""

# What the UI may change. Everything else (paths, devices, ports) stays file-only.
EDITABLE = {
    "target": {"roi"},
    "pose": {"yaw_center_deg", "pitch_center_deg", "yaw_tolerance_deg", "pitch_tolerance_deg"},
    "behavior": {
        "pause_after_s",
        "resume_after_s",
        "on_face_lost",
        "face_lost_after_s",
        "multiple_viewers",
    },
}


class SettingsError(Exception):
    """A change was rejected. User-facing message."""


def apply_changes(config: AppConfig, changes: Changes) -> AppConfig:
    """A validated copy of `config` with `changes` applied; rejects non-editable keys."""
    data = config.model_dump()
    for section, values in changes.items():
        for key, value in values.items():
            if key not in EDITABLE.get(section, set()):
                raise SettingsError(f"{section}.{key} cannot be changed here")
            data[section][key] = value
    try:
        return AppConfig.model_validate(data)
    except ValidationError as exc:
        details = "; ".join(
            f"{'.'.join(str(p) for p in error['loc'])}: {error['msg']}" for error in exc.errors()
        )
        raise SettingsError(details) from None


def save_changes(path: Path, config: AppConfig, changes: Changes) -> None:
    """Write the changed keys, with their validated values, into the YAML file.

    Comments, key order and inline lists are kept (round-trip YAML), so the file
    still reads like the hand-written one.
    """
    yaml = YAML()
    yaml.preserve_quotes = True
    data = yaml.load(path.read_text(encoding="utf-8")) or CommentedMap()

    for section, values in changes.items():
        node = data.get(section)
        if node is None:
            node = data[section] = CommentedMap()
        for key in values:
            value = _plain(getattr(getattr(config, section), key))
            current = node.get(key)
            if isinstance(value, list) and isinstance(current, list) and len(current) == len(value):
                current[:] = value  # in place: keeps `[a, b, c]` on one line
            else:
                node[key] = value

    # Write next to the file and swap, so a crash never leaves half a config behind.
    partial = path.with_name(path.name + ".tmp")
    with partial.open("w", encoding="utf-8") as file:
        yaml.dump(data, file)
    os.replace(partial, path)


def _plain(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, tuple):
        return [_plain(item) for item in value]
    if isinstance(value, float):
        return round(value, 3)
    return value
