"""FastAPI app for the web UI.

- REST under /api for commands (settings, calibration, automation, play/pause), with
  OpenAPI docs at /api/docs;
- one push-only WebSocket per open tab at /ws (status, video frames, events);
- the built React page at / and its assets at /assets.

uvicorn runs inside eos's own event loop, next to the camera analysis and the Apple TV
connection.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import contextlib
import logging
import secrets
import socket
from collections import deque
from collections.abc import Awaitable, Callable, Iterator, MutableMapping
from pathlib import Path
from typing import Any, Literal, Protocol
from urllib.parse import urlsplit

import uvicorn
from fastapi import APIRouter, FastAPI, HTTPException, WebSocket, status
from fastapi.responses import FileResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.requests import HTTPConnection
from starlette.websockets import WebSocketDisconnect

from eyes_on_screen.appletv.controller import AppleTvError
from eyes_on_screen.config import WebConfig
from eyes_on_screen.settings import SettingsError
from eyes_on_screen.web.messages import (
    AutomationInfo,
    AutomationUpdate,
    EventInfo,
    EventsMessage,
    SettingsChanges,
    SettingsInfo,
    StatusMessage,
)

log = logging.getLogger(__name__)

# The React app (frontend/) builds into this folder: index.html plus assets/.
STATIC_DIR = Path(__file__).parent / "static"
EVENT_HISTORY = 100
_SESSION_COOKIE = "eos_session"
_REALM = 'Basic realm="eyes-on-screen", charset="UTF-8"'
_NOT_BUILT = (
    "The web UI is not built yet: run `npm --prefix frontend ci` "
    "and `npm --prefix frontend run build`."
)
_SHUTDOWN_GRACE_S = 2


class Controls(Protocol):
    """What the web UI may do to the running app."""

    def status(self) -> StatusMessage: ...

    def change_settings(self, changes: SettingsChanges) -> SettingsInfo:
        """Apply and save; raises SettingsError for rejected values."""
        ...

    def start_calibration(self) -> None: ...

    def set_automation(self, enabled: bool) -> AutomationInfo: ...

    async def press(self, action: Literal["play", "pause"]) -> None:
        """Raises AppleTvError when the Apple TV is unreachable."""
        ...


class _Client:
    def __init__(self, ws: WebSocket, history: list[EventInfo]) -> None:
        self.ws = ws
        self.wake = asyncio.Event()
        self.events = history
        self.frame_seq = 0
        self.status_seq = 0


class WebServer:
    """Serves the UI and pushes the newest frame, status and events to every open tab.

    All sending for a tab happens in one task, so a slow tab only skips stale frames
    instead of queueing them, and writes to its socket never interleave.
    """

    def __init__(self, config: WebConfig, controls: Controls) -> None:
        self._config = config
        self._controls = controls
        self._clients: set[_Client] = set()
        self._frame: bytes | None = None
        self._frame_seq = 0
        self._status = ""
        self._status_seq = 0
        self._events: deque[EventInfo] = deque(maxlen=EVENT_HISTORY)
        self._server: uvicorn.Server | None = None
        self._serving: asyncio.Task[None] | None = None

    @property
    def url(self) -> str:
        host = self._config.host
        shown = "127.0.0.1" if host in ("0.0.0.0", "::") else host
        return f"http://{shown}:{self._config.port}/"

    @property
    def has_clients(self) -> bool:
        return bool(self._clients)

    # Lifecycle

    async def start(self) -> None:
        """Listen and serve in the background; raises OSError if the port is taken."""
        # Bind here rather than in uvicorn, which would sys.exit() on a busy port.
        sock = socket.create_server((self._config.host, self._config.port))
        config = uvicorn.Config(
            self.build_app(),
            log_config=None,  # keep eos's logging setup
            log_level="warning",
            access_log=False,
            lifespan="off",
            timeout_graceful_shutdown=_SHUTDOWN_GRACE_S,
        )
        self._server = _EmbeddedServer(config)
        self._serving = asyncio.create_task(self._server.serve(sockets=[sock]), name="web")
        while not self._server.started and not self._serving.done():
            await asyncio.sleep(0.01)
        if self._serving.done():
            self._serving.result()  # re-raise why it stopped

    async def stop(self) -> None:
        for client in list(self._clients):
            with contextlib.suppress(Exception):
                await client.ws.close()
        if self._server is not None and self._serving is not None:
            self._server.should_exit = True
            await self._serving
        self._server = self._serving = None

    # Pushing to open tabs

    def publish_frame(self, packet: bytes) -> None:
        self._frame = packet
        self._frame_seq += 1
        self._wake_all()

    def publish_status(self, message: StatusMessage) -> None:
        self._status = message.model_dump_json()
        self._status_seq += 1
        self._wake_all()

    def publish_event(self, event: EventInfo) -> None:
        self._events.append(event)
        for client in self._clients:
            client.events.append(event)
        self._wake_all()

    def _wake_all(self) -> None:
        for client in self._clients:
            client.wake.set()

    # The app

    def build_app(self) -> FastAPI:
        app = FastAPI(
            title="eyes-on-screen",
            summary="Pauses Apple TV when viewers look away from the screen.",
            docs_url="/api/docs",
            redoc_url=None,
            openapi_url="/api/openapi.json",
        )
        app.include_router(self._api())
        app.add_api_websocket_route("/ws", self._websocket)
        app.add_api_route("/", self._index, include_in_schema=False)
        app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets", check_dir=False))
        app.add_middleware(
            _BasicAuthMiddleware, password=self._config.password, session=secrets.token_urlsafe(24)
        )
        return app

    def _api(self) -> APIRouter:
        # All handlers are async on purpose: they run on eos's event loop, the thread that
        # owns the app's state, instead of FastAPI's thread pool.
        router = APIRouter(prefix="/api", tags=["eos"])
        controls = self._controls

        @router.get("/status", summary="Current state of the camera, viewers and player")
        async def get_status() -> StatusMessage:
            return controls.status()

        @router.get("/events", summary="Recent pause/resume and player events, oldest first")
        async def get_events() -> list[EventInfo]:
            return list(self._events)

        @router.patch(
            "/settings",
            summary="Change settings; applied live and saved to config.yaml",
            responses={422: {"description": "A value was rejected"}},
        )
        async def patch_settings(changes: SettingsChanges) -> SettingsInfo:
            try:
                return controls.change_settings(changes)
            except SettingsError as exc:
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc

        @router.post(
            "/calibration",
            status_code=status.HTTP_202_ACCEPTED,
            summary="Start calibrating the screen direction (3 s countdown, then 2 s)",
        )
        async def start_calibration() -> None:
            controls.start_calibration()

        @router.put("/automation", summary="Switch automatic pause/resume on or off")
        async def put_automation(update: AutomationUpdate) -> AutomationInfo:
            return controls.set_automation(update.enabled)

        @router.post(
            "/player/{action}",
            status_code=status.HTTP_204_NO_CONTENT,
            summary="Press play or pause on the Apple TV",
            responses={503: {"description": "The Apple TV is not connected"}},
        )
        async def press(action: Literal["play", "pause"]) -> None:
            try:
                await controls.press(action)
            except AppleTvError as exc:
                raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc

        return router

    async def _index(self) -> Response:
        index = STATIC_DIR / "index.html"
        if not index.is_file():
            return PlainTextResponse(_NOT_BUILT, status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
        # Asset names carry content hashes; only the page itself must never be cached.
        return FileResponse(index, headers={"Cache-Control": "no-cache"})

    async def _websocket(self, ws: WebSocket) -> None:
        origin = ws.headers.get("origin")
        if origin is not None and urlsplit(origin).netloc != ws.headers.get("host"):
            # Another site's page must not be able to watch the camera.
            await ws.close(code=status.WS_1008_POLICY_VIOLATION)
            return
        await ws.accept()
        client = _Client(ws, history=list(self._events))
        self._clients.add(client)
        client.wake.set()
        sender = asyncio.create_task(self._send_loop(client))
        try:
            while (await ws.receive())["type"] != "websocket.disconnect":
                pass  # push-only: commands go through the REST API
        finally:
            self._clients.discard(client)
            sender.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await sender

    async def _send_loop(self, client: _Client) -> None:
        ws = client.ws
        with contextlib.suppress(WebSocketDisconnect, RuntimeError, ConnectionError):
            while True:
                await client.wake.wait()
                client.wake.clear()
                if client.events:
                    events, client.events = client.events, []
                    await ws.send_text(EventsMessage(events=events).model_dump_json())
                if client.status_seq != self._status_seq and self._status:
                    client.status_seq = self._status_seq
                    await ws.send_text(self._status)
                if client.frame_seq != self._frame_seq and self._frame is not None:
                    client.frame_seq = self._frame_seq
                    await ws.send_bytes(self._frame)


class _EmbeddedServer(uvicorn.Server):
    """uvicorn inside eos's loop: Ctrl+C belongs to eos, not to the web server."""

    @contextlib.contextmanager
    def capture_signals(self) -> Iterator[None]:
        yield


