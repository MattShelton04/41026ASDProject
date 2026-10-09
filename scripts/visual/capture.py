"""Capture deterministic full-page screenshots of the visual case inventory.

    uv run python -m scripts.visual capture --provider fixture --out .propertyscope-visual/head
    uv run python -m scripts.visual capture --provider stack --case f4-site-reviews

``fixture`` starts the target checkout's own ``scripts.ui_fixture_server`` on a free loopback port,
so each revision renders its own frontend with its own fixtures. ``stack`` expects an offline stack
(``scripts/dev.py stack up --offline``) and reads it through the shared edge. Only the target origin
is reachable; every other request is aborted, except map styles, which receive a blank local style.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import re
import socket
import subprocess
import sys
import time
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.parse import urlsplit
from urllib.request import urlopen

from playwright.sync_api import Browser, FloatRect, Page, Route, sync_playwright

from scripts.visual.cases import CASES, VisualCase, select_cases, validate_cases
from scripts.visual.policy import (
    CHROMIUM_ARGS,
    FIXED_TIME,
    LOCALE,
    MAX_CAPTURE_HEIGHT,
    PROVIDERS,
    REVISIONS,
    TIMEZONE,
    VIEWPORT_HEIGHT,
    VIEWPORT_WIDTH,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = REPOSITORY_ROOT / ".propertyscope-visual" / "captures"
MASK_COLOUR = "#c9d8d1"
READY_TIMEOUT_MS = 20_000
SETTLE_TIMEOUT_MS = 15_000
STABLE_ATTEMPTS = 5
# A blank MapLibre style: the map frame, controls and feature markers still render, but no tiles
# are fetched from the internet, so captures never depend on a third-party tile server.
BLANK_MAP_STYLE = {
    "version": 8,
    "name": "visual-regression-blank",
    "sources": {},
    "layers": [
        {"id": "background", "type": "background", "paint": {"background-color": "#e6eae2"}}
    ],
}
# Served from the page's own origin by request interception, so strict ``style-src 'self'``
# policies still apply to everything the application itself does.
STILL_STYLESHEET = "/__visual-regression__/still.css"
STILL_CSS = (
    "*,*::before,*::after{animation:none!important;transition:none!important;"
    "scroll-behavior:auto!important;caret-color:transparent!important}"
)
BUSY_SCRIPT = """() => [...document.querySelectorAll(
  '[aria-busy="true"], .ps-skeleton, .ps-map__status[data-state="loading"]')]
  .every(element => {
    const box = element.getBoundingClientRect();
    return !box.width || !box.height || element.closest('[hidden]')
      || getComputedStyle(element).visibility === 'hidden';
  })"""
# Seed Math.random and crypto.randomUUID: client-generated request IDs are rendered in error states.
SEEDED_RANDOM = """(() => {
  let seed = 42;
  const next = () => (seed = (seed * 1664525 + 1013904223) >>> 0);
  Math.random = () => next() / 4294967296;
  if (globalThis.crypto && typeof crypto.randomUUID === 'function') {
    let uuid = 0;
    crypto.randomUUID = () => {
      uuid += 1;
      return `00000000-0000-4000-8000-${uuid.toString(16).padStart(12, '0')}`;
    };
  }
})();"""
# Offscreen WebGL surfaces can be partly blank when Chromium composites a full-page screenshot.
# Keep the real drawing buffer, then snapshot its pixels after readiness. This applies only inside
# the disposable capture context: production map settings and the 1000px viewport stay intact.
WEBGL_CAPTURE = """(() => {
  const canvases = new Set();
  const getContext = HTMLCanvasElement.prototype.getContext;
  HTMLCanvasElement.prototype.getContext = function(type, options) {
    const webgl = type === 'webgl' || type === 'webgl2' || type === 'experimental-webgl';
    const context = getContext.call(this, type,
      webgl ? {...options, preserveDrawingBuffer: true} : options);
    if (webgl && context) canvases.add(this);
    return context;
  };
  globalThis.__visualWebGLCanvases = canvases;
})();"""
FREEZE_WEBGL = """async () => {
  const canvases = [...(globalThis.__visualWebGLCanvases || [])].filter(c => c.isConnected);
  const snapshots = [];
  for (const canvas of canvases) {
    const image = new Image();
    image.src = canvas.toDataURL('image/png');
    await image.decode();
    image.className = canvas.className;
    image.style.cssText = canvas.style.cssText;
    image.width = canvas.width;
    image.height = canvas.height;
    image.setAttribute('aria-hidden', 'true');
    snapshots.push([canvas, image]);
  }
  // Keep all canvases rendering until every bitmap has decoded. Map controls and other DOM
  // overlays remain in place; only the already-rendered WebGL surface becomes a still image.
  for (const [canvas, image] of snapshots) canvas.replaceWith(image);
  return snapshots.length;
}"""


def _git_sha(path: Path) -> str | None:
    try:
        return subprocess.run(  # noqa: S603 - fixed git argv, no shell
            ("git", "-C", str(path), "rev-parse", "HEAD"),  # noqa: S607 - git is resolved from the developer PATH
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _ready(url: str) -> bool:
    try:
        with urlopen(url, timeout=0.5) as response:  # noqa: S310 - loopback capture server URL
            return bool(response.status == 200)
    except (OSError, URLError):
        return False


@contextlib.contextmanager
def fixture_host(target: Path, port: int) -> Iterator[str]:
    """Run the target revision's own fixture server and always stop it."""
    module = ("-m", "scripts.ui_fixture_server", "--port", str(port), "--scenario", "populated")
    command: tuple[str, ...]
    if target.resolve() == REPOSITORY_ROOT:
        command = (sys.executable, *module)
    else:
        # The target checkout has its own synced environment and production modules.
        command = ("uv", "run", "--directory", str(target), "--no-sync", "python", *module)
    base_url = f"http://127.0.0.1:{port}"
    child = subprocess.Popen(command, cwd=target)  # noqa: S603 - fixed uv/python argv, no shell
    try:
        deadline = time.monotonic() + 60
        while not _ready(f"{base_url}/__ui-fixture__/ready"):
            if child.poll() is not None:
                raise RuntimeError("the fixture server exited before it became ready")
            if time.monotonic() > deadline:
                raise RuntimeError(f"the fixture server did not become ready at {base_url}")
            time.sleep(0.2)
        yield base_url
    finally:
        child.terminate()
        try:
            child.wait(timeout=10)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait(timeout=10)


