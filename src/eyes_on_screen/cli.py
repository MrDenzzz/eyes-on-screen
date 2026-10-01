"""Command-line entry point: `eos <command>`."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

import yaml

from eyes_on_screen.config import DEFAULT_CONFIG_PATH, AppConfig, ConfigError, load_config
from eyes_on_screen.logging_setup import setup_logging

Handler = Callable[[AppConfig, argparse.Namespace], int]

EXIT_OK = 0
EXIT_CONFIG_ERROR = 2


def cmd_config_check(config: AppConfig, args: argparse.Namespace) -> int:
    """Print the effective config (defaults applied, paths resolved) and soft warnings."""
    print(f"Config OK: {args.config.resolve()}\n")
    # default_flow_style=None keeps scalar lists inline: roi: [0.5, 0.0, 1.0, 1.0]
    dump = yaml.safe_dump(config.model_dump(mode="json"), sort_keys=False, default_flow_style=None)
    print(dump, end="")

    notes = []
    if not config.detection.model_path.is_file():
        notes.append(f"detection.model_path does not exist yet: {config.detection.model_path}")
    if config.apple_tv.identifier is None:
        notes.append("apple_tv.identifier is not set")
    if notes:
        print("\nNotes:")
        for note in notes:
            print(f"  - {note}")
    return EXIT_OK


def cmd_preview(config: AppConfig, args: argparse.Namespace) -> int:
    """Open the configured video source and show the raw stream."""
    # Imported here: OpenCV is slow to import and config-check does not need it.
    from eyes_on_screen.debug.preview import run_preview
    from eyes_on_screen.video.capture import create_source

    source = create_source(config.video)
    source.start()
    try:
        run_preview(source)
    except KeyboardInterrupt:
        pass
    finally:
        source.stop()
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
    check = commands.add_parser(
        "config-check", help="validate the config and print the effective values"
    )
    check.set_defaults(handler=cmd_config_check)
    preview = commands.add_parser("preview", help="show the raw video stream (q/Esc to quit)")
    preview.set_defaults(handler=cmd_preview)
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
