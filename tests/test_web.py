import asyncio
import json
import logging

import aiohttp
import numpy as np
import pytest
from aiohttp.test_utils import TestClient, TestServer

from eyes_on_screen.app import App, _EventForwarder
from eyes_on_screen.config import WebConfig, load_config
from eyes_on_screen.video.source import SourceStats
from eyes_on_screen.vision.analyzer import FaceAnalyzer
from eyes_on_screen.web.protocol import decode_frame, encode_frame
from eyes_on_screen.web.server import WebServer


async def echo_command(message):
    return {"ok": True, "echo": message.get("cmd")}


def run(scenario):
    asyncio.run(asyncio.wait_for(scenario(), 10))


def test_frame_packets_round_trip():
    image = np.full((90, 160, 3), 200, np.uint8)

    header, jpeg = decode_frame(encode_frame(image, {"seq": 3}, max_width=80, quality=70))

    assert header == {"seq": 3}
    assert jpeg[:2] == b"\xff\xd8"  # a JPEG, downscaled on the way


def test_page_static_files_and_websocket_flow():
    server = WebServer(WebConfig(), echo_command)
    server.publish_event({"text": "before the page opened"})

    async def scenario():
        async with TestClient(TestServer(server.build_app())) as client:
            page = await client.get("/")
            assert page.status == 200
            assert "eyes-on-screen" in await page.text()
            assert (await client.get("/static/app.js")).status == 200

            ws = await client.ws_connect("/ws")
            assert (await ws.receive_json())["events"] == [{"text": "before the page opened"}]

            server.publish_status({"room": "away"})
            assert await ws.receive_json() == {"type": "status", "room": "away"}

            server.publish_frame(
                encode_frame(np.zeros((8, 8, 3), np.uint8), {"seq": 1}, max_width=8, quality=70)
            )
            header, _ = decode_frame(await ws.receive_bytes())
            assert header == {"seq": 1}

            await ws.send_json({"id": 7, "cmd": "ping"})
            assert await ws.receive_json() == {"type": "reply", "id": 7, "ok": True, "echo": "ping"}

            await ws.send_str("not json")
            reply = await ws.receive_json()
            assert reply["ok"] is False
            await ws.close()

    run(scenario)


def test_password_protects_the_page_and_the_socket():
    server = WebServer(WebConfig(host="0.0.0.0", password="secret"), echo_command)

    async def scenario():
        async with TestClient(TestServer(server.build_app())) as client:
            denied = await client.get("/")
            assert denied.status == 401
            assert "Basic" in denied.headers["WWW-Authenticate"]
            assert (
                await client.get(
                    "/", headers={"Authorization": aiohttp.encode_basic_auth("x", "wrong")}
                )
            ).status == 401

            assert (
                await client.get(
                    "/", headers={"Authorization": aiohttp.encode_basic_auth("anyone", "secret")}
                )
            ).status == 200
            # The session cookie set by that answer now opens the socket.
            ws = await client.ws_connect("/ws")
            await ws.close()

    run(scenario)


def test_websocket_from_another_site_is_refused():
    server = WebServer(WebConfig(), echo_command)

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
    published = []

    async def scenario():
        web = type("Web", (), {"publish_event": staticmethod(published.append)})()
        handler = _EventForwarder(web, asyncio.get_running_loop())
        handler.emit(logging.LogRecord("events", level, __file__, 1, message, None, None))
        await asyncio.sleep(0)

    run(scenario)

    [event] = published
    assert event["kind"] == kind
    assert event["text"] == message
    assert event["level"] == ("warning" if level >= logging.WARNING else "info")


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
    return asyncio.run(app._on_web_command(message))


class TestWebCommands:
    def test_settings_are_applied_live_and_saved(self, app):
        reply = command(
            app,
            {
                "cmd": "set",
                "changes": {
                    "behavior": {"pause_after_s": 2.5},
                    "target": {"roi": [0, 0, 0.5, 0.5]},
                },
            },
        )

        assert reply == {"ok": True}
        assert app._analyzer.roi == (0, 0, 0.5, 0.5)
        assert app._machine.behavior.pause_after_s == 2.5
        saved = app._config_path.read_text(encoding="utf-8")
        assert "# mine" in saved
        assert "pause_after_s: 2.5" in saved

    def test_invalid_settings_are_rejected_and_nothing_changes(self, app):
        reply = command(app, {"cmd": "set", "changes": {"behavior": {"pause_after_s": 0}}})

        assert reply["ok"] is False
        assert "behavior.pause_after_s" in reply["error"]
        assert app._machine.behavior.pause_after_s == 1.5

    def test_automation_can_be_switched_off(self, app):
        assert command(app, {"cmd": "automation", "enabled": False}) == {"ok": True}
        assert app._automation is False

    def test_calibration_starts_with_a_countdown(self, app):
        assert command(app, {"cmd": "calibrate"}) == {"ok": True}
        assert app._calibration is not None

    def test_player_buttons_need_the_apple_tv(self, app):
        reply = command(app, {"cmd": "player", "action": "pause"})

        assert reply["ok"] is False
        assert "not connected" in reply["error"]

    def test_unknown_command(self, app):
        assert command(app, {"cmd": "reboot"})["ok"] is False

    def test_status_is_plain_json(self, app):
        status = app._status()

        assert json.loads(json.dumps(status)) == status
        assert status["settings"]["behavior"]["multiple_viewers"] == "any_away"