def _route_handler(origin: str, blocked: list[str]) -> Any:
    def handle(route: Route) -> None:
        url = urlsplit(route.request.url)
        same_origin = f"{url.scheme}://{url.netloc}" == origin
        if same_origin and url.path == STILL_STYLESHEET:
            route.fulfill(body=STILL_CSS, content_type="text/css")
        elif same_origin or url.scheme in {"data", "blob"}:
            route.continue_()
        elif url.hostname == "tiles.openfreemap.org" and url.path.startswith("/styles/"):
            route.fulfill(json=BLANK_MAP_STYLE)
        else:
            if len(blocked) < 20:
                blocked.append(f"{url.scheme}://{url.hostname}{url.path}"[:200])
            route.abort()

    return handle


def stable_screenshot(capture: Any, limit: int = STABLE_ATTEMPTS) -> tuple[bytes, int]:
    """Return a screenshot once two consecutive captures are byte-identical."""
    previous: bytes | None = None
    for attempt in range(1, limit + 1):
        image = bytes(capture())
        if image == previous:
            return image, attempt
        previous = image
    raise RuntimeError(f"the view did not render identically twice within {limit} captures")


def _perform_steps(page: Page, case: VisualCase) -> None:
    for step in case.steps:
        target = page.locator(step.selector).first
        if step.action == "wait":
            target.wait_for(state="visible", timeout=READY_TIMEOUT_MS)
        elif step.action == "click":
            target.click(timeout=READY_TIMEOUT_MS)
        elif step.action == "fill":
            target.fill(step.value, timeout=READY_TIMEOUT_MS)
        elif step.action == "press":
            target.press(step.value, timeout=READY_TIMEOUT_MS)
        elif step.action == "scroll":
            target.scroll_into_view_if_needed(timeout=READY_TIMEOUT_MS)


