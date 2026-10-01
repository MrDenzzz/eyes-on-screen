"""Finding Apple TVs on the network and pairing with them (credentials kept locally)."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from pathlib import Path

import pyatv
from pyatv.const import OperatingSystem, PairingRequirement, Protocol
from pyatv.interface import BaseConfig
from pyatv.storage.file_storage import FileStorage

log = logging.getLogger(__name__)

SCAN_TIMEOUT_S = 5
REMOTE_NAME = "eyes-on-screen"
# Since tvOS 15 the media remote protocol (play/pause, push updates) is tunnelled over
# AirPlay, so pairing AirPlay is what makes control work. Companion is paired as well,
# as pyatv's own setup wizard does; RAOP (audio streaming) is not needed.
PAIRED_PROTOCOLS = (Protocol.AirPlay, Protocol.Companion)

PinReader = Callable[[str], Awaitable[str]]


class PairingError(Exception):
    """Pairing could not be completed. User-facing message."""


async def load_storage(path: Path) -> FileStorage:
    """pyatv's file storage at `path`; credentials from pairing end up there."""
    path.parent.mkdir(parents=True, exist_ok=True)
    storage = FileStorage(str(path), asyncio.get_running_loop())
    await storage.load()
    return storage


async def scan(
    storage: FileStorage, identifier: str | None = None, timeout: float = SCAN_TIMEOUT_S
) -> list[BaseConfig]:
    """Devices on the network, with stored credentials applied."""
    return await pyatv.scan(
        asyncio.get_running_loop(), identifier=identifier, timeout=timeout, storage=storage
    )


def is_apple_tv(config: BaseConfig) -> bool:
    return config.device_info.operating_system is OperatingSystem.TvOS


def pick_device(devices: list[BaseConfig], identifier: str | None) -> BaseConfig:
    """The device to pair: the given identifier, or the only Apple TV on the network."""
    if identifier is not None:
        for device in devices:
            if identifier in device.all_identifiers:
                return device
        raise PairingError(f"no device with identifier {identifier} found (asleep or off?)")
    apple_tvs = [device for device in devices if is_apple_tv(device)]
    if len(apple_tvs) == 1:
        return apple_tvs[0]
    if not apple_tvs:
        raise PairingError("no Apple TV found on the network (asleep, off or another network?)")
    raise PairingError("several Apple TVs found: pass --id with the one to pair (see eos atv scan)")


async def pair_device(config: BaseConfig, storage: FileStorage, read_pin: PinReader) -> None:
    """Pair every protocol in PAIRED_PROTOCOLS that needs it and save the credentials."""
    for protocol in PAIRED_PROTOCOLS:
        service = config.get_service(protocol)
        if service is None:
            log.info("%s is not offered by %s, skipping", protocol.name, config.name)
            continue
        if service.pairing not in (PairingRequirement.Mandatory, PairingRequirement.Optional):
            log.info("%s needs no pairing (%s)", protocol.name, service.pairing.name)
            continue
        if service.credentials:
            log.info("%s is already paired", protocol.name)
            continue

        handler = await pyatv.pair(
            config, protocol, asyncio.get_running_loop(), storage=storage, name=REMOTE_NAME
        )
        try:
            await handler.begin()
            if handler.device_provides_pin:
                handler.pin(await read_pin(f"{protocol.name}: enter the PIN shown on the TV: "))
            await handler.finish()
            if not handler.has_paired:
                raise PairingError(f"pairing {protocol.name} failed (wrong PIN?)")
        finally:
            await handler.close()
        # Credentials live in the storage's settings; persist after every protocol so a
        # failure later on does not throw away what already worked.
        await storage.save()
        log.info("Paired %s", protocol.name)
