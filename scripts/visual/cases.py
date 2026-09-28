"""The visual case inventory: every captured view, its data provider and readiness contract.

``fixture`` cases render the production Shared and Feature 1 frontends against the deterministic
``ui serve`` fixture host (no Docker, no database). ``stack`` cases render Features 2-5 through the
shared edge of an offline Compose stack whose databases hold each feature's own seeded baseline.

Add a case with a stable lowercase ID (``shared-``/``f1-`` ... ``f5-`` prefixes choose the gallery
section), a path, a plain-language state and a selector that is visible only when the intended
content has rendered. Interactions are limited to navigation, opening dialogs and typing; never add
a step that saves, publishes or deletes.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Literal

from scripts.visual.policy import CASE_ID, MAX_VIEWS, PROVIDERS, section_for

Provider = Literal["fixture", "stack"]
StepAction = Literal["click", "fill", "press", "wait", "scroll"]

# Browsers log every failed fetch. Error and partial scenarios expect them.
FAILED_FETCH = r"^Failed to load resource: the server responded with a status of (4|5)\d\d"
# Data status shows real browser-measured request latency, which differs on every run.
MEASURED_LATENCY = ".health-row__latency"


@dataclass(frozen=True)
class Step:
    """One bounded, non-mutating interaction performed before the capture."""

    action: StepAction
    selector: str
    value: str = ""


@dataclass(frozen=True)
class VisualCase:
    """One captured view."""

    id: str
    provider: Provider
    path: str
    state: str
    ready: str = "main h1"
    scenario: str = "populated"
    steps: tuple[Step, ...] = ()
    # Regular expressions for console errors this state is expected to log.
    expected_errors: tuple[str, ...] = ()
    # Elements painted over with a solid block: only genuinely measured runtime values, such as
    # response times, belong here. Never mask content a change could legitimately alter.
    mask: tuple[str, ...] = ()
    full_page: bool = True

    @property
    def section(self) -> str:
        return section_for(self.id)

    def url(self, base_url: str) -> str:
        """Return the absolute URL; fixture cases select their scenario through the query."""
        path = self.path
        if self.provider == "fixture":
            prefix, hash_mark, fragment = path.partition("#")
            separator = "&" if "?" in prefix else "?"
            path = f"{prefix}{separator}scenario={self.scenario}{hash_mark}{fragment}"
        return base_url.rstrip("/") + path


def _fixture(
    case_id: str,
    path: str,
    state: str,
    ready: str = "main h1",
    *,
    scenario: str = "populated",
    steps: tuple[Step, ...] = (),
    expected_errors: tuple[str, ...] = (),
    mask: tuple[str, ...] = (),
) -> VisualCase:
    return VisualCase(
        case_id,
        "fixture",
        path,
        state,
        ready,
        scenario=scenario,
        steps=steps,
        expected_errors=expected_errors,
        mask=mask,
    )


def _stack(
    case_id: str,
    path: str,
    state: str,
    ready: str = "main h1",
    *,
    steps: tuple[Step, ...] = (),
) -> VisualCase:
    return VisualCase(case_id, "stack", path, state, ready, steps=steps)


F1 = "/features/data-platform/"
F1_PROPERTY = "11111111-1111-4111-8111-111111111111"
F1_RUN = "30000000-0000-0000-0000-000000000001"
F1_RELEASE = "60000000-0000-0000-0000-000000000001"
F1_JOB = "20000000-0000-0000-0000-000000000001"
F1_SOURCE = "10000000-0000-0000-0000-000000000001"
F2 = "/features/market-intelligence/"
F3 = "/features/suburb-analytics/"
F4 = "/features/due-diligence/"
F4_REVIEW = "d4000000-0000-0000-0000-000000000001"
F5 = "/features/buyer-workspaces/"
F5_CASE = "b5000000-0000-4000-8000-000000000010"

CASES: tuple[VisualCase, ...] = (
    # Shared shell and home (fixture host).
    _fixture("shared-home", "/#home", "populated home", "#feature-area-list [data-feature-id]"),
    _fixture("shared-research-areas", "/#features", "all five research areas"),
    _fixture(
        "shared-data-status",
        "/#system-status",
        "every service healthy; measured response times masked",
        mask=(MEASURED_LATENCY,),
    ),
    _fixture("shared-sources-history", "/#evidence", "published datasets and AI review history"),
    _fixture("shared-assistant", "/#assistant", "assistant start screen"),
    _fixture("shared-roadmap", "/#release-roadmap", "release roadmap"),
    _fixture("shared-activity-history", "/operations/ai-mode/", "AI activity history", "h1"),
    _fixture(
        "shared-home-empty",
        "/#home",
        "empty scenario: no published data",
        scenario="empty",
    ),
    _fixture(
        "shared-data-status-error",
        "/#system-status",
        "error scenario: services unavailable",
        scenario="error",
        expected_errors=(FAILED_FETCH,),
        mask=(MEASURED_LATENCY,),
    ),
    # Feature 1 property discovery and data operations (fixture host).
    _fixture("f1-property-search", f"{F1}#properties", "search prompt"),
    _fixture(
        "f1-property-results",
        f"{F1}#properties?q=11%20Example%20Street",
        "one matching property",
        ".result-card",
    ),
    _fixture("f1-property-detail", f"{F1}#properties/{F1_PROPERTY}", "property record"),
    _fixture("f1-assistant", f"{F1}#assistant", "feature assistant start screen"),
    _fixture(
        "f1-overview", f"{F1}#overview", "data overview", '[aria-label="Data readiness summary"]'
    ),
    _fixture("f1-jobs", f"{F1}#jobs", "data update catalogue"),
    _fixture("f1-job-detail", f"{F1}#jobs/{F1_JOB}", "one data update definition"),
    _fixture("f1-runs", f"{F1}#runs", "update history"),
    _fixture("f1-run-detail", f"{F1}#runs/{F1_RUN}", "completed update"),
    _fixture("f1-releases", f"{F1}#releases", "published data versions"),
    _fixture("f1-release-detail", f"{F1}#releases/{F1_RELEASE}", "accepted release"),
    _fixture("f1-sources", f"{F1}#sources", "registered data sources"),
    _fixture("f1-source-detail", f"{F1}#sources/{F1_SOURCE}", "one data source"),
    _fixture("f1-quality", f"{F1}#quality", "data checks"),
    _fixture("f1-artifacts", f"{F1}#artifacts", "files and history"),
    _fixture("f1-coverage", f"{F1}#coverage", "published coverage"),
    _fixture(
        "f1-property-results-empty",
        f"{F1}#properties?q=11%20Example%20Street",
        "empty scenario: no matching property",
        scenario="empty",
    ),
    _fixture(
        "f1-overview-error",
        f"{F1}#overview",
        "error scenario: data service unavailable",
        "button:has-text('Try again')",
        scenario="error",
        expected_errors=(FAILED_FETCH,),
    ),
    _fixture(
        "f1-releases-long-content",
        f"{F1}#releases",
        "long-content scenario: verbose names wrap",
        scenario="long-content",
    ),
    _fixture("f1-runs-large", f"{F1}#runs", "large scenario: eighty rows", scenario="large"),
    # Shared knowledge sources are served by host AI-mode, so they need the stack.
    _stack(
        "shared-knowledge-sources",
        "/operations/ai-mode/knowledge/",
        "knowledge sources with no ingested corpus",
        "#knowledge-heading",
    ),
    # Feature 2 sales and market cases (offline stack, seeded baseline).
    _stack(
        "f2-market-cases",
        F2,
        "seeded cases with the first case selected",
        "#case-detail:not([hidden]) #case-title",
    ),
    _stack(
        "f2-new-case-dialog",
        F2,
        "new market case dialog",
        "#case-dialog[open]",
        steps=(
            Step("wait", "#case-list button, #case-list a, #case-list li"),
            Step("click", "#new-case"),
        ),
    ),
    # Feature 3 suburb, crime and liveability analytics.
    _stack("f3-explore", f"{F3}#explore", "overview, search and map", '[data-view="explore"]'),
    _stack("f3-trends", f"{F3}#trends", "crime trend comparison", '[data-view="trends"]'),
    _stack("f3-published", f"{F3}#published", "published evidence", '[data-view="published"]'),
    _stack("f3-comparisons", f"{F3}#comparisons", "saved comparisons", '[data-view="comparisons"]'),
    _stack("f3-assistant", f"{F3}#assistant", "trend assistant", '[data-view="assistant"]'),
    # Feature 4 site, planning and building due diligence.
    _stack("f4-site-reviews", f"{F4}#site-reviews", "seeded site reviews"),
    _stack(
        "f4-review-detail",
        f"{F4}#site-reviews/{F4_REVIEW}",
        "one review with evidence",
    ),
    _stack(
        "f4-new-review-dialog",
        f"{F4}#site-reviews",
        "new site review dialog",
        "#review-dialog[open]",
        steps=(Step("click", "button:has-text('New site review')"),),
    ),
    # Feature 5 buyer journey workspace.
    _stack("f5-buyer-cases", f"{F5}#buyer-cases", "seeded buyer cases"),
    _stack("f5-case-detail", f"{F5}#buyer-cases/{F5_CASE}", "one buyer case"),
)


def validate_cases(cases: Sequence[VisualCase] = CASES) -> None:
    """Reject duplicate, unbounded or mis-sectioned cases before a browser starts."""
    if len(cases) > MAX_VIEWS:
        raise ValueError(f"at most {MAX_VIEWS} visual cases are supported")
    seen: set[str] = set()
    for case in cases:
        if not CASE_ID.fullmatch(case.id):
            raise ValueError(f"invalid visual case id: {case.id!r}")
        if case.id in seen:
            raise ValueError(f"duplicate visual case id: {case.id}")
        if case.provider not in PROVIDERS:
            raise ValueError(f"{case.id} uses unknown provider {case.provider!r}")
        if not case.path.startswith("/"):
            raise ValueError(f"{case.id} path must be absolute")
        seen.add(case.id)


def select_cases(
    *,
    provider: str | None = None,
    ids: Iterable[str] = (),
    sections: Iterable[str] = (),
    cases: Sequence[VisualCase] = CASES,
) -> tuple[VisualCase, ...]:
    """Return the cases matching every supplied filter, in manifest order."""
    wanted_ids = {item for item in ids if item}
    wanted_sections = {item for item in sections if item}
    unknown = wanted_ids - {case.id for case in cases}
    if unknown:
        raise ValueError(f"unknown visual case: {', '.join(sorted(unknown))}")
    return tuple(
        case
        for case in cases
        if (provider is None or case.provider == provider)
        and (not wanted_ids or case.id in wanted_ids)
        and (not wanted_sections or case.section in wanted_sections)
    )
