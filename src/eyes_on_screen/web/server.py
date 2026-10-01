"""aiohttp server for the web UI: the built page, and one WebSocket per open tab."""

from __future__ import annotations

import asyncio
import base64
import binascii
import contextlib
import json
import logging
import secrets
from collections import deque
from collections.abc import Awaitable, Callable
from pathlib import Path
from urllib.parse import urlsplit

from aiohttp import WSMsgType, web
from pydantic import ValidationError

from eyes_on_screen.config import WebConfig
from eyes_on_screen.web.messages import (
    COMMAND_ADAPTER,
    EventInfo,
    EventsMessage,
    PageCommand,
    ReplyMessage,
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

CommandHandler = Callable[[PageCommand], Awaitable[str | None]]
"""Runs one validated command from a page; returns an error message, or None on success."""


class _Client:
    def __init__(self, ws: web.WebSocketResponse, history: list[EventInfo]) -> None:
        self.ws = ws
        self.wake = asyncio.Event()
        self.outbox: list[str] = []
        self.events = history
        self.frame_seq = 0
        self.status_seq = 0


class WebServer:
    """Serves the UI and pushes the newest frame, status and events to every open page.

    All sending for a page happens in one task, so a slow page only skips stale
    frames instead of queueing them, and writes to its socket never interleave.
    """

    def __init__(self, config: WebConfig, on_command: CommandHandler) -> None:
        self._config = config
        self._on_command = on_command
        self._session = secrets.token_urlsafe(24)
        self._clients: set[_Client] = set()
        self._frame: bytes | None = None
        self._frame_seq = 0
        self._status = ""
        self._status_seq = 0
        self._events: deque[EventInfo] = deque(maxlen=EVENT_HISTORY)
        self._runner: web.AppRunner | None = None

    @property
    def url(self) -> str:
        host = self._config.host
        shown = "127.0.0.1" if host in ("0.0.0.0", "::") else host
        return f"http://{shown}:{self._config.port}/"

    @property
    def has_clients(self) -> bool:
        return bool(self._clients)

    def build_app(self) -> web.Application:
        app = web.Application(middlewares=[self._auth])
        app.router.add_get("/", self._index)
        app.router.add_get("/ws", self._websocket)
        assets = STATIC_DIR / "assets"
        if assets.is_dir():
            app.router.add_static("/assets/", assets)
        return app

    async def start(self) -> None:
        self._runner = web.AppRunner(self.build_app(), access_log=None)
        await self._runner.setup()
        await web.TCPSite(self._runner, self._config.host, self._config.port).start()

    async def stop(self) -> None:
        for client in list(self._clients):
            await client.ws.close()
        if self._runner is not None:
            await self._runner.cleanup()
            self._runner = None

    def publish_frame(self, packet: bytes) -> None:
        self._frame = packet
        self._frame_seq += 1
        self._wake_all()

    def publish_status(self, status: StatusMessage) -> None:
        self._status = status.model_dump_json()
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

    # HTTP

    async def _index(self, request: web.Request) -> web.StreamResponse:
        index = STATIC_DIR / "index.html"
        if not index.is_file():
            return web.Response(status=503, text=_NOT_BUILT)
        # Asset names carry content hashes; only the page itself must never be cached.
        return web.FileResponse(index, headers={"Cache-Control": "no-cache"})

    @web.middleware
    async def _auth(self, request: web.Request, handler) -> web.StreamResponse:
        if not self._config.password:
            return await handler(request)
        if secrets.compare_digest(request.cookies.get(_SESSION_COOKIE, ""), self._session):
            return await handler(request)
        if not self._basic_auth_ok(request.headers.get("Authorization", "")):
            raise web.HTTPUnauthorized(headers={"WWW-Authenticate": _REALM})
        response = await handler(request)
        if not response.prepared:
            response.set_cookie(_SESSION_COOKIE, self._session, httponly=True, samesite="Strict")
        return response

    def _basic_auth_ok(self, header: str) -> bool:
        scheme, _, encoded = header.partition(" ")
        if scheme.lower() != "basic":
            return False
        try:
            _, _, password = base64.b64decode(encoded).decode("utf-8").partition(":")
        except (binascii.Error, UnicodeDecodeError):
            return False
        expected = self._config.password or ""
        return secrets.compare_digest(password.encode(), expected.encode())

    # WebSocket

    async def _websocket(self, request: web.Request) -> web.StreamResponse:
        origin = request.headers.get("Origin")
        if origin is not None and urlsplit(origin).netloc != request.host:
            # Another site's page must not be able to drive this one.
            raise web.HTTPForbidden(text="cross-origin WebSocket refused")

        ws = web.WebSocketResponse(heartbeat=20, compress=False)  # JPEGs do not compress
        await ws.prepare(request)
        client = _Client(ws, history=list(self._events))
        self._clients.add(client)
        client.wake.set()
        sender = asyncio.create_task(self._send_loop(client))
        try:
            async for message in ws:
                if message.type is WSMsgType.TEXT:
                    await self._handle(client, message.data)
        finally:
            self._clients.discard(client)
            sender.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await sender
        return ws

    async def _handle(self, client: _Client, data: str) -> None:
        try:
            raw = json.loads(data)
        except ValueError as exc:
            reply = ReplyMessage(id=None, ok=False, error=f"bad JSON: {exc}")
        else:
            request_id = raw.get("id") if isinstance(raw, dict) else None
            reply = await self._run_command(
                raw, request_id if isinstance(request_id, int) else None
            )
        client.outbox.append(reply.model_dump_json())
        client.wake.set()

    async def _run_command(self, raw: object, request_id: int | None) -> ReplyMessage:
        try:
            command = COMMAND_ADAPTER.validate_python(raw)
        except ValidationError as exc:
            details = "; ".join(
                f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()
            )
            return ReplyMessage(id=request_id, ok=False, error=f"bad command: {details}")
        try:
            error = await self._on_command(command)
        except Exception as exc:  # a broken command must not kill the page's socket
            log.exception("Web command failed: %s", command)
            error = str(exc)
        return ReplyMessage(id=request_id, ok=error is None, error=error)

    async def _send_loop(self, client: _Client) -> None:
        ws = client.ws
        while not ws.closed:
            await client.wake.wait()
            client.wake.clear()
            try:
                while client.outbox:
                    await ws.send_str(client.outbox.pop(0))
                if client.events:
                    events, client.events = client.events, []
                    await ws.send_str(EventsMessage(events=events).model_dump_json())
                if client.status_seq != self._status_seq and self._status:
                    client.status_seq = self._status_seq
                    await ws.send_str(self._status)
                if client.frame_seq != self._frame_seq and self._frame is not None:
                    client.frame_seq = self._frame_seq
                    await ws.send_bytes(self._frame)
            except ConnectionError:
                return
