"""Running go2rtc alongside eos, so the camera stream needs no separate start."""

from __future__ import annotations

import logging
import socket
import subprocess
import sys
import threading
import time
from collections.abc import Sequence
from pathlib import Path
from typing import IO
from urllib.parse import urlsplit

from eyes_on_screen.config import Go2rtcConfig, VideoConfig, VideoSourceKind

log = logging.getLogger(__name__)

READY_TIMEOUT_S = 10.0
WATCH_INTERVAL_S = 1.0
# Short on purpose: each second here is a second without video. A crash loop then
# restarts about every 2 s, which the log makes obvious.
RESTART_DELAY_S = 1.0
_READY_POLL_S = 0.2
_STOP_TIMEOUT_S = 5.0
_DEFAULT_RTSP_PORT = 554


class SupervisorError(Exception):
    """The helper process could not be started. User-facing message."""


class ProcessSupervisor:
    """Keeps a helper process (go2rtc) running for as long as the app needs it.

    If something already listens on `address`, that instance is used and left alone.
    Otherwise the process is started hidden, restarted if it dies, and stopped on exit.
    """

    def __init__(
        self,
        name: str,
        command: Sequence[str],
        cwd: Path,
        address: tuple[str, int],
        log_path: Path | None = None,
    ) -> None:
        self.name = name
        self.spawned = 0
        self._command = list(command)
        self._cwd = cwd
        self._address = address
        self._log_path = log_path
        self._log_file: IO[bytes] | None = None
        self._process: subprocess.Popen[bytes] | None = None
        self._stopping = threading.Event()
        self._watchdog: threading.Thread | None = None

    def __enter__(self) -> ProcessSupervisor:
        self.start()
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.stop()

    def start(self) -> None:
        host, port = self._address
        if is_listening(host, port):
            log.info("%s is already running on %s:%d, using it", self.name, host, port)
            return
        if self._log_path is not None:
            self._log_path.parent.mkdir(parents=True, exist_ok=True)
            self._log_file = self._log_path.open("ab")
        try:
            self._spawn()
            self._wait_ready()
        except BaseException:
            self.stop()
            raise
        self._watchdog = threading.Thread(
            target=self._watch, name=f"{self.name}-watchdog", daemon=True
        )
        self._watchdog.start()

    def stop(self) -> None:
        self._stopping.set()
        if self._watchdog is not None:
            self._watchdog.join()
            self._watchdog = None
        process, self._process = self._process, None
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(_STOP_TIMEOUT_S)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            log.info("Stopped %s", self.name)
        if self._log_file is not None:
            self._log_file.close()
            self._log_file = None

    def _spawn(self) -> None:
        # No console window on Windows; this also keeps our Ctrl+C away from the
        # child, so shutdown order stays ours.
        flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        output = self._log_file if self._log_file is not None else subprocess.DEVNULL
        try:
            self._process = subprocess.Popen(
                self._command,
                cwd=self._cwd,
                stdin=subprocess.DEVNULL,
                stdout=output,
                stderr=subprocess.STDOUT,
                creationflags=flags,
            )
        except OSError as exc:
            raise SupervisorError(f"cannot start {self.name}: {exc}") from exc
        self.spawned += 1
        log.info("Started %s (pid %d)", self.name, self._process.pid)

    def _wait_ready(self) -> None:
        assert self._process is not None
        host, port = self._address
        deadline = time.monotonic() + READY_TIMEOUT_S
        while time.monotonic() < deadline:
            code = self._process.poll()
            if code is not None:
                raise SupervisorError(
                    f"{self.name} exited right away with code {code}{self._see_log()}"
                )
            if is_listening(host, port):
                return
            time.sleep(_READY_POLL_S)
        raise SupervisorError(
            f"{self.name} did not open {host}:{port} within {READY_TIMEOUT_S:.0f}s{self._see_log()}"
        )

    def _watch(self) -> None:
        while not self._stopping.wait(WATCH_INTERVAL_S):
            assert self._process is not None
            code = self._process.poll()
            if code is None:
                continue
            log.warning(
                "%s exited with code %s; restarting in %.0fs", self.name, code, RESTART_DELAY_S
            )
            if self._stopping.wait(RESTART_DELAY_S):
                return
            try:
                self._spawn()
            except SupervisorError as exc:
                log.error("%s", exc)

    def _see_log(self) -> str:
        return f"; see {self._log_path}" if self._log_path else ""


def is_listening(host: str, port: int, timeout: float = 0.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def go2rtc_supervisor(go2rtc: Go2rtcConfig, video: VideoConfig) -> ProcessSupervisor | None:
    """The supervisor for go2rtc, or None when the app should not manage it."""
    if not go2rtc.autostart or video.source is not VideoSourceKind.RTSP:
        return None
    for path, what in ((go2rtc.binary, "binary"), (go2rtc.config_file, "config")):
        if not path.is_file():
            raise SupervisorError(
                f"go2rtc {what} not found: {path} "
                "(see docs/go2rtc.md, or set go2rtc.autostart: false)"
            )
    url = urlsplit(video.rtsp_url or "")
    return ProcessSupervisor(
        "go2rtc",
        [str(go2rtc.binary), "-c", str(go2rtc.config_file)],
        cwd=go2rtc.binary.parent,
        address=(url.hostname or "127.0.0.1", url.port or _DEFAULT_RTSP_PORT),
        log_path=go2rtc.log_file,
    )
