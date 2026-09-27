"""Capture the Release 1 report screenshots from the running application.

This drives the real stack (feature containers plus host AI-mode, MCP and RAG), so it needs
``uv run scripts/dev.py stack up --ai-runtime host`` with the corpora ingested and a model key.
Each assistant screenshot asks one question through the feature's own frontend and waits for the
answer, so every feature is captured the same way at the same size.

    uv run python scripts/capture_release1_screenshots.py --list
    uv run python scripts/capture_release1_screenshots.py                  # every ready shot
    uv run python scripts/capture_release1_screenshots.py --only feature-3 # one feature

Look at every image before committing it. A screenshot of an error, an empty page or an answer that
does not show what its caption claims is worse than a pending placeholder.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
OUTPUT = REPOSITORY_ROOT / "docs" / "reports" / "assets" / "release-1" / "screenshots"
VIEWPORT = {"width": 1440, "height": 1000}
ANSWER_TIMEOUT_MS = 180_000
TURN = ".ps-ai-chat__turn"
FINISHED_TURN = f"{TURN}:has(.ps-ai-chat__answer), {TURN}:has(.ps-ai-chat__turn-error)"


@dataclass(frozen=True)
class Shot:
    """One report screenshot: a page to open and, for assistant shots, a question to ask."""

    name: str
    owner: str
    path: str
    question: str | None = None
    ready: str | None = None
    # Why the shot cannot be taken yet. Pending shots are skipped unless --include-pending.
    pending: str | None = None


# The three questions per feature show what the rubric asks for: a structured MCP tool result, a
# grounded answer with citations and confidence, and an insufficient-context answer.
# TODO(Students 2-5): once your feature uses the shared assistant and has a registered corpus
# (docs/release-1/adopt-mcp-and-rag.md), write questions your tools and corpus can answer, delete
# the `pending` value, capture with --only feature-N and check the images.
_FEATURE_2_PENDING = "Feature 2 renders answer text only; adopt the shared assistant and a corpus"
_FEATURE_3_PENDING = "Feature 3 has the shared assistant but no registered corpus yet"
_FEATURE_4_PENDING = "Feature 4 renders answer text only; adopt the shared assistant and a corpus"
_FEATURE_5_PENDING = "Feature 5 needs /assistant/turns routes, the shared assistant and a corpus"

SHOTS: tuple[Shot, ...] = (
    Shot(
        "shared-knowledge-sources",
        "Shared",
        "/operations/ai-mode/knowledge/",
        ready="h1",
    ),
    Shot("shared-activity-history", "Shared", "/operations/ai-mode/", ready="h1"),
    Shot(
        "feature-1-mcp",
        "Student 1",
        "/features/data-platform/#assistant",
        question="Which datasets are published at the moment, and how many records does each have?",
    ),
    Shot(
        "feature-1-rag",
        "Student 1",
        "/features/data-platform/#assistant",
        question="Why can a property show no recorded sales even though it has sold before?",
    ),
    Shot(
        "feature-1-insufficient",
        "Student 1",
        "/features/data-platform/#assistant",
        question="What oven temperature should I use for a chocolate cake?",
    ),
    *(
        Shot(f"feature-{number}-{kind}", f"Student {number}", path, pending=reason)
        for number, path, reason in (
            (2, "/features/market-intelligence/#assistant", _FEATURE_2_PENDING),
            (3, "/features/suburb-analytics/#assistant", _FEATURE_3_PENDING),
            (4, "/features/due-diligence/#assistant", _FEATURE_4_PENDING),
            (5, "/features/buyer-workspaces/#assistant", _FEATURE_5_PENDING),
        )
        for kind in ("mcp", "rag", "insufficient")
    ),
)


def _ask(page: Page, question: str) -> None:
    composer = page.locator("textarea[name='message']").first
    composer.wait_for(state="visible")
    finished_before = page.locator(FINISHED_TURN).count()
    composer.fill(question)
    composer.press("Enter")
    page.wait_for_function(
        "([selector, before]) => document.querySelectorAll(selector).length > before",
        arg=[FINISHED_TURN, finished_before],
        timeout=ANSWER_TIMEOUT_MS,
    )
    page.locator(TURN).last.evaluate("turn => turn.scrollIntoView({block: 'start'})")


def capture(shots: Iterable[Shot], *, base_url: str, output: Path) -> list[str]:
    """Capture each shot and return a list of problems observed in the browser."""
    output.mkdir(parents=True, exist_ok=True)
    problems: list[str] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            for shot in shots:
                context = browser.new_context(
                    viewport=VIEWPORT,  # type: ignore[arg-type]
                    color_scheme="light",
                    locale="en-AU",
                    timezone_id="Australia/Sydney",
                    reduced_motion="reduce",
                )
                page = context.new_page()
                page.on(
                    "pageerror", lambda error, name=shot.name: problems.append(f"{name}: {error}")
                )
                try:
                    page.goto(base_url.rstrip("/") + shot.path, wait_until="networkidle")
                    if shot.ready:
                        page.locator(shot.ready).first.wait_for(state="visible")
                    if shot.question:
                        _ask(page, shot.question)
                    page.wait_for_timeout(600)
                    target = output / f"{shot.name}.png"
                    page.screenshot(path=str(target))
                    print(f"Captured {target.relative_to(REPOSITORY_ROOT)}")
                finally:
                    context.close()
        finally:
            browser.close()
    return problems


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--base-url", default="http://localhost:5100", help="shared edge URL")
    parser.add_argument("--only", action="append", default=[], help="name prefix, repeatable")
    parser.add_argument("--include-pending", action="store_true")
    parser.add_argument("--list", action="store_true", help="print the shot list and exit")
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args(list(argv) if argv is not None else None)

    selected = [
        shot
        for shot in SHOTS
        if not args.only or any(shot.name.startswith(prefix) for prefix in args.only)
    ]
    if args.list:
        for shot in selected:
            state = f"pending: {shot.pending}" if shot.pending else "ready"
            print(f"{shot.name:<28} {shot.owner:<10} {state}")
        return 0
    runnable = [shot for shot in selected if args.include_pending or not shot.pending]
    for shot in selected:
        if shot not in runnable:
            print(f"Skipped {shot.name}: {shot.pending}")
    problems = capture(runnable, base_url=args.base_url, output=args.output)
    for problem in problems:
        print(f"Page error: {problem}", file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
