import asyncio
import contextlib
import logging
import re
import socket
from collections.abc import AsyncIterator

import aiohttp
import numpy as np
import pytest

from eyes_on_screen.app import App, _EventForwarder
from eyes_on_screen.appletv.controller import AppleTvError
from eyes_on_screen.config import WebConfig, load_config
from eyes_on_screen.settings import SettingsError
from eyes_on_screen.video.source import SourceStats
from eyes_on_screen.vision.analyzer import FaceAnalyzer
from eyes_on_screen.web import server as server_module
from eyes_on_screen.web.messages import AutomationInfo, EventInfo, SettingsChanges
from eyes_on_screen.web.protocol import decode_frame, encode_frame
from eyes_on_screen.web.server import WebServer


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def event(text: str = "hello") -> EventInfo:
    return EventInfo(ts=1, time="12:00:00", level="info", kind="other", text=text)


class FakeSource:
    def start(self):
        pass

    def stop(self):
        pass

    def wait_for_frame(self, newer_than, timeout):
        return None

    def stats(self):
        return SourceStats("fake", False, None, None, None, 0.0, 0, 0, None)


def make_app(tmp_path) -> App:
    path = tmp_path / "config.yaml"
    path.write_text(
        "# mine\nvideo: {source: webcam}\napple_tv: {identifier: 'AA:BB'}\n"
        "behavior:\n  pause_after_s: 1.5\n",
        encoding="utf-8",
    )
    analyzer = FaceAnalyzer((0, 0, 1, 1), lambda image: [], lambda crop: None, max_faces=3)
    return App(load_config(path), path, FakeSource(), analyzer)


@pytest.fixture
def app(tmp_path) -> App:
    return make_app(tmp_path)


class FakeControls:
    """Controls with canned answers, recording what the web layer asked for."""

    def __init__(self, app: App) -> None:
        self.app = app
        self.calls: list[tuple] = []
        self.settings_error: str | None = None
        self.player_error: str | None = None

    def status(self):
        return self.app.status()

    def change_settings(self, changes: SettingsChanges):
        self.calls.append(("settings", changes.as_changes()))
        if self.settings_error:
            raise SettingsError(self.settings_error)
        return self.app._settings_info()

    def start_calibration(self):
        self.calls.append(("calibrate",))

    def set_automation(self, enabled: bool):
        self.calls.append(("automation", enabled))
        return AutomationInfo(enabled=enabled, dry_run=False)

    async def press(self, action):
        self.calls.append(("press", action))
        if self.player_error:
            raise AppleTvError(self.player_error)


@contextlib.asynccontextmanager
async def serving(server_config: WebConfig, controls) -> AsyncIterator[tuple[WebServer, str]]:
    server = WebServer(server_config, controls)
    await server.start()
    try:
        yield server, f"http://127.0.0.1:{server_config.port}"
    finally:
        await server.stop()


def run(scenario):
    asyncio.run(asyncio.wait_for(scenario(), 20))


def basic(password: str) -> dict[str, str]:
    return {"Authorization": aiohttp.encode_basic_auth("anyone", password)}


def test_frame_packets_round_trip():
    image = np.full((90, 160, 3), 200, np.uint8)

    header, jpeg = decode_frame(encode_frame(image, {"seq": 3}, max_width=80, quality=70))

    assert header == {"seq": 3}
    assert jpeg[:2] == b"\xff\xd8"  # a JPEG, downscaled on the way


def test_page_assets_and_api_docs_are_served(app):
    async def scenario():
        async with (
            serving(WebConfig(port=free_port()), FakeControls(app)) as (_, url),
            aiohttp.ClientSession() as http,
        ):
            page = await http.get(url + "/")
            assert page.status == 200
            for asset in re.findall(r'(?:src|href)="(/assets/[^"]+)"', await page.text()):
                assert (await http.get(url + asset)).status == 200, asset
            openapi = await (await http.get(url + "/api/openapi.json")).json()
            assert {"/api/status", "/api/settings", "/api/player/{action}"} <= set(openapi["paths"])

    run(scenario)


def test_unbuilt_ui_explains_how_to_build_it(app, tmp_path, monkeypatch):
    monkeypatch.setattr(server_module, "STATIC_DIR", tmp_path / "empty")

    async def scenario():
        async with (
            serving(WebConfig(port=free_port()), FakeControls(app)) as (_, url),
            aiohttp.ClientSession() as http,
        ):
            page = await http.get(url + "/")
            assert page.status == 503
            assert "npm --prefix frontend run build" in await page.text()

    run(scenario)


