"""Validate untrusted screenshot PNGs before decoding them in the trusted reporter.

Chromium screenshots contain only IHDR, IDAT and IEND chunks with 8-bit, non-interlaced RGB or
RGBA pixels. Everything else (repeated headers, colour profiles, gamma, text or oversized images)
is rejected before Pillow sees the bytes, so an artifact cannot change how pixels are interpreted.
"""

from __future__ import annotations

import io
import struct
import zlib

import numpy as np
from numpy.typing import NDArray
from PIL import Image

from scripts.visual.policy import (
    MAX_CAPTURE_HEIGHT,
    MAX_PNG_BYTES,
    MIN_CAPTURE_HEIGHT,
    VIEWPORT_WIDTH,
)

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
Pixels = NDArray[np.uint8]


def png_dimensions(data: bytes) -> tuple[int, int] | None:
    """Return (width, height) for an acceptable screenshot PNG, otherwise ``None``."""
    if len(data) < 57 or len(data) > MAX_PNG_BYTES or not data.startswith(PNG_SIGNATURE):
        return None
    offset, header, has_data, chunks = 8, None, False, 0
    while offset + 12 <= len(data):
        chunks += 1
        if chunks > 20_000:
            return None
        (size,) = struct.unpack(">I", data[offset : offset + 4])
        kind = data[offset + 4 : offset + 8]
        end = offset + 12 + size
        if end > len(data):
            return None
        body = data[offset + 8 : offset + 8 + size]
        (crc,) = struct.unpack(">I", data[offset + 8 + size : end])
        if zlib.crc32(kind + body) != crc:
            return None
        if kind == b"IHDR":
            if header is not None or offset != 8 or size != 13:
                return None
            width, height, depth, colour, compression, filtering, interlace = struct.unpack(
                ">IIBBBBB", body
            )
            if (
                width != VIEWPORT_WIDTH
                or not MIN_CAPTURE_HEIGHT <= height <= MAX_CAPTURE_HEIGHT
                or depth != 8
                or colour not in (2, 6)
                or (compression, filtering, interlace) != (0, 0, 0)
            ):
                return None
            header = (width, height)
        elif header is None:
            return None
        elif kind == b"IDAT":
            has_data = True
        elif kind == b"IEND":
            return header if size == 0 and has_data and end == len(data) else None
        else:
            return None
        offset = end
    return None


def decode_png(data: bytes) -> Pixels:
    """Decode a validated screenshot into an ``(height, width, 4)`` RGBA array."""
    dimensions = png_dimensions(data)
    if dimensions is None:
        raise ValueError("unsupported or malformed screenshot PNG")
    with Image.open(io.BytesIO(data)) as image:
        image.load()
        if image.size != dimensions:
            raise ValueError("decoded PNG size does not match its header")
        pixels = np.asarray(image.convert("RGBA"), dtype=np.uint8)
    return pixels


def encode_png(pixels: Pixels) -> bytes:
    """Encode an RGBA array deterministically (no metadata, fixed compression)."""
    buffer = io.BytesIO()
    if pixels.ndim != 3 or pixels.shape[2] != 4 or pixels.dtype != np.uint8:
        raise ValueError("expected an RGBA uint8 array")
    Image.fromarray(pixels).save(buffer, format="PNG", optimize=False, compress_level=6)
    return buffer.getvalue()
