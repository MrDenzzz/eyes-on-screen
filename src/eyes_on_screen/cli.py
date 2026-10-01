"""Command-line entry point: `eos <command>`."""

from __future__ import annotations

import argparse
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
        "--record", type=Path, metavar="CSV", help="write the target's pose per frame to a CSV"
    )
    pose.set_defaults(handler=cmd_pose)
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
