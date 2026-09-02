"""Contracts for the deterministic screenshots embedded in the root README."""

from __future__ import annotations

import struct
from pathlib import Path

from scripts.readme_screenshots import DEFAULT_OUTPUT, SCREENSHOTS, VIEWPORT

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def test_readme_embeds_each_consistent_screenshot() -> None:
    readme = (REPOSITORY_ROOT / "README.md").read_text(encoding="utf-8")
    expected_size = (VIEWPORT["width"], VIEWPORT["height"])

    for screenshot in SCREENSHOTS:
        image = DEFAULT_OUTPUT / screenshot.filename
        content = image.read_bytes()

        assert f"docs/images/readme/{screenshot.filename}" in readme
        assert content.startswith(b"\x89PNG\r\n\x1a\n")
        assert struct.unpack(">II", content[16:24]) == expected_size
