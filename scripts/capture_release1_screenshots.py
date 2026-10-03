"""Capture verified Release 1 browser evidence from the running local stack.

Start the combined host AI tier and feature containers, then ingest each registered corpus.
Each question goes through its owning feature frontend/backend. Existing demonstration cases
are selected read-only; the command never creates, edits, publishes or deletes feature records.
Successful captures include an answer image, a sources/activity image and an allowlisted JSON
manifest. Failed or insufficiently verified scenarios do not overwrite existing evidence.
Visually inspect every image before using it in the report.

    uv run python scripts/capture_release1_screenshots.py --list
    uv run python scripts/capture_release1_screenshots.py --only feature-1
    uv run python scripts/capture_release1_screenshots.py --output Temp/release1-screens
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
import sys
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit
from uuid import UUID

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from playwright.sync_api import Locator, Page, sync_playwright
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from scripts.release1_capture_evidence import CaptureError, correlate_run, verified_evidence

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
OUTPUT = REPOSITORY_ROOT / "docs" / "reports" / "assets" / "release-1" / "screenshots"
VIEWPORT = {"width": 1440, "height": 1000}
FOCUS_WIDTH = 1100
MAX_FOCUS_HEIGHT = 6000
ANSWER_TIMEOUT_MS = 210_000
RUN_START_TIMEOUT_MS = 20_000
TURN = ".ps-ai-chat__turn"
FINISHED_TURN = f"{TURN}:has(.ps-ai-chat__answer), {TURN}:has(.ps-ai-chat__turn-error)"
STOP_RESPONSE = 'form.ps-ai-chat__composer button:has-text("Stop response")'


@dataclass(frozen=True)
class Feature:
    """Public route and evidence scope owned by one feature."""

    number: int
    route: str
    api: str
    key: str
    corpus: str
    expected_tool: str


FEATURES = {
    1: Feature(
        1,
        "data-platform",
        "data-platform",
        "student-1-propertyscope-data-platform",
        "operator-guidance",
        "data.releases.v1",
    ),
    2: Feature(
        2,
        "market-intelligence",
        "market-intelligence",
        "student-2-market-intelligence",
        "operator-guidance",
        "market.sales.summary.v1",
    ),
    3: Feature(
        3,
        "suburb-analytics",
        "suburb-analytics",
        "student-3-suburb-analytics",
        "suburb-analytics-guidance",
        "crime.methodology.v1",
    ),
    4: Feature(
        4,
        "due-diligence",
        "due-diligence",
        "student-4-due-diligence",
        "operator-guidance",
        "duediligence.evidence.summary.v1",
    ),
    5: Feature(
        5,
        "buyer-workspaces",
        "buyer-workspaces",
        "student-5-buyer-journey",
        "operator-guidance",
        "buyer.cases.inspect.v1",
    ),
}


@dataclass(frozen=True)
class Shot:
    """One explicit expected outcome, rather than a screenshot of any terminal turn."""

    name: str
    owner: str
    path: str
    question: str | None = None
    ready: str | None = None
    feature: int | None = None
    mode: str | None = None


_QUESTIONS = {
    1: (
        "Which datasets are published at the moment, and how many records does each have?",
        "Why can a property show no recorded sales even though it has sold before?",
        "What oven temperature should I use for a chocolate cake?",
    ),
    2: (
        "How many eligible sales and what is the median recorded price in this case?",
        "What does the minimum match tier exclude, and why might a case show few eligible sales?",
        "How do I reset my password?",
    ),
    3: (
        "What are the recorded zero versus missing evidence rules and rate calculation "
        "for this feature?",
        "How does Feature 3 distinguish recorded zero from missing evidence?",
        "What oven temperature should I use for a chocolate cake?",
    ),
    4: (
        "What planning, environmental, strata and building evidence is recorded for this review?",
        "What do confirmed, no_intersection, partial and unavailable evidence states "
        "mean in a site review?",
        "How do I reset my password?",
    ),
    5: (
        "What budget, target suburbs and shortlisted properties are recorded in this buyer case?",
        "What do journey stages mean, and how should I manage my shortlist?",
        "What oven temperature should I use for a chocolate cake?",
    ),
}

SHOTS = (
    Shot(
        "shared-knowledge-sources",
        "Shared",
        "/operations/ai-mode/knowledge/",
        ready="#corpus-list .corpus-card",
    ),
    Shot("shared-activity-history", "Shared", "/operations/ai-mode/", ready="#run-list"),
    *(
        Shot(
            f"feature-{number}-{mode}",
            f"Student {number}",
            f"/features/{FEATURES[number].route}/#assistant",
            question,
            feature=number,
            mode=mode,
        )
        for number, questions in _QUESTIONS.items()
        for mode, question in zip(("mcp", "rag", "insufficient"), questions, strict=True)
    ),
)


def _get(page: Page, base_url: str, path: str) -> dict[str, Any]:
    """Read a public projection without attaching host secrets or saving raw payloads."""
    response = page.request.get(base_url.rstrip("/") + path, timeout=20_000)
    if response.status != 200:
        raise CaptureError(f"public read {path.split('?')[0]} returned HTTP {response.status}")
    value = response.json()
    if not isinstance(value, dict):
        raise CaptureError("public endpoint returned a non-object")
    return value


def _uuid(value: object) -> str:
    try:
        return str(UUID(str(value)))
    except ValueError as error:
        raise CaptureError("expected a valid public resource/run ID") from error


def _resource(items: object, identifier: str) -> dict[str, Any]:
    if not isinstance(items, list):
        raise CaptureError("resource list has no items")
    selected = next(
        (item for item in items if isinstance(item, dict) and item.get("id") == identifier), None
    )
    if selected is None:
        raise CaptureError(
            "selected demonstration resource is absent; pass an existing resource ID explicitly"
        )
    return selected


def setup_feature(
    page: Page, shot: Shot, base_url: str, resources: Mapping[int, str]
) -> dict[str, str]:
    """Bind the visible assistant to an existing case/review or an exact published locality."""
    assert shot.feature is not None
    feature = FEATURES[shot.feature]
    root = f"/api/{feature.api}/v1"
    context: dict[str, str] = {}
    path = shot.path
    if feature.number == 2:
        listing = _get(page, base_url, root + "/market-cases")
        identifier = _uuid(resources.get(2, "60000000-0000-4000-8000-000000000001"))
        _resource(listing.get("items"), identifier)
        context["market_case_id"] = identifier
    elif feature.number == 4:
        identifier = _uuid(resources.get(4, "d4000000-0000-0000-0000-000000000001"))
        _get(page, base_url, root + f"/site-reviews/{identifier}")
        context["site_review_id"] = identifier
        path = f"/features/{feature.route}/#site-reviews/{identifier}"
    elif feature.number == 5:
        identifier = _uuid(resources.get(5, "b5000000-0000-4000-8000-000000000001"))
        _get(page, base_url, root + f"/buyer-cases/{identifier}")
        context["buyer_case_id"] = identifier
        path = f"/features/{feature.route}/#buyer-cases/{identifier}"
    elif feature.number == 3:
        selected_locality = resources.get(3, "PARRAMATTA")
        listing = _get(page, base_url, root + "/published/suburbs?q=" + quote(selected_locality))
        items = listing.get("items")
        localities = (
            [
                item if isinstance(item, str) else item.get("locality")
                for item in items
                if isinstance(item, (str, dict))
            ]
            if isinstance(items, list)
            else []
        )
        locality = selected_locality
        if not locality or locality not in localities:
            raise CaptureError("an exact published Feature 3 locality is required")
        _get(page, base_url, root + "/published/context?locality=" + quote(locality))
        context.update(route="suburbs/detail", locality=locality)
    response = page.goto(base_url.rstrip("/") + path, wait_until="domcontentloaded")
    if response is None or response.status != 200:
        raise CaptureError("feature frontend did not load successfully")
    if feature.number == 2:
        selected = page.locator(f'#case-list [data-case-id="{context["market_case_id"]}"]')
        selected.wait_for(state="visible")
        selected.click()
        page.locator("#case-detail[aria-busy='false']").wait_for(state="visible")
    if feature.number == 3:
        page.locator("#assistant-root details.ps-ai-chat__settings").evaluate(
            "node => { node.open = true; }"
        )
        page.locator("#assistant-root .ps-ai-chat__context-editor select").select_option("locality")
        page.locator("#assistant-root input[name='locality']").fill(context["locality"])
    page.locator("textarea[name='message']").first.wait_for(state="visible")
    return context


def _ask(page: Page, question: str) -> str:
    composer = page.locator("textarea[name='message']").first
    composer.fill(question)
    composer.press("Enter")
    stop = page.locator(STOP_RESPONSE).first
    try:
        stop.wait_for(state="visible", timeout=RUN_START_TIMEOUT_MS)
    except PlaywrightTimeoutError:
        pass  # Fast rejection/completion is inspected below; it is never accepted implicitly.
    else:
        stop.wait_for(state="hidden", timeout=ANSWER_TIMEOUT_MS)
    turn = page.locator(FINISHED_TURN).last
    turn.wait_for(state="visible", timeout=RUN_START_TIMEOUT_MS)
    if turn.locator(".ps-ai-chat__turn-error").count():
        raise CaptureError("assistant turn rendered an error")
    identifier = _uuid(turn.get_attribute("data-run-id"))
    turn.evaluate("node => node.scrollIntoView({block: 'start'})")
    return identifier


def _sources(page: Page, shot: Shot, evidence: Mapping[str, Any]) -> Locator | None:
    page.locator(TURN).last.locator("[data-action='inspect-evidence']").click()
    panel = page.locator(".ps-ai-chat__inspection:not([hidden])").first
    panel.wait_for(state="visible")
    selector = (
        ".ps-ai-chat__source--tool"
        if shot.mode == "mcp"
        else ".ps-ai-chat__source:not(.ps-ai-chat__source--tool)"
    )
    if shot.mode == "mcp":
        expected = FEATURES[shot.feature].expected_tool if shot.feature else None
        matched = next(
            (
                item
                for item in evidence.get("tools", [])
                if item["tool_name"] == expected and item["transport"] == "mcp"
            ),
            None,
        )
        if matched:
            selector = f'details[data-disclosure="tool:{matched["call_id"]}"]'
    elif shot.mode == "rag" and evidence.get("citations"):
        citation = max(evidence["citations"], key=lambda item: item.get("score", -1))
        selector = f'details[data-disclosure="source:{citation["citation_id"]}"]'
    card = panel.locator(selector).first
    if card.count():
        card.evaluate("node => { node.open = true; node.scrollIntoView({block: 'start'}); }")
        return card
    elif shot.mode == "insufficient":
        panel.locator(".ps-ai-chat__qualifications").evaluate("node => { node.open = true; }")
        panel.evaluate("node => node.scrollIntoView({block: 'start'})")
    else:
        raise CaptureError("verified evidence is absent from the visible sources panel")
    return None


def _focused_image(page: Page, target: Locator, destination: Path) -> dict[str, Any]:
    """Photograph a complete rendered element at a readable responsive browser width.

    A taller real viewport removes clipping from the application's scrolling panels. The
    browser lays out every pixel; this never rewrites content/styles or reconstructs an image.
    Full-workspace screenshots keep their separate, consistent 1440x1000 viewport.
    """
    page.set_viewport_size({"width": FOCUS_WIDTH, "height": VIEWPORT["height"]})
    target.wait_for(state="visible")
    box = target.bounding_box()
    if box is None or box["width"] < 300 or box["height"] < 80:
        raise CaptureError("focused evidence element is absent or too small to be readable")
    height = max(VIEWPORT["height"], math.ceil(box["height"]) + 240)
    if height > MAX_FOCUS_HEIGHT:
        raise CaptureError("focused evidence is too long for a readable report image")
    viewport = {"width": FOCUS_WIDTH, "height": height}
    page.set_viewport_size(viewport)
    target.evaluate("node => node.scrollIntoView({block: 'center', inline: 'nearest'})")
    box = target.bounding_box()
    if (
        box is None
        or box["x"] < 0
        or box["y"] < 0
        or box["x"] + box["width"] > viewport["width"]
        or box["y"] + box["height"] > viewport["height"]
    ):
        raise CaptureError("focused evidence would be clipped by its browser viewport")
    target.screenshot(path=str(destination), animations="disabled")
    return {
        "capture": "element",
        "viewport": viewport,
        "element_size": {"width": round(box["width"]), "height": round(box["height"])},
    }


def _software() -> tuple[str, bool]:
    sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPOSITORY_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    dirty = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=no"],
        cwd=REPOSITORY_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return sha, bool(dirty)


def _shared(page: Page, shot: Shot, base_url: str, recent_run: str | None) -> dict[str, Any]:
    if shot.name == "shared-knowledge-sources":
        listing = _get(page, base_url, "/api/v1/operations/knowledge")
        corpora = listing.get("corpora", [])
        ready = [
            item for item in corpora if isinstance(item, dict) and item.get("status") == "ready"
        ]
        if {item.get("feature_key") for item in ready} != {
            feature.key for feature in FEATURES.values()
        }:
            raise CaptureError(
                "all five registered corpora must be ready for the shared evidence image"
            )
        page.goto(base_url.rstrip("/") + shot.path, wait_until="domcontentloaded")
        page.locator("#document-list details").first.wait_for(state="visible")
        page.locator("#document-list details").first.evaluate("node => { node.open = true; }")
        return {
            "corpora": [
                {
                    "feature_key": item["feature_key"],
                    "corpus_id": item["corpus_id"],
                    "corpus_version": item["version"]["corpus_version"],
                    "document_count": item["version"]["document_count"],
                }
                for item in ready
            ]
        }
    if recent_run is None:
        listing = _get(page, base_url, "/api/v1/agent-runs?limit=100")
        for item in listing.get("items", []):
            if item.get("status") != "succeeded" or item.get("feature_key") != FEATURES[1].key:
                continue
            candidate = _get(
                page, base_url, f"/api/v1/operations/agent-runs/{_uuid(item.get('id'))}"
            )
            final = candidate.get("final_result") or {}
            if final.get("confidence") in {"high", "moderate", "low"} and final.get("citations"):
                recent_run = item["id"]
                break
    if recent_run is None:
        raise CaptureError("no successful Feature 1 run is available for shared activity evidence")
    detail = _get(page, base_url, f"/api/v1/operations/agent-runs/{_uuid(recent_run)}")
    if detail.get("run", {}).get("status") != "succeeded":
        raise CaptureError("shared activity run has not succeeded")
    page.goto(
        base_url.rstrip("/") + shot.path + "?run=" + recent_run, wait_until="domcontentloaded"
    )
    page.locator("#run-detail .ps-ai-chat__answer").first.wait_for(state="visible")
    return {
        "run_id": recent_run,
        "run_created_at": detail["run"]["created_at"],
        "status": "succeeded",
        "feature_key": detail["run"]["feature_key"],
    }


def capture(
    shots: Iterable[Shot],
    *,
    base_url: str,
    output: Path,
    resources: Mapping[int, str] | None = None,
) -> list[str]:
    """Write evidence only after verifying the current UI, backend and durable run agree."""
    parsed = urlsplit(base_url)
    if (
        parsed.scheme not in ("http", "https")
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise CaptureError(
            "base URL must be an HTTP origin without credentials or query parameters"
        )
    output.mkdir(parents=True, exist_ok=True)
    problems: list[str] = []
    sha, dirty = _software()
    recent_run = None
    # Shared images use the runs created here where possible, rather than an arbitrary old run.
    ordered = sorted(shots, key=lambda shot: shot.feature is None)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            for shot in ordered:
                context = browser.new_context(
                    viewport=VIEWPORT,
                    color_scheme="light",
                    locale="en-AU",
                    timezone_id="Australia/Sydney",
                    reduced_motion="reduce",
                )  # type: ignore[arg-type]
                page = context.new_page()
                page_errors: list[str] = []
                page.on(
                    "pageerror",
                    lambda _error, errors=page_errors: errors.append("uncaught browser exception"),
                )
                staging = output / f".{shot.name}.png"
                sources_staging = output / f".{shot.name}.sources.png"
                answer_staging = output / f".{shot.name}.answer.png"
                citation_staging = output / f".{shot.name}.citation.png"
                try:
                    metadata: dict[str, Any]
                    if shot.feature is not None:
                        feature = FEATURES[shot.feature]
                        capabilities = _get(page, base_url, "/api/ai-mode/capabilities")
                        expected_context = setup_feature(page, shot, base_url, resources or {})
                        assert shot.question is not None and shot.mode is not None
                        question = shot.question.format(**expected_context)
                        turns = f"/api/{feature.api}/v1/assistant/turns"
                        with page.expect_response(
                            lambda response, route=turns: (
                                urlsplit(response.url).path == route
                                and response.request.method == "POST"
                            ),
                            timeout=RUN_START_TIMEOUT_MS,
                        ) as started:
                            run_id = _ask(page, question)
                        response = started.value
                        start_payload = response.json()
                        start_run = start_payload.get("run", start_payload)
                        if response.status not in (200, 201, 202) or start_run.get("id") != run_id:
                            raise CaptureError(
                                "visible turn does not match the owning backend start response"
                            )
                        posted = response.request.post_data_json
                        if not isinstance(posted, dict) or any(
                            posted.get("context", {}).get(key) != value
                            for key, value in expected_context.items()
                        ):
                            raise CaptureError(
                                "owning backend did not receive the selected resource context"
                            )
                        owning_detail = _get(page, base_url, turns + "/" + run_id)
                        shared_detail = _get(page, base_url, "/api/v1/agent-runs/" + run_id)
                        detail = correlate_run(owning_detail, shared_detail)
                        metadata = verified_evidence(
                            detail,
                            feature_key=feature.key,
                            corpus_id=feature.corpus,
                            mode=shot.mode,
                            expected_tool=feature.expected_tool,
                            run_id=run_id,
                            capabilities=capabilities,
                        )
                        metadata["context"] = expected_context
                        metadata["backend_route"] = turns
                        if feature.number == 1 and metadata["confidence"] != "insufficient":
                            recent_run = run_id
                        if (
                            page.locator(TURN)
                            .last.locator(".ps-ai-chat__answer")
                            .inner_text()
                            .strip()
                            == ""
                        ):
                            raise CaptureError("visible answer is empty")
                    else:
                        metadata = _shared(page, shot, base_url, recent_run)
                    if page_errors:
                        raise CaptureError("uncaught browser exception")
                    page.screenshot(path=str(staging), animations="disabled")
                    artifacts = [
                        (f"{shot.name}.png", staging, {"capture": "viewport", "viewport": VIEWPORT})
                    ]
                    if shot.feature is not None:
                        _sources(page, shot, metadata)
                        page.screenshot(path=str(sources_staging), animations="disabled")
                        artifacts.append(
                            (
                                f"{shot.name}.sources.png",
                                sources_staging,
                                {"capture": "viewport", "viewport": VIEWPORT},
                            )
                        )
                        page.locator(
                            ".ps-ai-chat__inspection:not([hidden]) "
                            ".ps-ai-chat__inspection-head button"
                        ).first.click()
                        answer = page.locator(TURN).last.locator(".ps-ai-chat__message--assistant")
                        focused = _focused_image(page, answer, answer_staging)
                        artifacts.append((f"{shot.name}.answer.png", answer_staging, focused))
                        if shot.mode == "rag":
                            card = _sources(page, shot, metadata)
                            if card is None:
                                raise CaptureError(
                                    "supported RAG source card is unavailable for its focused image"
                                )
                            focused = _focused_image(page, card, citation_staging)
                            artifacts.append(
                                (f"{shot.name}.citation.png", citation_staging, focused)
                            )
                    if page_errors:
                        raise CaptureError("uncaught browser exception")
                    manifest = {
                        "schema_version": "1.0",
                        "shot": shot.name,
                        "captured_at": datetime.now(UTC).isoformat(),
                        "software_sha": sha,
                        "tracked_worktree_dirty": dirty,
                        "origin": base_url.rstrip("/"),
                        "viewport": VIEWPORT,
                        "decision_provider": "live-configured-provider"
                        if shot.feature
                        else "public-operations-projection",
                        "mode": shot.mode or "shared",
                        **metadata,
                        "images": [
                            {
                                "file": name,
                                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                                **image_metadata,
                            }
                            for name, path, image_metadata in artifacts
                        ],
                    }
                    for name, path, _image_metadata in artifacts:
                        path.replace(output / name)
                    (output / f"{shot.name}.json").write_text(
                        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
                    )
                    print(f"Verified and captured {shot.name}: {output / artifacts[0][0]}")
                except (CaptureError, PlaywrightTimeoutError) as error:
                    problems.append(f"{shot.name}: {error}")
                finally:
                    staging.unlink(missing_ok=True)
                    sources_staging.unlink(missing_ok=True)
                    answer_staging.unlink(missing_ok=True)
                    citation_staging.unlink(missing_ok=True)
                    context.close()
        finally:
            browser.close()
    return problems


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--base-url", default="http://localhost:5100", help="shared edge origin")
    parser.add_argument("--only", action="append", default=[], help="shot name prefix, repeatable")
    parser.add_argument("--list", action="store_true", help="print supported capture scenarios")
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument(
        "--feature-2-case", help="existing market case UUID (default: demonstration case)"
    )
    parser.add_argument(
        "--feature-3-locality",
        help="exact existing published locality (default: PARRAMATTA)",
    )
    parser.add_argument(
        "--feature-4-review", help="existing site review UUID (default: demonstration review)"
    )
    parser.add_argument(
        "--feature-5-case", help="existing buyer case UUID (default: demonstration case)"
    )
    args = parser.parse_args(list(argv) if argv is not None else None)
    selected = [
        shot
        for shot in SHOTS
        if not args.only or any(shot.name.startswith(prefix) for prefix in args.only)
    ]
    if not selected:
        parser.error("--only did not match a capture scenario")
    if args.list:
        for shot in selected:
            print(f"{shot.name:<28} {shot.owner:<10} ready: {shot.mode or 'shared'}")
        return 0
    resources = {
        number: value
        for number, value in (
            (2, args.feature_2_case),
            (3, args.feature_3_locality),
            (4, args.feature_4_review),
            (5, args.feature_5_case),
        )
        if value
    }
    problems = capture(selected, base_url=args.base_url, output=args.output, resources=resources)
    for problem in problems:
        print(f"Capture failed: {problem}", file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
