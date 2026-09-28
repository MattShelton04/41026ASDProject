"""Exact pixel comparison, change regions and reviewer images, computed on decoded RGBA arrays.

Nothing here decides whether a change is intended. Counts are exact; thresholds only add views
that ignore small channel differences, and every threshold keeps its own heatmap.
"""

from __future__ import annotations

import math
from collections import deque
from typing import Any, TypedDict

import numpy as np
from numpy.typing import NDArray

from scripts.visual.policy import VIEWPORT_HEIGHT, VIEWPORT_WIDTH

Pixels = NDArray[np.uint8]
Mask = NDArray[np.bool_]
THRESHOLDS = (0, 8, 16, 32)
SUBTLE_MAX_PIXELS = 128
SUBTLE_MAX_DELTA = 8
TILE = 8
MAX_REGIONS = 12
# A saturated magenta reads clearly against PropertyScope's green, sand and white surfaces.
HIGHLIGHT = (214, 36, 120)


class Region(TypedDict):
    x: int
    y: int
    width: int
    height: int
    pixels: int


class Analysis(TypedDict):
    threshold: int
    changed: int
    total: int
    percent: float
    bounds: Region | None
    regions: list[Region]
    regionCount: int


def align(base: Pixels, head: Pixels) -> tuple[Pixels, Pixels]:
    """Pad the shorter capture with transparent rows so both share one canvas.

    Rows that exist on one side only differ in alpha, so they always count as changed.
    """
    height = max(base.shape[0], head.shape[0])

    def pad(pixels: Pixels) -> Pixels:
        if pixels.shape[0] == height:
            return pixels
        extra = np.zeros((height - pixels.shape[0], pixels.shape[1], 4), dtype=np.uint8)
        return np.concatenate((pixels, extra), axis=0)

    return pad(base), pad(head)


def channel_delta(base: Pixels, head: Pixels) -> NDArray[np.uint8]:
    """Largest absolute RGBA channel difference per pixel."""
    difference = np.abs(base.astype(np.int16) - head.astype(np.int16)).max(axis=2)
    return difference.astype(np.uint8)


def _regions(mask: Mask) -> tuple[list[Region], int]:
    """Group changed pixels by 8-connected 8px tiles, clipped to the actual changed pixels."""
    height, width = mask.shape
    rows, columns = math.ceil(height / TILE), math.ceil(width / TILE)
    padded = np.zeros((rows * TILE, columns * TILE), dtype=bool)
    padded[:height, :width] = mask
    counts = padded.reshape(rows, TILE, columns, TILE).sum(axis=(1, 3))
    remaining = {(int(row), int(column)) for row, column in np.argwhere(counts > 0)}
    regions: list[Region] = []
    while remaining:
        start = remaining.pop()
        queue = deque([start])
        top, left, bottom, right, pixels = start[0], start[1], start[0], start[1], 0
        while queue:
            row, column = queue.popleft()
            pixels += int(counts[row, column])
            top, bottom = min(top, row), max(bottom, row)
            left, right = min(left, column), max(right, column)
            for d_row in (-1, 0, 1):
                for d_column in (-1, 0, 1):
                    neighbour = (row + d_row, column + d_column)
                    if neighbour in remaining:
                        remaining.remove(neighbour)
                        queue.append(neighbour)
        window = padded[top * TILE : (bottom + 1) * TILE, left * TILE : (right + 1) * TILE]
        ys, xs = np.nonzero(window)
        y0, x0 = top * TILE + int(ys.min()), left * TILE + int(xs.min())
        y1, x1 = top * TILE + int(ys.max()), left * TILE + int(xs.max())
        regions.append(
            Region(x=x0, y=y0, width=x1 - x0 + 1, height=y1 - y0 + 1, pixels=pixels),
        )
    regions.sort(key=lambda item: (-item["pixels"], item["y"], item["x"]))
    return regions[:MAX_REGIONS], len(regions)


def analyse(delta: NDArray[np.uint8], threshold: int) -> tuple[Analysis, Mask]:
    """Exact metrics for one threshold plus its changed-pixel mask."""
    mask: Mask = delta > threshold
    changed = int(mask.sum())
    bounds: Region | None = None
    regions: list[Region] = []
    region_count = 0
    if changed:
        ys, xs = np.nonzero(mask)
        bounds = Region(
            x=int(xs.min()),
            y=int(ys.min()),
            width=int(xs.max() - xs.min() + 1),
            height=int(ys.max() - ys.min() + 1),
            pixels=changed,
        )
        regions, region_count = _regions(mask)
    total = int(mask.size)
    analysis = Analysis(
        threshold=threshold,
        changed=changed,
        total=total,
        percent=round(100 * changed / total, 4) if total else 0.0,
        bounds=bounds,
        regions=regions,
        regionCount=region_count,
    )
    return analysis, mask


def classify(analyses: dict[int, Analysis], *, size_changed: bool) -> str:
    """Triage only: ``subtle`` is sparse and low-contrast, never proof a change is harmless."""
    if size_changed:
        return "changed"
    if analyses[0]["changed"] == 0:
        return "unchanged"
    if analyses[0]["changed"] <= SUBTLE_MAX_PIXELS and analyses[SUBTLE_MAX_DELTA]["changed"] == 0:
        return "subtle"
    return "changed"


