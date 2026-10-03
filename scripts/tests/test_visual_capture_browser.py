"""Real Chromium regressions for rendered WebGL surfaces below the viewport."""

from __future__ import annotations

import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from PIL import Image
from playwright.sync_api import Error, sync_playwright
from scripts.visual.capture import CHROMIUM_ARGS, capture_case
from scripts.visual.cases import VisualCase

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
PAGE = b"""<!doctype html><link rel="stylesheet" href="/page.css">
<link rel="stylesheet" href="/maplibre-gl.css">
<h1>Rendered map</h1><div class="ps-map__status" data-state="loading">Loading map</div>
<div class="map-frame"><div id="map" class="map-surface"></div></div>
<script src="/maplibre-gl.js"></script>
<canvas id="chart" width="40" height="40"></canvas><div id="vh"></div>
<div id="tail"></div>
<script src="/page.js"></script>"""
CSS = b"""body { margin: 0; } h1 { margin: 0; height: 40px; }
.ps-map__status { height: 20px; }
.map-frame { position: relative; overflow: hidden; border: 1px solid black; border-radius: 8px;
  width: 1084px; height: 318px; margin-top: 1770px; margin-left: 296px; }
.map-surface, .map-surface.maplibregl-map { position: absolute; inset: 0; }
#chart { display: block; }
#tail { height: 1500px; }
#vh { position: absolute; left: 1400px; top: 0; width: 10px; height: 100vh; background: red; }"""
JAVASCRIPT = b"""const map = new maplibregl.Map({
  container: 'map', center: [0, 0], zoom: 12, attributionControl: false,
  style: {version: 8, sources: {}, layers: [
    {id: 'background', type: 'background', paint: {'background-color': '#0000ff'}}
  ]}
});
document.querySelector('#chart').getContext('2d').fillRect(0, 0, 40, 40);
map.on('load', () => setTimeout(() => {
  map.addSource('property', {type: 'geojson', data: {
    type: 'FeatureCollection', features: [{type: 'Feature', properties: {},
    geometry: {type: 'Point', coordinates: [0, 0]}}]
  }});
  map.addLayer({id: 'property', source: 'property', type: 'circle',
    paint: {'circle-color': '#ff0000', 'circle-radius': 30}});
  map.once('idle', () => document.querySelector('.ps-map__status').dataset.state = 'ready');
}, 900));"""


class CanvasPage(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        pass

    def do_GET(self) -> None:
        body, content_type = {
            "/": (PAGE, "text/html"),
            "/page.css": (CSS, "text/css"),
            "/page.js": (JAVASCRIPT, "text/javascript"),
        }.get(self.path, (b"", "text/plain"))
        if self.path in {"/maplibre-gl.js", "/maplibre-gl.css"}:
            vendor = REPOSITORY_ROOT / "shared/frontend/mapping/vendor" / self.path.lstrip("/")
            body = vendor.read_bytes()
            content_type = "text/javascript" if self.path.endswith(".js") else "text/css"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "img-src 'self' data:; worker-src blob:",
        )
        self.end_headers()
        self.wfile.write(body)


def test_full_page_capture_keeps_settled_webgl_pixels_without_changing_viewport(
    tmp_path: Path,
) -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 0), CanvasPage)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    try:
        with sync_playwright() as playwright:
            try:
                browser = playwright.chromium.launch(args=list(CHROMIUM_ARGS))
            except Error as exc:
                if (
                    "Executable doesn't exist" in str(exc)
                    and os.getenv("VISUAL_REQUIRE_BROWSER") != "1"
                ):
                    pytest.skip("Playwright Chromium is not installed")
                raise
            try:
                case = VisualCase("shared-canvas", "stack", "/", "rendered map", "h1")
                captures = [
                    capture_case(browser, case, f"http://127.0.0.1:{server.server_port}", tmp_path)
                    for _ in range(3)
                ]
            finally:
                browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert all(record["status"] == "captured" for record in captures), captures
    assert len({record["sha256"] for record in captures}) == 1
    assert all(record["attempts"] == 2 for record in captures)
    assert captures[0]["notes"] == ["snapshotted 1 rendered WebGL canvas(es) for full-page capture"]
    with Image.open(tmp_path / "shared-canvas.png") as image:
        assert image.size == (1440, 3690)
        pixels = image.convert("RGB")
        # Real vendored MapLibre renders below the viewport. The map's busy marker must settle
        # before freezing, and the delayed property marker must survive offscreen compositing.
        assert pixels.getpixel((900, 2050)) == (0, 0, 255)
        assert pixels.getpixel((839, 1990)) == (255, 0, 0)
        assert pixels.getpixel((20, 2160)) == (0, 0, 0)  # the 2D canvas still renders normally
        assert pixels.getpixel((1405, 999)) == (255, 0, 0)
        assert pixels.getpixel((1405, 1000)) == (255, 255, 255)  # 100vh remains 1000px
