import json
from pathlib import Path

from eyes_on_screen.web.messages import (
    BehaviorChanges,
    PoseChanges,
    SettingsChanges,
    protocol_schema,
)

SCHEMA_FILE = Path(__file__).resolve().parents[1] / "frontend" / "src" / "protocol" / "schema.json"


def test_frontend_schema_matches_the_python_messages():
    committed = json.loads(SCHEMA_FILE.read_text(encoding="utf-8"))

    assert committed == protocol_schema(), (
        "frontend/src/protocol/schema.json is stale: run `npm --prefix frontend run gen`"
    )


def test_schema_is_shaped_for_the_typescript_generator():
    schema = protocol_schema()

    assert "prefixItems" not in json.dumps(schema)  # draft-07 tuples json2ts understands
    assert {
        "StatusMessage",
        "FrameHeader",
        "EventsMessage",
        "SettingsChanges",
        "AutomationUpdate",
    } <= set(schema["$defs"])


def test_settings_changes_only_carry_what_was_sent():
    changes = SettingsChanges.model_validate({"behavior": {"pause_after_s": 2}, "pose": {}})

    assert changes.as_changes() == {"behavior": {"pause_after_s": 2.0}}


def test_change_models_cover_exactly_the_editable_settings():
    assert set(PoseChanges.model_fields) == {
        "yaw_center_deg",
        "pitch_center_deg",
        "yaw_tolerance_deg",
        "pitch_tolerance_deg",
    }
    assert "multiple_viewers" in BehaviorChanges.model_fields
