"""Messages between `eos run` and the web UI, as pydantic models.

The WebSocket pushes StatusMessage, binary frames (FrameHeader + JPEG) and
EventsMessage; the REST API (web/server.py) takes SettingsChanges and AutomationUpdate
and lists the steps of a guided recording (RecordingStepInfo).
These models are the single source of truth: FastAPI validates requests and documents
them (OpenAPI at /api/docs), and their JSON Schema becomes the frontend's TypeScript
types (`frontend/src/protocol`). Regenerate after a change:

    uv run python -m eyes_on_screen.web.messages frontend/src/protocol/schema.json
    npm --prefix frontend run gen:types
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, create_model
from pydantic.json_schema import models_json_schema

from eyes_on_screen.appletv.state import Playback
from eyes_on_screen.attention.classifier import Attention
from eyes_on_screen.attention.state_machine import PlaybackCommand
from eyes_on_screen.config import BehaviorConfig, PoseConfig
from eyes_on_screen.settings import EDITABLE

Roi = tuple[float, float, float, float]


class _Message(BaseModel):
    # Fields with defaults (like `type`) are always present in what the server sends,
    # so they are required in the serialization schema the frontend types come from.
    model_config = ConfigDict(extra="forbid", json_schema_serialization_defaults_required=True)


# Server -> page


class StreamInfo(_Message):
    connected: bool
    width: int | None
    height: int | None
    fps: float
    error: str | None


class AnalysisInfo(_Message):
    fps: float
    ms: float


class PlayerInfo(_Message):
    configured: bool
    """False until an Apple TV is set up: eos then only watches."""
    connected: bool
    name: str | None
    playback: Playback | None
    app: str | None
    title: str | None


class RoomInfo(_Message):
    attention: Attention
    viewers: int
    looking: int


class MachineInfo(_Message):
    streak_s: float
    paused_by_us: bool
    armed: bool
    pending: PlaybackCommand | None
    skipped: PlaybackCommand | None


class AutomationInfo(_Message):
    enabled: bool
    dry_run: bool


class CalibrationInfo(_Message):
    phase: Literal["countdown", "collecting"]
    remaining_s: float
    phase_s: float


class RecordingStepInfo(_Message):
    label: str
    title: str
    instruction: str
    duration_s: float


class RecordingProgress(_Message):
    index: int
    phase: Literal["countdown", "recording"]
    remaining_s: float
    phase_s: float
    frames: int
    with_face: int


class RecordingResult(_Message):
    index: int
    take: int
    frames: int
    with_face: int


class RecordingInfo(_Message):
    file: str
    current: RecordingProgress | None
    done: list[RecordingResult]
    """The latest take of every finished step, by step."""
    last: int | None
    """The step finished most recently."""


class SettingsInfo(_Message):
    roi: Roi
    pose: PoseConfig
    behavior: BehaviorConfig


class StatusMessage(_Message):
    type: Literal["status"] = "status"
    stream: StreamInfo
    analysis: AnalysisInfo
    player: PlayerInfo
    room: RoomInfo
    machine: MachineInfo
    automation: AutomationInfo
    calibration: CalibrationInfo | None
    recording: RecordingInfo | None
    settings: SettingsInfo


class FaceInfo(_Message):
    box: Roi
    """Normalized (x1, y1, x2, y2) in the frame."""
    state: Literal["looking", "away", "ignored"]
    yaw: float | None
    pitch: float | None
    eyes_down: float | None
    focus: bool


class FrameHeader(_Message):
    """JSON header of a binary frame message; the JPEG follows it."""

    seq: int
    ts: int
    """Wall-clock milliseconds, the same clock as event timestamps."""
    attention: Attention
    faces: list[FaceInfo]


class EventInfo(_Message):
    ts: int
    time: str
    level: Literal["info", "warning"]
    kind: Literal["pause", "resume", "player", "calibration", "other"]
    text: str


class EventsMessage(_Message):
    type: Literal["events"] = "events"
    events: list[EventInfo]


# Page -> server (REST request bodies)


def _partial(name: str, model: type[BaseModel], keys: set[str]) -> type[BaseModel]:
    """Optional copies of the editable fields of a config section."""
    fields: dict[str, Any] = {
        key: (model.model_fields[key].annotation | None, None) for key in sorted(keys)
    }
    return create_model(name, __base__=_Message, **fields)


PoseChanges = _partial("PoseChanges", PoseConfig, EDITABLE["pose"])
BehaviorChanges = _partial("BehaviorChanges", BehaviorConfig, EDITABLE["behavior"])


class TargetChanges(_Message):
    roi: Roi | None = None


class SettingsChanges(_Message):
    target: TargetChanges | None = None
    pose: PoseChanges | None = None  # type: ignore[valid-type]
    behavior: BehaviorChanges | None = None  # type: ignore[valid-type]

    def as_changes(self) -> dict[str, dict[str, Any]]:
        """{section: {key: value}} with only the keys that were sent."""
        return {
            section: values
            for section, values in self.model_dump(exclude_none=True).items()
            if values
        }


class AutomationUpdate(_Message):
    enabled: bool


def protocol_schema() -> dict[str, Any]:
    """One JSON Schema with every message, shaped for json-schema-to-typescript.

    Server messages use the serialization schema (what is actually sent), request bodies
    the validation one (optional fields stay optional). Property titles and defaults
    next to $refs are dropped so the generator does not emit an alias per field or
    duplicate enums, and 2020-12 `prefixItems` tuples are rewritten to the draft-07
    form it understands.
    """
    _, schema = models_json_schema(
        [
            (StatusMessage, "serialization"),
            (FrameHeader, "serialization"),
            (EventsMessage, "serialization"),
            (RecordingStepInfo, "serialization"),
            (SettingsChanges, "validation"),
            (AutomationUpdate, "validation"),
        ],
        title="Protocol",
    )
    schema["additionalProperties"] = False
    return _for_json2ts(schema)


def _for_json2ts(node: Any) -> Any:
    if isinstance(node, list):
        return [_for_json2ts(item) for item in node]
    if not isinstance(node, dict):
        return node
    node = {key: _for_json2ts(value) for key, value in node.items()}
    if "$ref" in node:
        # A `default` next to a $ref makes the generator emit a duplicate type.
        node.pop("default", None)
    if "prefixItems" in node:
        node["items"] = node.pop("prefixItems")
        node["additionalItems"] = False
    if isinstance(node.get("properties"), dict):
        for prop in node["properties"].values():
            if isinstance(prop, dict):
                prop.pop("title", None)
    return node


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: python -m eyes_on_screen.web.messages <schema.json>", file=sys.stderr)
        return 2
    # LF on every OS: the file is compared byte for byte in CI.
    Path(argv[1]).write_text(
        json.dumps(protocol_schema(), indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