def capture_case(browser: Browser, case: VisualCase, base_url: str, output: Path) -> dict[str, Any]:
    """Capture one case in a fresh context and return its bounded manifest record."""
    started = time.monotonic()
    errors: list[str] = []
    blocked: list[str] = []
    record: dict[str, Any] = {
        "id": case.id,
        "section": case.section,
        "provider": case.provider,
        "path": case.path,
        "scenario": case.scenario,
        "state": case.state,
        "status": "captured",
    }
    origin = "{0.scheme}://{0.netloc}".format(urlsplit(base_url))
    context = browser.new_context(
        viewport={"width": VIEWPORT_WIDTH, "height": VIEWPORT_HEIGHT},
        device_scale_factor=1,
        color_scheme="light",
        locale=LOCALE,
        timezone_id=TIMEZONE,
        reduced_motion="reduce",
        service_workers="block",
    )
    context.route("**/*", _route_handler(origin, blocked))
    page = context.new_page()
    expected = [re.compile(pattern) for pattern in case.expected_errors]

    def console(message: Any) -> None:
        if message.type != "error":
            return
        text = str(message.text)
        if any(pattern.search(text) for pattern in expected):
            return
        if blocked and "net::ERR_FAILED" in text:
            return  # an external request this harness deliberately aborted
        errors.append(f"console: {text}"[:500])

    page.on("console", console)
    page.on("pageerror", lambda error: errors.append(f"page error: {error}"[:500]))
    page.clock.set_fixed_time(FIXED_TIME)
    page.add_init_script(SEEDED_RANDOM)
    page.add_init_script(WEBGL_CAPTURE)
    try:
        page.goto(case.url(base_url), wait_until="domcontentloaded", timeout=READY_TIMEOUT_MS)
        _perform_steps(page, case)
        page.locator(case.ready).first.wait_for(state="visible", timeout=READY_TIMEOUT_MS)
        with contextlib.suppress(Exception):
            page.wait_for_load_state("networkidle", timeout=SETTLE_TIMEOUT_MS)
        try:
            page.wait_for_function(BUSY_SCRIPT, timeout=SETTLE_TIMEOUT_MS)
        except Exception:
            errors.append("page still showed a loading indicator after 15 seconds")
        page.add_style_tag(url=f"{origin}{STILL_STYLESHEET}")
        page.evaluate(
            "async () => { await document.fonts.ready;"
            " await new Promise(requestAnimationFrame); await new Promise(requestAnimationFrame); }"
        )
        page.mouse.move(0, 0)
        frozen_canvases = page.evaluate(FREEZE_WEBGL)
        if frozen_canvases:
            record.setdefault("notes", []).append(
                f"snapshotted {frozen_canvases} rendered WebGL canvas(es) for full-page capture"
            )
        page_height = int(page.evaluate("document.documentElement.scrollHeight"))
        height = min(max(page_height, VIEWPORT_HEIGHT), MAX_CAPTURE_HEIGHT)
        if not case.full_page:
            height = VIEWPORT_HEIGHT
        clip: FloatRect = {"x": 0, "y": 0, "width": VIEWPORT_WIDTH, "height": height}
        image, attempts = stable_screenshot(
            lambda: page.screenshot(
                # The stylesheet above hides carets; Playwright's own caret style is inline.
                full_page=case.full_page,
                clip=clip,
                animations="disabled",
                caret="initial",
                mask=[page.locator(selector) for selector in case.mask],
                mask_color=MASK_COLOUR,
            )
        )
        (output / f"{case.id}.png").write_bytes(image)
        record.update(
            sha256=hashlib.sha256(image).hexdigest(),
            width=VIEWPORT_WIDTH,
            height=height,
            pageHeight=page_height,
            attempts=attempts,
        )
        if page_height > MAX_CAPTURE_HEIGHT:
            record.setdefault("notes", []).append(
                f"page is {page_height}px tall; only the first 6000px are compared"
            )
        if errors:
            record["status"] = "incomplete"
    except Exception as exc:
        record["status"] = "failed"
        errors.append(str(exc).splitlines()[0][:500] if str(exc) else type(exc).__name__)
        # Diagnostic only: the reporter never treats a failed capture as a comparable view.
        with contextlib.suppress(Exception):
            page.screenshot(path=str(output / f"{case.id}.failed.png"))
    finally:
        context.close()
    if case.mask:
        record.setdefault("notes", []).append(f"masked runtime values: {', '.join(case.mask)}")
    if blocked:
        record.setdefault("notes", []).append(f"blocked external requests: {', '.join(blocked)}")
    record["errors"] = errors[:10]
    record["durationMs"] = round((time.monotonic() - started) * 1000)
    return record