def test_rest_api(app):
    controls = FakeControls(app)

    async def scenario():
        async with (
            serving(WebConfig(port=free_port()), controls) as (_, url),
            aiohttp.ClientSession(base_url=url) as http,
        ):
            status = await (await http.get("/api/status")).json()
            assert status["type"] == "status"

            changed = await http.patch("/api/settings", json={"behavior": {"pause_after_s": 2.5}})
            assert changed.status == 200
            assert controls.calls[-1] == ("settings", {"behavior": {"pause_after_s": 2.5}})

            not_a_setting = await http.patch("/api/settings", json={"video": {"rtsp_url": "x"}})
            assert not_a_setting.status == 422  # FastAPI validation: no such editable key

            controls.settings_error = "behavior.pause_after_s: must be > 0"
            rejected = await http.patch("/api/settings", json={"behavior": {"pause_after_s": 0}})
            assert rejected.status == 422
            assert (await rejected.json())["detail"] == "behavior.pause_after_s: must be > 0"

            assert (await http.post("/api/calibration")).status == 202
            automation = await http.put("/api/automation", json={"enabled": False})
            assert await automation.json() == {"enabled": False, "dry_run": False}

            assert (await http.post("/api/player/pause")).status == 204
            assert (await http.post("/api/player/rewind")).status == 422
            controls.player_error = "not connected to the Apple TV"
            offline = await http.post("/api/player/play")
            assert offline.status == 503
            assert "not connected" in (await offline.json())["detail"]

    run(scenario)


def test_websocket_pushes_events_status_and_frames(app):
    async def scenario():
        async with serving(WebConfig(port=free_port()), FakeControls(app)) as (server, url):
            server.publish_event(event("before the page opened"))
            async with aiohttp.ClientSession() as http, http.ws_connect(url + "/ws") as ws:
                history = await ws.receive_json()
                assert history["type"] == "events"
                assert [e["text"] for e in history["events"]] == ["before the page opened"]

                server.publish_status(app.status())
                status = await ws.receive_json()
                assert status["type"] == "status"
                assert status["settings"]["behavior"]["multiple_viewers"] == "any_away"

                image = np.zeros((8, 8, 3), np.uint8)
                server.publish_frame(encode_frame(image, {"seq": 1}, max_width=8, quality=70))
                header, _ = decode_frame(await ws.receive_bytes())
                assert header == {"seq": 1}

    run(scenario)


def test_password_protects_page_api_and_socket(app):
    config = WebConfig(host="127.0.0.1", port=free_port(), password="secret")

    async def scenario():
        async with (
            serving(config, FakeControls(app)) as (_, url),
            aiohttp.ClientSession(cookie_jar=aiohttp.CookieJar(unsafe=True)) as http,
        ):
            denied = await http.get(url + "/")
            assert denied.status == 401
            assert "Basic" in denied.headers["WWW-Authenticate"]
            assert (await http.get(url + "/api/status")).status == 401
            assert (await http.get(url + "/", headers=basic("wrong"))).status == 401
            with pytest.raises(aiohttp.WSServerHandshakeError):
                await http.ws_connect(url + "/ws")

            assert (await http.get(url + "/", headers=basic("secret"))).status == 200
            # The session cookie from that answer now opens the API and the socket.
            assert (await http.get(url + "/api/status")).status == 200
            ws = await http.ws_connect(url + "/ws")
            await ws.close()

    run(scenario)


def test_websocket_from_another_site_is_refused(app):
    async def scenario():
        async with (
            serving(WebConfig(port=free_port()), FakeControls(app)) as (_, url),
            aiohttp.ClientSession() as http,
        ):
            with pytest.raises(aiohttp.WSServerHandshakeError) as refused:
                await http.ws_connect(url + "/ws", headers={"Origin": "http://evil.example"})
            assert refused.value.status == 403

    run(scenario)


def test_busy_port_is_an_os_error(app):
    async def scenario():
        with socket.socket() as taken:
            taken.bind(("127.0.0.1", 0))
            taken.listen()
            port = taken.getsockname()[1]
            with pytest.raises(OSError):
                await WebServer(WebConfig(port=port), FakeControls(app)).start()

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


class TestAppControls:
    def test_settings_are_applied_live_and_saved(self, app):
        changes = SettingsChanges.model_validate(
            {"behavior": {"pause_after_s": 2.5}, "target": {"roi": [0, 0, 0.5, 0.5]}}
        )

        settings = app.change_settings(changes)

        assert settings.behavior.pause_after_s == 2.5
        assert app._analyzer.roi == (0, 0, 0.5, 0.5)
        assert app._machine.behavior.pause_after_s == 2.5
        saved = app._config_path.read_text(encoding="utf-8")
        assert "# mine" in saved
        assert "pause_after_s: 2.5" in saved

    def test_invalid_settings_are_rejected_and_nothing_changes(self, app):
        changes = SettingsChanges.model_validate({"behavior": {"pause_after_s": 0}})

        with pytest.raises(SettingsError, match=r"behavior\.pause_after_s"):
            app.change_settings(changes)
        assert app._machine.behavior.pause_after_s == 1.5

    def test_automation_switch(self, app):
        assert app.set_automation(False) == AutomationInfo(enabled=False, dry_run=False)
        assert app._automation is False

    def test_calibration_starts_with_a_countdown(self, app):
        app.start_calibration()

        assert app._calibration is not None
        assert app._calibration.counting_down(app._calibration.start - 1)

    def test_player_buttons_need_the_apple_tv(self, app):
        with pytest.raises(AppleTvError, match="not connected"):
            asyncio.run(app.press("pause"))

    def test_status_serializes(self, app):
        status = app.status()

        assert '"type":"status"' in status.model_dump_json()
        assert status.settings.roi == (0, 0, 1, 1)
