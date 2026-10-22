"""Feature 3's feature-owned multi-agent workflow definition."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from shared_contracts.multi_agent import WorkflowTemplate

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "student-3/config/multi-agent/workflow.yaml"
CATALOGUE = ROOT / "student-3/tool-catalog.yaml"


def _document() -> dict[str, Any]:
    value = yaml.safe_load(MANIFEST.read_text("utf-8"))
    assert isinstance(value, dict)
    return value


def test_comparison_review_manifest_matches_the_shared_contract() -> None:
    template = WorkflowTemplate.model_validate(_document())

    assert template.id == "f3-suburb-comparison-review"
    assert template.version == "v1"
    assert template.feature_id == "student-3-suburb-analytics"
    assert [field.name for field in template.inputs] == [
        "suburb_comparison_id",
        "reviewer_note",
    ]
    assert template.inputs[0].pattern == r"^[A-Za-z0-9][A-Za-z0-9._-]*$"


def test_workflow_uses_only_the_two_owned_read_only_tools() -> None:
    template = WorkflowTemplate.model_validate(_document())
    catalogue = yaml.safe_load(CATALOGUE.read_text("utf-8"))
    definitions = {item["definition"]["name"]: item["definition"] for item in catalogue["tools"]}
    expected = (
        "suburb.comparison.inspect.v1",
        "crime.saved-comparison-evidence.v1",
    )

    assert template.allowed_tools == expected
    assert tuple(step.tool for step in template.steps) == expected
    assert [step.id for step in template.steps] == ["comparison", "evidence"]
    for name in expected:
        assert definitions[name]["feature_key"] == template.feature_id
        assert definitions[name]["side_effect"] == "read_only"
        assert definitions[name]["requires_approval"] is False


def test_every_step_is_scoped_to_the_requested_saved_comparison() -> None:
    template = WorkflowTemplate.model_validate(_document())

    for step in template.steps:
        assert step.arguments == {
            "suburb_comparison_id": "{{input.suburb_comparison_id}}",
        }


def test_review_checks_cover_identity_consistency_provenance_and_responsible_use() -> None:
    template = WorkflowTemplate.model_validate(_document())
    checks = {check.id: check for check in template.reviewer_checks}

    assert {
        "comparison-inspected",
        "evidence-read",
        "comparison-matches",
        "evidence-matches",
        "localities-comparable",
        "period-consistent",
        "measure-consistent",
        "missing-values-preserved",
        "rate-denominator-valid",
        "evidence-available",
        "sources-recorded",
        "limitations-stated",
        "responsible-use-recorded",
    } == set(checks)
    assert checks["period-consistent"].severity == "critical"
    assert checks["measure-consistent"].severity == "critical"
    assert checks["missing-values-preserved"].severity == "critical"
    assert checks["rate-denominator-valid"].severity == "high"
    assert checks["sources-recorded"].severity == "high"


def test_human_guidance_forbids_safety_rankings_and_discloses_demo_evidence() -> None:
    template = WorkflowTemplate.model_validate(_document())
    guidance = template.human_review_guidance.lower()

    assert "safety rankings" in guidance
    assert "causal claims" in guidance
    assert "predictions" in guidance
    assert "seeded_demonstration" in guidance
    assert "missing observations" in guidance
