"""Screenshot PNG validation and pixel comparison for the visual regression harness."""

from __future__ import annotations

import struct
import zlib

import numpy as np
import pytest
from scripts.visual import pixels as px
from scripts.visual.pngsafe import decode_png, encode_png, png_dimensions
from scripts.visual.policy import VIEWPORT_WIDTH


def _page(height: int = 400, colour: tuple[int, int, int] = (245, 244, 238)) -> px.Pixels:
    image = np.zeros((height, VIEWPORT_WIDTH, 4), dtype=np.uint8)
    image[..., :3] = colour
    image[..., 3] = 255
    return image


def _chunk(kind: bytes, body: bytes) -> bytes:
    return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))


def test_png_round_trip_is_deterministic_and_validated() -> None:
    image = _page()
    image[10:20, 30:40, :3] = (40, 84, 66)
    data = encode_png(image)
    assert data == encode_png(image.copy())
    assert png_dimensions(data) == (VIEWPORT_WIDTH, 400)
    assert np.array_equal(decode_png(data), image)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda data: data[:-1],
        lambda data: b"\x89PNG\r\n\x1a\x0b" + data[8:],
        # A corrupted CRC anywhere invalidates the file.
        lambda data: data[:40] + bytes([data[40] ^ 1]) + data[41:],
        # Ancillary chunks (text, colour profiles) are not accepted.
        lambda data: data[:33] + _chunk(b"tEXt", b"Comment\x00hi") + data[33:],
    ],
)
def test_png_validation_rejects_malformed_or_decorated_files(mutate: object) -> None:
    data = encode_png(_page())
    assert callable(mutate)
    assert png_dimensions(mutate(data)) is None
    with pytest.raises(ValueError):
        decode_png(mutate(data))


def test_png_validation_rejects_unexpected_dimensions() -> None:
    narrow = np.zeros((400, 800, 4), dtype=np.uint8)
    assert png_dimensions(encode_png(narrow)) is None
    assert png_dimensions(encode_png(_page(height=100))) is None


def test_identical_pages_are_unchanged() -> None:
    delta = px.channel_delta(_page(), _page())
    analyses = {threshold: px.analyse(delta, threshold)[0] for threshold in px.THRESHOLDS}
    assert px.classify(analyses, size_changed=False) == "unchanged"
    assert analyses[0]["bounds"] is None


def test_sparse_low_contrast_differences_are_subtle() -> None:
    before, after = _page(), _page()
    after[5, 5, 0] += 4
    delta = px.channel_delta(before, after)
    analyses = {threshold: px.analyse(delta, threshold)[0] for threshold in px.THRESHOLDS}
    assert analyses[0]["changed"] == 1
    assert analyses[8]["changed"] == 0
    assert px.classify(analyses, size_changed=False) == "subtle"


def test_visible_changes_are_changed_with_regions_and_exact_bounds() -> None:
    before, after = _page(), _page()
    after[100:120, 200:260, :3] = (230, 111, 81)
    after[300:302, 1000:1010, :3] = (0, 0, 0)
    delta = px.channel_delta(before, after)
    analysis, mask = px.analyse(delta, 0)
    assert analysis["changed"] == 20 * 60 + 2 * 10
    assert analysis["bounds"] == {"x": 200, "y": 100, "width": 810, "height": 202, "pixels": 1220}
    assert analysis["regionCount"] == 2
    largest = analysis["regions"][0]
    assert (largest["x"], largest["y"], largest["width"], largest["height"]) == (200, 100, 60, 20)
    analyses = {threshold: px.analyse(delta, threshold)[0] for threshold in px.THRESHOLDS}
    assert px.classify(analyses, size_changed=False) == "changed"
    assert px.heatmap(mask)[110, 210, 3] > 0


def test_height_changes_are_always_changed_and_padding_counts() -> None:
    base, head = px.align(_page(400), _page(420))
    assert base.shape == head.shape == (420, VIEWPORT_WIDTH, 4)
    analysis, _ = px.analyse(px.channel_delta(base, head), 0)
    assert analysis["changed"] == 20 * VIEWPORT_WIDTH
    assert px.classify({0: analysis, 8: analysis}, size_changed=True) == "changed"


def test_nearby_regions_merge_and_windows_stay_inside_the_canvas() -> None:
    regions: list[px.Region] = [
        {"x": 10, "y": 10, "width": 10, "height": 10, "pixels": 100},
        {"x": 30, "y": 10, "width": 10, "height": 10, "pixels": 100},
        {"x": 900, "y": 900, "width": 5, "height": 5, "pixels": 25},
    ]
    merged = px.merge_areas(regions)
    assert len(merged) == 2
    window = px.preview_window(merged, 1200)
    assert window["y"] >= 0
    assert window["y"] + window["height"] <= 1200
    assert px.area_key(merged) == px.area_key(list(reversed(merged)))
