"""Command-line entry point: `eos <command>`."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

from eyes_on_screen.config import DEFAULT_CONFIG_PATH, AppConfig, ConfigError, load_config
from eyes_on_screen.logging_setup import setup_logging
from eyes_on_screen.vision.models import ALL_MODELS, ModelError, download_model, missing_models

if TYPE_CHECKING:
    from eyes_on_screen.app import App
    from eyes_on_screen.video.source import VideoSource

log = logging.getLogger(__name__)

Handler = Callable[[AppConfig, argparse.Namespace], int]

EXIT_OK = 0
EXIT_CONFIG_ERROR = 2
EXIT_MODEL_ERROR = 3
EXIT_GO2RTC_ERROR = 4
EXIT_APPLE_TV_ERROR = 5


class _ConfigDumper(yaml.SafeDumper):
    """Block-style sections, but lists inline the way they are written: roi: [0.5, 0, 1, 1]."""


_ConfigDumper.add_representer(
    list,
    lambda dumper, data: dumper.represent_sequence("tag:yaml.org,2002:seq", data, flow_style=True),
)


def cmd_config_check(config: AppConfig, args: argparse.Namespace) -> int:
    """Print the effective config (defaults applied, paths resolved) and soft warnings."""
    print(f"Config OK: {args.config.resolve()}\n")
    dump = yaml.dump(config.model_dump(mode="json"), Dumper=_ConfigDumper, sort_keys=False)
    print(dump, end="")

    notes = []
    missing = missing_models(config.detection.models_dir)
    if missing:
        names = ", ".join(model.filename for model in missing)
        notes.append(f"models not downloaded yet: {names} (run `eos download-models`)")
    if config.apple_tv.identifier is None:
        notes.append("apple_tv.identifier is not set")
    if notes:
        print("\nNotes:")
        for note in notes:
            print(f"  - {note}")
    return EXIT_OK


def _with_camera(config: AppConfig, body: Callable[[VideoSource], None]) -> int:
    """Run `body` with a started video source, and go2rtc around it if configured."""
    # Imported here: OpenCV is slow to import and config-check does not need it.
    from eyes_on_screen.video.capture import create_source
    from eyes_on_screen.video.go2rtc import SupervisorError, go2rtc_supervisor

    try:
        with go2rtc_supervisor(config.go2rtc, config.video) or contextlib.nullcontext():
            source = create_source(config.video)
            source.start()
            try:
                body(source)
            finally:
                source.stop()
    except SupervisorError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_GO2RTC_ERROR
    except KeyboardInterrupt:
        pass
    return EXIT_OK


def cmd_download_models(config: AppConfig, args: argparse.Namespace) -> int:
    """Fetch the face models into detection.models_dir, verifying checksums."""
    models_dir = config.detection.models_dir
    for model in ALL_MODELS:
        print(f"{model.description} ({model.filename}): ", end="", flush=True)
        try:
            downloaded = download_model(model, models_dir, force=args.force)
        except ModelError as exc:
            print("failed")
            print(f"error: {exc}", file=sys.stderr)
            return EXIT_MODEL_ERROR
        print("downloaded" if downloaded else "already present")
    print(f"Models are in {models_dir}")
    return EXIT_OK


def cmd_run(config: AppConfig, args: argparse.Namespace) -> int:
    """The app itself: pause the Apple TV when viewers look away, resume when they look back."""
    from eyes_on_screen.app import App
    from eyes_on_screen.appletv.controller import AppleTvController
    from eyes_on_screen.vision.backends import create_face_analyzer

    try:
        analyzer = create_face_analyzer(config.detection, config.target.roi)
    except ModelError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_MODEL_ERROR
    identifier = config.apple_tv.identifier
    player = AppleTvController(identifier, config.apple_tv.credentials_file) if identifier else None
    if player is None:
        print(
            "note: apple_tv.identifier is not set, so nothing will be paused; the web UI "
            "still shows the camera, viewers and calibration (`eos atv scan`, `eos atv pair`)",
            file=sys.stderr,
        )

    def body(source: VideoSource) -> None:
        app = App(config, args.config, source, analyzer, player, dry_run=args.dry_run)
        asyncio.run(_serve(app, config))

    return _with_camera(config, body)


async def _serve(app: App, config: AppConfig) -> None:
    """Run the app, with the web UI around it when it is enabled and its port is free."""
    from eyes_on_screen.web.bridge import WebUi

    web = WebUi(config.web, app) if config.web.enabled else None
    if web is not None:
        try:
            await web.start()
        except OSError as exc:
            log.error("Web UI disabled: cannot listen on %s: %s", web.server.url, exc)
            web = None
    try:
        await app.run()
    finally:
        if web is not None:
            await web.stop()


def cmd_atv(config: AppConfig, args: argparse.Namespace) -> int:
    """Apple TV commands: scan, pair, status, play, pause."""
    # Imported here: pyatv pulls in aiohttp, zeroconf and cryptography.
    from eyes_on_screen.appletv import commands
    from eyes_on_screen.appletv.pairing import PairingError
    from eyes_on_screen.appletv.state import AppleTvError

    credentials = config.apple_tv.credentials_file
    explicit_id = getattr(args, "atv_id", None)  # `scan` has no --id
    identifier = explicit_id or config.apple_tv.identifier
    action = args.atv_command

    if action == "scan":
        coroutine = commands.scan_command(credentials)
    elif action == "pair":
        coroutine = commands.pair_command(credentials, explicit_id)
    elif identifier is None:
        print(
            "error: no Apple TV selected: set apple_tv.identifier in config.yaml "
            "or pass --id (see `eos atv scan`)",
            file=sys.stderr,
        )
        return EXIT_APPLE_TV_ERROR
    elif action == "status":
        coroutine = commands.status_command(identifier, credentials, watch=args.watch)
    else:
        coroutine = commands.remote_command(identifier, credentials, action)

    try:
        return asyncio.run(coroutine)
    except (AppleTvError, PairingError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_APPLE_TV_ERROR
    except KeyboardInterrupt:
        return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="eos",
        description="Pause Apple TV when the viewer looks away from the screen.",
    )
    parser.add_argument(
        "-c",
        "--config",
        type=Path,
        default=DEFAULT_CONFIG_PATH,
        help="path to the YAML config (default: %(default)s)",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="enable debug logging")

    commands = parser.add_subparsers(dest="command", required=True, metavar="<command>")
    run = commands.add_parser(
        "run", help="pause the Apple TV when viewers look away, resume when they look back"
    )
    run.add_argument(
        "--dry-run", action="store_true", help="only log what would be paused or resumed"
    )
    run.set_defaults(handler=cmd_run)
    check = commands.add_parser(
        "config-check", help="validate the config and print the effective values"
    )
    check.set_defaults(handler=cmd_config_check)
    download = commands.add_parser("download-models", help="download the face models")
    download.add_argument("--force", action="store_true", help="download even if present")
    download.set_defaults(handler=cmd_download_models)

    atv = commands.add_parser("atv", help="Apple TV: scan, pair, status, play, pause")
    atv.set_defaults(handler=cmd_atv)
    atv_commands = atv.add_subparsers(dest="atv_command", required=True, metavar="<action>")
    atv_commands.add_parser("scan", help="list Apple TVs and other AirPlay devices nearby")
    for name, help_text in (
        ("pair", "pair with the Apple TV (a PIN appears on the TV)"),
        ("status", "show what the Apple TV is playing"),
        ("play", "resume playback"),
        ("pause", "pause playback"),
    ):
        action = atv_commands.add_parser(name, help=help_text)
        action.add_argument(
            "--id", dest="atv_id", help="device identifier (default: apple_tv.identifier)"
        )
        if name == "status":
            action.add_argument(
                "--watch", action="store_true", help="keep printing changes (Ctrl+C to stop)"
            )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        config = load_config(args.config)
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_CONFIG_ERROR

    setup_logging(config.logging, verbose=args.verbose)
    handler: Handler = args.handler
    return handler(config, args)