Scope = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[MutableMapping[str, Any]]]
Send = Callable[[MutableMapping[str, Any]], Awaitable[None]]


class _BasicAuthMiddleware:
    """Password protection for everything: page, assets, API and WebSocket.

    The browser asks for the password once (HTTP Basic); the answer sets an HttpOnly,
    SameSite=Strict session cookie that later requests and the WebSocket use.
    """

    def __init__(
        self, app: Callable[..., Awaitable[None]], password: str | None, session: str
    ) -> None:
        self._app = app
        self._password = password
        self._session = session

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket") or not self._password:
            await self._app(scope, receive, send)
            return
        connection = HTTPConnection(scope)
        if secrets.compare_digest(connection.cookies.get(_SESSION_COOKIE, ""), self._session):
            await self._app(scope, receive, send)
            return
        if not self._basic_ok(connection.headers.get("authorization", "")):
            await self._deny(scope, send)
            return
        await self._app(
            scope, receive, self._with_cookie(send) if scope["type"] == "http" else send
        )

    def _basic_ok(self, header: str) -> bool:
        scheme, _, encoded = header.partition(" ")
        if scheme.lower() != "basic":
            return False
        try:
            _, _, password = base64.b64decode(encoded).decode("utf-8").partition(":")
        except (binascii.Error, UnicodeDecodeError):
            return False
        return secrets.compare_digest(password.encode(), (self._password or "").encode())

    def _with_cookie(self, send: Send) -> Send:
        cookie = f"{_SESSION_COOKIE}={self._session}; Path=/; HttpOnly; SameSite=Strict".encode()

        async def send_with_cookie(message: MutableMapping[str, Any]) -> None:
            if message["type"] == "http.response.start":
                message["headers"] = [*message.get("headers", []), (b"set-cookie", cookie)]
            await send(message)

        return send_with_cookie

    async def _deny(self, scope: Scope, send: Send) -> None:
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": status.WS_1008_POLICY_VIOLATION})
            return
        await send(
            {
                "type": "http.response.start",
                "status": status.HTTP_401_UNAUTHORIZED,
                "headers": [
                    (b"www-authenticate", _REALM.encode()),
                    (b"content-type", b"text/plain"),
                ],
            }
        )
        await send({"type": "http.response.body", "body": b"password required"})