def capture_exit_code(records: Sequence[dict[str, Any]], revision: str) -> int:
    """A head view must capture cleanly; a baseline may lack views a change introduces."""
    if revision == "base":
        return 0 if any(record["status"] == "captured" for record in records) else 1
    return 0 if records and all(record["status"] == "captured" for record in records) else 1


def capture(
    *,
    provider: str,
    target: Path,
    output: Path,
    revision: str,
    base_url: str | None,
    case_ids: Sequence[str] = (),
    sections: Sequence[str] = (),
    channel: str | None = None,
) -> int:
    """Capture the selected cases for one provider and write ``capture-<provider>.json``."""
    validate_cases(CASES)
    requested_sha = os.environ.get("VISUAL_REVISION_SHA")
    if requested_sha and _git_sha(target) != requested_sha:
        raise RuntimeError("the capture checkout does not match the requested revision")
    selected = select_cases(provider=provider, ids=case_ids, sections=sections)
    if not selected:
        print(f"No {provider} cases selected; nothing to capture.", flush=True)
        return 0
    output.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    records: list[dict[str, Any]] = []
    with contextlib.ExitStack() as stack:
        if provider == "fixture":
            base_url = stack.enter_context(fixture_host(target, _free_port()))
        elif base_url is None:
            port = os.environ.get("PROPERTYSCOPE_SHARED_PORT") or "5100"
            base_url = f"http://127.0.0.1:{port}"
        playwright = stack.enter_context(sync_playwright())
        browser = playwright.chromium.launch(args=list(CHROMIUM_ARGS), channel=channel or None)
        stack.callback(browser.close)
        for case in selected:
            record = capture_case(browser, case, base_url, output)
            records.append(record)
            print(f"{case.id}: {record['status']} ({record['durationMs']} ms)", flush=True)
            for error in record["errors"]:
                print(f"    {error}", flush=True)
    manifest = {
        "schema": 1,
        "revision": revision,
        "provider": provider,
        "revisionSha": _git_sha(target),
        "harnessSha": _git_sha(REPOSITORY_ROOT),
        "viewport": {"width": VIEWPORT_WIDTH, "height": VIEWPORT_HEIGHT},
        "fixedTime": FIXED_TIME,
        "durationMs": round((time.monotonic() - started) * 1000),
        "cases": records,
    }
    (output / f"capture-{provider}.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return capture_exit_code(records, revision)


def add_arguments(parser: argparse.ArgumentParser) -> None:
    """Register capture options on a parser."""
    parser.add_argument("--provider", choices=PROVIDERS, required=True)
    parser.add_argument("--target", type=Path, default=REPOSITORY_ROOT, help="checkout to render")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--revision", choices=REVISIONS, default="head")
    parser.add_argument("--base-url", default=None, help="stack edge URL (default: port 5100)")
    parser.add_argument("--case", action="append", default=[], help="case ID (repeatable)")
    parser.add_argument("--section", action="append", default=[], help="section (repeatable)")
    parser.add_argument("--channel", default=None, help="browser channel, e.g. msedge (local)")


def run(arguments: argparse.Namespace) -> int:
    """Run a parsed capture command."""
    return capture(
        provider=arguments.provider,
        target=arguments.target,
        output=arguments.out,
        revision=arguments.revision,
        base_url=arguments.base_url,
        case_ids=[item for value in arguments.case for item in value.split(",")],
        sections=arguments.section,
        channel=arguments.channel,
    )
