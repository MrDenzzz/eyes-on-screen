import socket
import sys
import time
from collections.abc import Callable
from pathlib import Path

import pytest

from eyes_on_screen.config import Go2rtcConfig, VideoConfig
from eyes_on_screen.video import go2rtc as go2rtc_module
from eyes_on_screen.video.go2rtc import (
    ProcessSupervisor,
    SupervisorError,
    go2rtc_supervisor,
    is_listening,
)

# Stands in for go2rtc: listens on a port for a while, then exits.
FAKE_SERVER = (
    "import socket, sys, time\n"
    "s = socket.socket(); s.bind(('127.0.0.1', int(sys.argv[1]))); s.listen()\n"
    "time.sleep(float(sys.argv[2]))\n"
)


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def supervisor(tmp_path: Path, port: int, *script_args: str, script: str = FAKE_SERVER):
    return ProcessSupervisor(
        "fake",
        [sys.executable, "-c", script, *script_args],
        cwd=tmp_path,
        address=("127.0.0.1", port),
        log_path=tmp_path / "fake.log",
    )


def wait_until(predicate: Callable[[], bool], timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() > deadline:
            pytest.fail("condition not reached in time")
        time.sleep(0.02)


def test_starts_the_process_and_stops_it_on_exit(tmp_path):
    port = free_port()

    with supervisor(tmp_path, port, str(port), "30") as sup:
        assert sup.spawned == 1
        assert is_listening("127.0.0.1", port)

    wait_until(lambda: not is_listening("127.0.0.1", port))


def test_running_instance_is_reused_and_left_alone(tmp_path):
    port = free_port()
    with socket.socket() as existing:
        existing.bind(("127.0.0.1", port))
        existing.listen()

        with supervisor(tmp_path, port, str(port), "30") as sup:
            assert sup.spawned == 0

        assert is_listening("127.0.0.1", port)


def test_crashed_process_is_restarted(tmp_path, monkeypatch):
    monkeypatch.setattr(go2rtc_module, "WATCH_INTERVAL_S", 0.05)
    monkeypatch.setattr(go2rtc_module, "RESTART_DELAY_S", 0.05)
    port = free_port()

    # Lives long enough to pass the readiness check, then "crashes".
    with supervisor(tmp_path, port, str(port), "2") as sup:
        wait_until(lambda: sup.spawned >= 2, timeout=10)


def test_process_that_exits_at_once_is_reported(tmp_path):
    sup = supervisor(tmp_path, free_port(), script="raise SystemExit(3)")

    with pytest.raises(SupervisorError, match="exited right away with code 3"):
        sup.start()


def test_process_that_never_listens_is_stopped(tmp_path, monkeypatch):
    monkeypatch.setattr(go2rtc_module, "READY_TIMEOUT_S", 0.5)
    sup = supervisor(tmp_path, free_port(), script="import time; time.sleep(30)")

    with pytest.raises(SupervisorError, match="did not open"):
        sup.start()

    assert sup._process is None  # terminated, not left behind


class TestGo2rtcSupervisor:
    RTSP = VideoConfig(source="rtsp", rtsp_url="rtsp://127.0.0.1:8554/c400")

    def files(self, tmp_path: Path) -> Go2rtcConfig:
        binary, config = tmp_path / "go2rtc.exe", tmp_path / "go2rtc.yaml"
        binary.touch()
        config.touch()
        return Go2rtcConfig(autostart=True, binary=binary, config_file=config, log_file=None)

    def test_not_managed_when_autostart_is_off(self, tmp_path):
        config = self.files(tmp_path).model_copy(update={"autostart": False})

        assert go2rtc_supervisor(config, self.RTSP) is None

    def test_not_managed_for_a_webcam(self, tmp_path):
        assert go2rtc_supervisor(self.files(tmp_path), VideoConfig(source="webcam")) is None

    def test_runs_the_binary_with_its_config_and_waits_for_the_rtsp_port(self, tmp_path):
        config = self.files(tmp_path)

        sup = go2rtc_supervisor(config, self.RTSP)

        assert sup is not None
        assert sup._command == [str(config.binary), "-c", str(config.config_file)]
        assert sup._address == ("127.0.0.1", 8554)

    def test_missing_binary_is_reported(self, tmp_path):
        config = self.files(tmp_path)
        config.binary.unlink()

        with pytest.raises(SupervisorError, match="binary not found"):
            go2rtc_supervisor(config, self.RTSP)
