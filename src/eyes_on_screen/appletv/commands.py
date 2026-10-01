"""`eos atv ...`: scan, pair, status and manual play/pause."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

from tabulate import tabulate

from eyes_on_screen.appletv.controller import AppleTvController
from eyes_on_screen.appletv.pairing import is_apple_tv, load_storage, pair_device, pick_device, scan
from eyes_on_screen.appletv.state import Playback, PlayerState

COMMAND_CONFIRM_TIMEOUT_S = 3.0


async def scan_command(credentials_file: Path) -> int:
    storage = await load_storage(credentials_file)
    devices = await scan(storage)
    if not devices:
        print("No AirPlay devices found.")
        return 1

    rows = []
    for device in sorted(devices, key=lambda d: not is_apple_tv(d)):
        protocols = ", ".join(
            f"{s.protocol.name}: {'paired' if s.credentials else s.pairing.name.lower()}"
            for s in device.services
        )
        rows.append(
            [
                "*" if is_apple_tv(device) else "",
                device.name,
                device.device_info.model_str,
                str(device.address),
                device.identifier,
                protocols,
            ]
        )
    print(tabulate(rows, headers=["", "Name", "Model", "Address", "Identifier", "Protocols"]))
    print("\n* Apple TV. Pair it with `eos atv pair` and put its identifier into config.yaml.")
    return 0


async def pair_command(credentials_file: Path, identifier: str | None) -> int:
    storage = await load_storage(credentials_file)
    device = pick_device(await scan(storage), identifier)
    print(f"Pairing with {device.name} ({device.address}). A PIN will appear on the TV.")
    await pair_device(device, storage, _read_pin)
    print(f"\nPaired. Credentials are in {credentials_file}.")
    print(f'Put this into config.yaml:\n\napple_tv:\n  identifier: "{device.identifier}"\n')

    controller = AppleTvController(device.identifier, credentials_file)
    await controller.connect()
    try:
        print(f"Connection check: {controller.state}")
    finally:
        await controller.close()
    return 0


async def status_command(identifier: str, credentials_file: Path, watch: bool) -> int:
    if not watch:
        controller = AppleTvController(identifier, credentials_file)
        await controller.connect()
        try:
            print(f"{controller.name}: {controller.state}")
        finally:
            await controller.close()
        return 0

    def show(state: PlayerState | None) -> None:
        print(f"{time.strftime('%H:%M:%S')}  {state or 'disconnected'}", flush=True)

    controller = AppleTvController(identifier, credentials_file, on_state=show)
    print("Watching player state (Ctrl+C to stop)...")
    try:
        await controller.run_forever()
    finally:
        await controller.close()
    return 0


async def remote_command(identifier: str, credentials_file: Path, action: str) -> int:
    """Send play or pause and wait until a push update confirms it."""
    expected = Playback.PLAYING if action == "play" else Playback.PAUSED
    confirmed = asyncio.Event()

    def on_state(state: PlayerState | None) -> None:
        if state is not None and state.playback is expected:
            confirmed.set()

    controller = AppleTvController(identifier, credentials_file, on_state=on_state)
    await controller.connect()
    try:
        print(f"Before: {controller.state}")
        confirmed.clear()
        await (controller.play() if action == "play" else controller.pause())
        try:
            await asyncio.wait_for(confirmed.wait(), COMMAND_CONFIRM_TIMEOUT_S)
        except TimeoutError:
            wait = f"{COMMAND_CONFIRM_TIMEOUT_S:.0f}s"
            print(f"After:  {controller.state} (no confirmation within {wait})")
            return 1
        print(f"After:  {controller.state}")
    finally:
        await controller.close()
    return 0


async def _read_pin(prompt: str) -> str:
    # input() blocks, so it runs in a thread while pyatv keeps the session alive.
    pin = await asyncio.get_running_loop().run_in_executor(None, input, prompt)
    return pin.strip()
