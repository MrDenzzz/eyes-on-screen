"""Messages between `eos run` and the web UI, as pydantic models.

They are the single source of truth for the protocol: the server builds and validates
messages with them, and their JSON Schema is turned into the frontend's TypeScript
types (`frontend/src/protocol`). Regenerate after a change:

    uv run python -m eyes_on_screen.web.messages frontend/src/protocol/schema.json
    npm --prefix frontend run gen:types
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, create_model

from eyes_on_screen.appletv.state import Playback
from eyes_on_screen.attention.classifier import Attention
from eyes_on_screen.attention.state_machine import PlaybackCommand
from eyes_on_screen.config import BehaviorConfig, PoseConfig
from eyes_on_screen.settings import EDITABLE

Roi = tuple[float, float, float, float]


class _Message(BaseModel):
    model_config = ConfigDict(extra="forbid")


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


class AutomationInfo(_Message):
    enabled: bool
    dry_run: bool


class CalibrationInfo(_Message):
    phase: Literal["countdown", "collecting"]
    remaining_s: float
    phase_s: float


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


class ReplyMessage(_Message):
    type: Literal["reply"] = "reply"
    id: int | None
    ok: bool
    error: str | None = None


# Page -> server


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


class SetCommand(_Message):
    cmd: Literal["set"]
    id: int | None = None
    changes: SettingsChanges


class CalibrateCommand(_Message):
    cmd: Literal["calibrate"]
    id: int | None = None


class AutomationCommand(_Message):
    cmd: Literal["automation"]
    id: int | None = None
    enabled: bool


class PlayerCommand(_Message):
    cmd: Literal["player"]
    id: int | None = None
    action: Literal["play", "pause"]


PageCommand = Annotated[
    SetCommand | CalibrateCommand | AutomationCommand | PlayerCommand,
    Field(discriminator="cmd", title="PageCommand"),
]
COMMAND_ADAPTER: TypeAdapter[PageCommand] = TypeAdapter(PageCommand)


class Protocol(_Message):
    """Not sent anywhere: gathers every message so one schema describes them all."""

    status: StatusMessage
    frame: FrameHeader
    events: EventsMessage
    reply: ReplyMessage
    command: PageCommand


def protocol_schema() -> dict[str, Any]:
    return Protocol.model_json_schema(mode="serialization")


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: python -m eyes_on_screen.web.messages <schema.json>", file=sys.stderr)
        return 2
    Path(argv[1]).write_text(json.dumps(protocol_schema(), indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
