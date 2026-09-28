"""The visual case inventory and browser-free capture policy."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml
from scripts.visual import capture
from scripts.visual.cases import CASES, Step, VisualCase, select_cases, validate_cases
from scripts.visual.policy import SECTION_IDS, section_for

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = REPOSITORY_ROOT / ".github" / "workflows"


def test_inventory_is_valid_and_covers_every_section() -> None:
    validate_cases()
    assert {case.section for case in CASES} == set(SECTION_IDS)
    for case in CASES:
        assert case.section == section_for(case.id)
        assert case.ready


def test_shared_and_feature_1_use_fixtures_and_other_features_the_stack() -> None:
    for case in CASES:
        if case.section in {"feature-2", "feature-3", "feature-4", "feature-5"}:
            assert case.provider == "stack", case.id
    fixture_sections = {case.section for case in CASES if case.provider == "fixture"}
    assert fixture_sections == {"shared", "feature-1"}


def test_fixture_urls_carry_the_scenario_before_the_hash() -> None:
    case = VisualCase("f1-x", "fixture", "/features/data-platform/#runs", "runs", scenario="error")
    assert case.url("http://127.0.0.1:5990") == (
        "http://127.0.0.1:5990/features/data-platform/?scenario=error#runs"
    )
    stack = VisualCase("f2-x", "stack", "/features/market/", "cases")
    assert stack.url("http://localhost:5100") == "http://localhost:5100/features/market/"


def test_invalid_inventories_are_rejected_before_a_browser_starts() -> None:
    good = VisualCase("shared-a", "fixture", "/", "home")
    with pytest.raises(ValueError, match="duplicate"):
        validate_cases((good, good))
    with pytest.raises(ValueError, match="invalid"):
        validate_cases((VisualCase("Bad_ID", "fixture", "/", "x"),))
    with pytest.raises(ValueError, match="provider"):
        validate_cases((VisualCase("shared-b", "cloud", "/", "x"),))
    with pytest.raises(ValueError, match="absolute"):
        validate_cases((VisualCase("shared-c", "fixture", "relative", "x"),))


def test_case_selection_filters_by_provider_id_and_section() -> None:
    stack = select_cases(provider="stack")
    assert stack and all(case.provider == "stack" for case in stack)
    assert [case.id for case in select_cases(ids=["f1-runs"])] == ["f1-runs"]
    assert all(case.section == "feature-3" for case in select_cases(sections=["feature-3"]))
    with pytest.raises(ValueError, match="unknown"):
        select_cases(ids=["missing-case"])


def test_steps_are_limited_to_known_actions() -> None:
    actions = {step.action for case in CASES for step in case.steps}
    assert actions <= {"click", "fill", "press", "wait", "scroll"}
    assert isinstance(Step("click", "#x"), Step)


def test_stable_screenshots_need_two_identical_captures() -> None:
    frames = iter([b"a", b"b", b"b"])
    assert capture.stable_screenshot(lambda: next(frames)) == (b"b", 3)
    counter = iter(range(100))
    with pytest.raises(RuntimeError, match="identically"):
        capture.stable_screenshot(lambda: str(next(counter)).encode(), limit=3)


def test_head_captures_must_be_complete_but_baselines_may_lack_new_views() -> None:
    captured, failed = {"status": "captured"}, {"status": "failed"}
    assert capture.capture_exit_code([captured, failed], "base") == 0
    assert capture.capture_exit_code([failed], "base") == 1
    assert capture.capture_exit_code([captured, failed], "head") == 1
    assert capture.capture_exit_code([captured], "head") == 0
    assert capture.capture_exit_code([], "head") == 1


class FakeRoute:
    def __init__(self, url: str) -> None:
        self.request = type("Request", (), {"url": url})()
        self.outcome: tuple[str, Any] | None = None

    def fulfill(self, **kwargs: Any) -> None:
        self.outcome = ("fulfill", kwargs)

    def continue_(self) -> None:
        self.outcome = ("continue", None)

    def abort(self) -> None:
        self.outcome = ("abort", None)


def test_network_policy_keeps_captures_same_origin() -> None:
    blocked: list[str] = []
    handle = capture._route_handler("http://127.0.0.1:5990", blocked)
    outcomes = {}
    for url in (
        "http://127.0.0.1:5990/features/data-platform/app.js",
        f"http://127.0.0.1:5990{capture.STILL_STYLESHEET}",
        "https://tiles.openfreemap.org/styles/liberty",
        "https://tiles.openfreemap.org/planet/1/2/3.pbf",
        "https://fonts.googleapis.com/css2",
    ):
        route = FakeRoute(url)
        handle(route)
        assert route.outcome is not None
        outcomes[url] = route.outcome[0]
    assert list(outcomes.values()) == ["continue", "fulfill", "fulfill", "abort", "abort"]
    assert blocked == [
        "https://tiles.openfreemap.org/planet/1/2/3.pbf",
        "https://fonts.googleapis.com/css2",
    ]


def test_workflows_split_untrusted_capture_from_trusted_publishing() -> None:
    capture_workflow = yaml.safe_load((WORKFLOWS / "visual-capture.yml").read_text())
    report_workflow = yaml.safe_load((WORKFLOWS / "visual-report.yml").read_text())
    assert capture_workflow["permissions"] == {"contents": "read"}
    triggers = report_workflow[True]  # PyYAML reads the "on" key as a boolean
    assert triggers["workflow_run"]["workflows"] == [capture_workflow["name"]]
    assert "pull_request" not in triggers and "pull_request_target" not in triggers
    steps = report_workflow["jobs"]["report"]["steps"]
    checkout_refs = [step["with"]["ref"] for step in steps if "checkout" in step.get("uses", "")]
    assert checkout_refs == ["${{ github.event.repository.default_branch }}", "gh-pages"]
    assert any("--only-group visual" in step.get("run", "") for step in steps)
    matrix = capture_workflow["jobs"]["capture"]["strategy"]["matrix"]
    assert matrix == {"revision": ["base", "head"], "provider": ["fixture", "stack"]}
    for workflow in (capture_workflow, report_workflow):
        for job in workflow["jobs"].values():
            for step in job["steps"]:
                if "uses" in step:
                    assert "@" in step["uses"] and len(step["uses"].split("@")[1].split()[0]) == 40
