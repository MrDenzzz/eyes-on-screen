import asyncio
import logging
import re

import aiohttp
import numpy as np
import pytest
from aiohttp.test_utils import TestClient, TestServer

from eyes_on_screen.app import App, _EventForwarder
from eyes_on_screen.config import WebConfig, load_config
from eyes_on_screen.video.source import SourceStats
from eyes_on_screen.vision.analyzer import FaceAnalyzer
from eyes_on_screen.web import server as server_module
from eyes_on_screen.web.messages import COMMAND_ADAPTER, CalibrateCommand, EventInfo
from eyes_on_screen.web.protocol import decode_frame, encode_frame
from eyes_on_screen.web.server import WebServer


class RecordingHandler:
    def __init__(self, error: str | None = None) -> None:
        self.error = error
        self.commands = []

    async def __call__(self, command):
        self.commands.append(command)
        return self.error


def event(text: str = "hello") -> EventInfo:
    return EventInfo(ts=1, time="12:00:00", level="info", kind="other", text=text)


def run(scenario):
    asyncio.run(asyncio.wait_for(scenario(), 10))


def test_frame_packets_round_trip():
    image = np.full((90, 160, 3), 200, np.uint8)

    header, jpeg = decode_frame(encode_frame(image, {"seq": 3}, max_width=80, quality=70))

    assert header == {"seq": 3}
    assert jpeg[:2] == b"\xff\xd8"  # a JPEG, downscaled on the way


def test_page_and_its_assets_are_served():
    server = WebServer(WebConfig(), RecordingHandler())

    async def scenario():
        async with TestClient(TestServer(server.build_app())) as client:
            page = await client.get("/")
            assert page.status == 200
            html = await page.text()
            for asset in re.findall(r'(?:src|href)="(/assets/[^"]+)"', html):
                assert (await client.get(asset)).status == 200, asset

    run(scenario)


def test_unbuilt_ui_explains_how_to_build_it(tmp_path, monkeypatch):
    monkeypatch.setattr(server_module, "STATIC_DIR", tmp_path)
    server = WebServer(WebConfig(), RecordingHandler())

    async def scenario():
        async with TestClient(TestServer(server.build_app())) as client:
            page = await client.get("/")
            assert page.status == 503
            assert "npm --prefix frontend run build" in await page.text()

    run(scenario)


def test_websocket_pushes_events_status_frames_and_replies(app):
    handler = RecordingHandler()
    server = WebServer(WebConfig(), handler)
    server.publish_event(event("before the page opened"))

    async def scenario():
        async with TestClient(TestServer(server.build_app())) as client:
            ws = await client.ws_connect("/ws")
            history = await ws.receive_json()
            assert history["type"] == "events"
            assert [e["text"] for e in history["events"]] == ["before the page opened"]

            server.publish_status(app._status())
            status = await ws.receive_json()
            assert status["type"] == "status"
            assert status["settings"]["behavior"]["multiple_viewers"] == "any_away"

            image = np.zeros((8, 8, 3), np.uint8)
            server.publish_frame(encode_frame(image, {"seq": 1}, max_width=8, quality=70))
            header, _ = decode_frame(await ws.receive_bytes())
            assert header == {"seq": 1}

            await ws.send_json({"id": 7, "cmd": "calibrate"})
            assert await ws.receive_json() == {"type": "reply", "id": 7, "ok": True, "error": None}
            assert isinstance(handler.commands[0], CalibrateCommand)

            await ws.send_json({"id": 8, "cmd": "reboot"})
            reply = await ws.receive_json()
            assert (reply["id"], reply["ok"]) == (8, False)
            assert "bad command" in reply["error"]

            await ws.send_str("not json")
            assert (await ws.receive_json())["ok"] is False
            await ws.close()

    run(scenario)


def test_handler_errors_are_replied():
    server = WebServer(WebConfig(), RecordingHandler(error="Apple TV not connected"))

    async def scenario():
        async with TestClient(TestServer(server.build_app())) as client:
            ws = await client.ws_connect("/ws")
            await ws.send_json({"id": 1, "cmd": "player", "action": "pause"})
            reply = await ws.receive_json()
            assert reply == {
                "type": "reply",
                "id": 1,
                "ok": False,
                "error": "Apple TV not connected",
            }
            await ws.close()

    run(scenario)


