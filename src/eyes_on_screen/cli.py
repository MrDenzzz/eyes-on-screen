"""Command-line entry point: `eos <command>`."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

from eyes_on_screen.config import DEFAULT_CONFIG_PATH, AppConfig, ConfigError, load_config
from eyes_on_screen.logging_setup import setup_logging
from eyes_on_screen.vision.models import ALL_MODELS, ModelError, download_model, missing_models

if TYPE_CHECKING:
    from eyes_on_screen.video.source import VideoSource

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


def cmd_preview(config: AppConfig, args: argparse.Namespace) -> int:
    """Open the configured video source and show the raw stream."""
    from eyes_on_screen.debug.preview import run_preview

    return _with_camera(config, run_preview)


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


def cmd_pose(config: AppConfig, args: argparse.Namespace) -> int:
    """Live face and head-pose analysis in a debug window, with calibration."""
    # Imported here: MediaPipe and OpenCV are slow to import.
    from eyes_on_screen.debug.pose_view import run_pose_view
    from eyes_on_screen.vision.backends import create_face_analyzer

    try:
        analyzer = create_face_analyzer(config.detection, config.target.roi)
    except ModelError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_MODEL_ERROR

    def body(source: VideoSource) -> None:
        run_pose_view(
            source,
            analyzer,
            config.pose,
            config.target.roi,
            config.video.process_fps,
            record=args.record,
        )

    return _with_camera(config, body)


def cmd_run(config: AppConfig, args: argparse.Namespace) -> int:
    """The app itself: pause the Apple TV when viewers look away, resume when they look back."""
    from eyes_on_screen.app import App
    from eyes_on_screen.vision.backends import create_face_analyzer

    if config.apple_tv.identifier is None:
        print(
            "error: apple_tv.identifier is not set (find it with `eos atv scan`, "
            "then pair with `eos atv pair`)",
            file=sys.stderr,
        )
        return EXIT_APPLE_TV_ERROR
    try:
        analyzer = create_face_analyzer(config.detection, config.target.roi)
    except ModelError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_MODEL_ERROR

    def body(source: VideoSource) -> None:
        app = App(config, args.config, source, analyzer, dry_run=args.dry_run, debug=args.debug)
        asyncio.run(app.run())

    return _with_camera(config, body)


def cmd_atv(config: AppConfig, args: argparse.Namespace) -> int:
    """Apple TV commands: scan, pair, status, play, pause."""
    # Imported here: pyatv pulls in aiohttp, zeroconf and cryptography.
    from eyes_on_screen.appletv import commands
    from eyes_on_screen.appletv.controller import AppleTvError
    from eyes_on_screen.appletv.pairing import PairingError

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
    run.add_argument("--debug", action="store_true", help="show the live debug window")
    run.add_argument(
        "--dry-run", action="store_true", help="only log what would be paused or resumed"
    )
    run.set_defaults(handler=cmd_run)
    check = commands.add_parser(
        "config-check", help="validate the config and print the effective values"
    )
    check.set_defaults(handler=cmd_config_check)
    preview = commands.add_parser("preview", help="show the raw video stream (q/Esc to quit)")
    preview.set_defaults(handler=cmd_preview)
    download = commands.add_parser("download-models", help="download the face models")
    download.add_argument("--force", action="store_true", help="download even if present")
    download.set_defaults(handler=cmd_download_models)
    pose = commands.add_parser(
        "pose", help="live head-pose view and calibration (c: calibrate, q: quit)"
    )
    pose.add_argument(
        "--record",
        type=Path,
        metavar="CSV",
        help="write the target's pose and eye scores per frame to a CSV; "
        "keys 1-3 label what the viewer does (1 screen, 2 phone, 3 elsewhere, 0 none)",
    )
    pose.set_defaults(handler=cmd_pose)

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
