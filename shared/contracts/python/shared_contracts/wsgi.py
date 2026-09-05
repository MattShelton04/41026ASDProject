"""Framework-neutral, bounded JSON-object parsing at WSGI service boundaries."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any


def read_json_object(environ: Mapping[str, Any], *, max_bytes: int) -> dict[str, Any]:
    """Read exactly Content-Length bytes; never allow read(-1) or silent truncation.

    WSGI servers own transfer framing. This helper intentionally does not consume
    an unspecified-length stream. Empty bodies preserve the existing empty-object
    contract. Callers translate ValueError into their own Problem Details shape.
    """
    raw_length = environ.get("CONTENT_LENGTH")
    if raw_length is None or raw_length == "":
        raw_length = "0"
    if not isinstance(raw_length, str) or not raw_length.isascii() or not raw_length.isdecimal():
        raise ValueError("Content-Length must be a non-negative integer")
    length = int(raw_length)
    if length > max_bytes:
        raise ValueError("body_too_large")
    if length == 0:
        return {}
    body = environ["wsgi.input"].read(length)
    if len(body) != length:
        raise ValueError("incomplete JSON body")
    value = json.loads(body)
    if not isinstance(value, dict):
        raise ValueError("JSON body must be an object")
    return value