def test_password_protects_the_page_and_the_socket():
    server = WebServer(WebConfig(host="0.0.0.0", password="secret"), RecordingHandler())

    def basic(password):
        return {"Authorization": aiohttp.encode_basic_auth("anyone", password)}

    async def scenario():
        async with TestClient(TestServer(server.build_app())) as client:
            denied = await client.get("/")
            assert denied.status == 401
            assert "Basic" in denied.headers["WWW-Authenticate"]
            assert (await client.get("/", headers=basic("wrong"))).status == 401

            assert (await client.get("/", headers=basic("secret"))).status == 200
            # The session cookie set by that answer now opens the socket.
            ws = await client.ws_connect("/ws")
            await ws.close()

    run(scenario)


def test_websocket_from_another_site_is_refused():
    server = WebServer(WebConfig(), RecordingHandler())

    async def scenario():
        async with TestClient(TestServer(server.build_app())) as client:
            with pytest.raises(aiohttp.WSServerHandshakeError) as refused:
                await client.ws_connect("/ws", headers={"Origin": "http://evil.example"})
            assert refused.value.status == 403

    run(scenario)


@pytest.mark.parametrize(
    ("message", "level", "kind"),
    [
        ("paused: looked away for 1.6s", logging.INFO, "pause"),
        ("would resume: looking at the screen for 0.5s", logging.INFO, "resume"),
        ("player: playing (TV - Show)", logging.INFO, "player"),
        ("calibrated: screen at yaw +2.9", logging.INFO, "calibration"),
        ("pause failed: timeout", logging.WARNING, "other"),
    ],
)
def test_events_are_forwarded_with_their_kind(message, level, kind):
    published: list[EventInfo] = []

    async def scenario():
        web = type("Web", (), {"publish_event": staticmethod(published.append)})()
        handler = _EventForwarder(web, asyncio.get_running_loop())
        handler.emit(logging.LogRecord("events", level, __file__, 1, message, None, None))
        await asyncio.sleep(0)

    run(scenario)

    [forwarded] = published
    assert forwarded.kind == kind
    assert forwarded.text == message
    assert forwarded.level == ("warning" if level >= logging.WARNING else "info")


class FakeSource:
    def start(self):
        pass

    def stop(self):
        pass

    def wait_for_frame(self, newer_than, timeout):
        return None

    def stats(self):
        return SourceStats("fake", False, None, None, None, 0.0, 0, 0, None)


@pytest.fixture
def app(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(
        "# mine\nvideo: {source: webcam}\napple_tv: {identifier: 'AA:BB'}\n"
        "behavior:\n  pause_after_s: 1.5\n",
        encoding="utf-8",
    )
    analyzer = FaceAnalyzer((0, 0, 1, 1), lambda image: [], lambda crop: None, max_faces=3)
    return App(load_config(path), path, FakeSource(), analyzer)


def command(app, message):
    return asyncio.run(app._on_web_command(COMMAND_ADAPTER.validate_python(message)))


class TestWebCommands:
    def test_settings_are_applied_live_and_saved(self, app):
        changes = {"behavior": {"pause_after_s": 2.5}, "target": {"roi": [0, 0, 0.5, 0.5]}}

        assert command(app, {"cmd": "set", "changes": changes}) is None
        assert app._analyzer.roi == (0, 0, 0.5, 0.5)
        assert app._machine.behavior.pause_after_s == 2.5
        saved = app._config_path.read_text(encoding="utf-8")
        assert "# mine" in saved
        assert "pause_after_s: 2.5" in saved

    def test_invalid_settings_are_rejected_and_nothing_changes(self, app):
        error = command(app, {"cmd": "set", "changes": {"behavior": {"pause_after_s": 0}}})

        assert "behavior.pause_after_s" in error
        assert app._machine.behavior.pause_after_s == 1.5

    def test_only_editable_settings_exist_in_the_protocol(self):
        with pytest.raises(ValueError, match="video"):
            COMMAND_ADAPTER.validate_python(
                {"cmd": "set", "changes": {"video": {"rtsp_url": "rtsp://x"}}}
            )

    def test_automation_can_be_switched_off(self, app):
        assert command(app, {"cmd": "automation", "enabled": False}) is None
        assert app._automation is False

    def test_calibration_starts_with_a_countdown(self, app):
        assert command(app, {"cmd": "calibrate"}) is None
        assert app._calibration is not None

    def test_player_buttons_need_the_apple_tv(self, app):
        assert "not connected" in command(app, {"cmd": "player", "action": "pause"})

    def test_status_serializes(self, app):
        status = app._status()

        assert '"type":"status"' in status.model_dump_json()
        assert status.settings.roi == (0, 0, 1, 1)
