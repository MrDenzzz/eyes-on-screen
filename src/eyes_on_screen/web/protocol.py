"""Wire format between `eos run` and the browser.

Text messages are JSON objects with a "type". Video frames are binary messages:
a 4-byte big-endian header length, the JSON header, then the JPEG. The header
carries the analysis of that very frame, so boxes never drift from the faces.
"""

from __future__ import annotations

import json
import struct
from typing import Any

import cv2
import numpy as np

_LENGTH = struct.Struct(">I")


def encode_frame(
    image: np.ndarray, header: dict[str, Any], *, max_width: int, quality: int
) -> bytes:
    height, width = image.shape[:2]
    if width > max_width:
        size = (max_width, round(height * max_width / width))
        image = cv2.resize(image, size, interpolation=cv2.INTER_AREA)
    ok, jpeg = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, quality])
    if not ok:
        raise ValueError("JPEG encoding failed")
    head = json.dumps(header, separators=(",", ":")).encode()
    return _LENGTH.pack(len(head)) + head + jpeg.tobytes()


def decode_frame(packet: bytes) -> tuple[dict[str, Any], bytes]:
    """Inverse of encode_frame (the browser does the same in JavaScript)."""
    (length,) = _LENGTH.unpack_from(packet)
    start = _LENGTH.size
    return json.loads(packet[start : start + length]), packet[start + length :]