def heatmap(mask: Mask) -> Pixels:
    """Transparent overlay with changed pixels in the highlight colour."""
    heat = np.zeros((*mask.shape, 4), dtype=np.uint8)
    heat[mask] = (*HIGHLIGHT, 220)
    return heat


def merge_areas(regions: list[Region], gap: int = 24) -> list[Region]:
    """Merge nearby regions into reviewable areas, largest first."""
    areas: list[Region] = [Region(**region) for region in regions]
    merged = True
    while merged:
        merged = False
        for i in range(len(areas)):
            for j in range(i + 1, len(areas)):
                a, b = areas[i], areas[j]
                if (
                    a["x"] - gap > b["x"] + b["width"]
                    or b["x"] - gap > a["x"] + a["width"]
                    or a["y"] - gap > b["y"] + b["height"]
                    or b["y"] - gap > a["y"] + a["height"]
                ):
                    continue
                x, y = min(a["x"], b["x"]), min(a["y"], b["y"])
                areas[i] = Region(
                    x=x,
                    y=y,
                    width=max(a["x"] + a["width"], b["x"] + b["width"]) - x,
                    height=max(a["y"] + a["height"], b["y"] + b["height"]) - y,
                    pixels=a["pixels"] + b["pixels"],
                )
                del areas[j]
                merged = True
                break
            if merged:
                break
    return sorted(areas, key=lambda item: (-item["pixels"], item["y"], item["x"]))


def area_key(areas: list[Region]) -> str:
    """Coarse signature: views whose areas coincide usually show one shared-component change."""
    return ";".join(
        sorted(
            ",".join(
                str(round(value / 8))
                for value in (area["x"], area["y"], area["width"], area["height"])
            )
            for area in areas
        )
    )


def focus_rect(
    area: Region,
    canvas_height: int,
    *,
    padding: int = 32,
    min_width: int = 480,
    min_height: int = 200,
) -> Region | None:
    """A readable 1:1 crop around an area, or ``None`` when the area is most of a viewport."""
    width = max(min_width, area["width"] + padding * 2)
    height = max(min_height, area["height"] + padding * 2)
    if width * height > VIEWPORT_WIDTH * VIEWPORT_HEIGHT / 2:
        return None
    width, height = min(VIEWPORT_WIDTH, width), min(canvas_height, height)
    x = round(min(VIEWPORT_WIDTH - width, max(0, area["x"] + area["width"] / 2 - width / 2)))
    y = round(min(canvas_height - height, max(0, area["y"] + area["height"] / 2 - height / 2)))
    return Region(x=x, y=y, width=width, height=height, pixels=0)


def preview_window(areas: list[Region], canvas_height: int) -> Region:
    """A full-width, viewport-tall window centred on the largest area, for PR comments."""
    height = min(VIEWPORT_HEIGHT, canvas_height)
    centre = areas[0]["y"] + areas[0]["height"] / 2 if areas else 0
    y = round(min(canvas_height - height, max(0, centre - height / 2)))
    return Region(x=0, y=y, width=VIEWPORT_WIDTH, height=height, pixels=0)


def crop(pixels: Pixels, rect: Region) -> Pixels:
    """Copy a rectangle out of an RGBA array."""
    y, x = rect["y"], rect["x"]
    return np.ascontiguousarray(pixels[y : y + rect["height"], x : x + rect["width"]])


def difference_image(after: Pixels, mask: Mask, areas: list[Region]) -> Pixels:
    """The after capture dimmed outside changed areas, changes tinted and each area outlined.

    Unlike a transparent heatmap this stays legible when GitHub scales it into a comment.
    """
    rgb = after[:, :, :3].astype(np.float32)
    height, width = mask.shape
    inside = np.zeros((height, width), dtype=bool)
    pad = 4
    for area in areas:
        inside[
            max(0, area["y"] - pad) : area["y"] + area["height"] + pad,
            max(0, area["x"] - pad) : area["x"] + area["width"] + pad,
        ] = True
    grey = rgb @ np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)
    dimmed = (rgb * 0.4 + grey[..., None] * 0.6) * 0.45 + 255 * 0.12
    out = np.where(inside[..., None], rgb, dimmed)
    tint = np.array(HIGHLIGHT, dtype=np.float32)
    out = np.where(mask[..., None], rgb * 0.3 + tint * 0.7, out)
    result = np.empty((height, width, 4), dtype=np.uint8)
    result[:, :, :3] = np.clip(out, 0, 255).astype(np.uint8)
    result[:, :, 3] = 255
    stroke = 2
    for area in areas:
        top = max(0, area["y"] - pad - stroke)
        left = max(0, area["x"] - pad - stroke)
        bottom = min(height, area["y"] + area["height"] + pad + stroke)
        right = min(width, area["x"] + area["width"] + pad + stroke)
        colour = (*HIGHLIGHT, 255)
        result[top : top + stroke, left:right] = colour
        result[bottom - stroke : bottom, left:right] = colour
        result[top:bottom, left : left + stroke] = colour
        result[top:bottom, right - stroke : right] = colour
    return result


def jsonable(analysis: Analysis) -> dict[str, Any]:
    """A plain dictionary copy for JSON output."""
    return dict(analysis)
