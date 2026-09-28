"""Fixed capture and publication limits shared by the capture harness and the trusted reporter."""

from __future__ import annotations

import re
from typing import Final

VIEWPORT_WIDTH: Final = 1440
VIEWPORT_HEIGHT: Final = 1000
# Full-page captures are clipped to this height. Long pages still compare their first 6000 px;
# anything below is reported as a limitation rather than silently ignored.
MAX_CAPTURE_HEIGHT: Final = 6000
MIN_CAPTURE_HEIGHT: Final = 200
# A fixed wall clock keeps relative dates ("3 days ago") and "today" markers identical
# on both sides.
FIXED_TIME: Final = "2026-09-01T10:00:00+10:00"
LOCALE: Final = "en-AU"
TIMEZONE: Final = "Australia/Sydney"

# Chromium re-rasterises only invalidated tiles by default, so blurred shadows can differ by 1/255
# between fresh contexts; Skia's CPU-specific SIMD paths differ between hosted runner CPUs.
CHROMIUM_ARGS: Final = (
    "--disable-partial-raster",
    "--disable-skia-runtime-opts",
    "--force-color-profile=srgb",
    "--font-render-hinting=none",
)

MAX_VIEWS: Final = 160
MAX_PNG_BYTES: Final = 16_000_000
MAX_JSON_BYTES: Final = 400_000
CASE_ID: Final = re.compile(r"^[a-z][a-z0-9-]{0,63}$")
SHA: Final = re.compile(r"^[a-f0-9]{40}$")
IMAGE_NAME: Final = re.compile(r"^[a-f0-9]{64}\.png$")
PROVIDERS: Final = ("fixture", "stack")
REVISIONS: Final = ("base", "head")

# Stable review sections. Their IDs appear in URLs and retained history, so never rename one.
SECTIONS: Final = (
    ("shared", "Shared"),
    ("feature-1", "Feature 1 · Property data"),
    ("feature-2", "Feature 2 · Sales & market"),
    ("feature-3", "Feature 3 · Suburb context"),
    ("feature-4", "Feature 4 · Site & planning"),
    ("feature-5", "Feature 5 · Buyer workspace"),
)
SECTION_IDS: Final = tuple(section for section, _ in SECTIONS)


def section_for(case_id: str, declared: object = None) -> str:
    """Return a known section for a case, inferring one from its ID prefix when needed."""
    if isinstance(declared, str) and declared in SECTION_IDS:
        return declared
    for number in range(1, 6):
        if case_id.startswith(f"f{number}-"):
            return f"feature-{number}"
    return "shared"


def section_label(section: str) -> str:
    """Return the display label for a section ID."""
    return dict(SECTIONS).get(section, section)
