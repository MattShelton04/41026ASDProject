"""Evidence review contract: checklist verdict floor and evidence binding."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from shared_contracts import SUPPORTED_PROMPT_SETS
from shared_contracts.evidence_review import (
    REVIEW_MODES,
    REVIEW_PROMPT_SETS,
    EvidenceCheck,
    EvidenceReviewBundle,
    EvidenceReviewOutput,
    ReviewVerdict,
    checklist_verdict,
    is_known_ref,
    stricter_verdict,
    validate_review_output,
)


def _check(check_id: str, status: str, *, required: bool = True) -> dict[str, Any]:
    return {
        "id": check_id,
        "title": check_id,
        "status": status,
        "required": required,
        "detail": "detail",
    }


def _bundle(*checks: dict[str, Any]) -> EvidenceReviewBundle:
    return EvidenceReviewBundle.model_validate(
        {
            "mode": "cloud",
            "inputs": [{"path": "cloud/smoke.json", "status": "read", "sha256": "b" * 64}],
            "checks": list(checks),
        }
    )


def test_every_review_mode_has_a_supported_prompt_set() -> None:
    assert set(REVIEW_PROMPT_SETS) == set(REVIEW_MODES)
    assert set(REVIEW_PROMPT_SETS.values()) <= set(SUPPORTED_PROMPT_SETS)


def test_checklist_verdict_and_stricter_verdict() -> None:
    passed = EvidenceCheck.model_validate(_check("a", "passed"))
    advisory = EvidenceCheck.model_validate(_check("b", "failed", required=False))
    required = EvidenceCheck.model_validate(_check("c", "failed"))

    assert checklist_verdict([passed]) is ReviewVerdict.PASS
    assert checklist_verdict([passed, advisory]) is ReviewVerdict.PASS_WITH_RISKS
    assert checklist_verdict([advisory, required]) is ReviewVerdict.FAIL
    assert stricter_verdict(ReviewVerdict.PASS, ReviewVerdict.FAIL) is ReviewVerdict.FAIL
    assert stricter_verdict(ReviewVerdict.FAIL, ReviewVerdict.PASS) is ReviewVerdict.FAIL


def test_bundle_rejects_duplicate_identities() -> None:
    with pytest.raises(ValidationError, match="check ids"):
        _bundle(_check("a", "passed"), _check("a", "failed"))
    with pytest.raises(ValidationError, match="input paths"):
        EvidenceReviewBundle.model_validate(
            {
                "mode": "testing",
                "inputs": [
                    {"path": "ci/student-1.md", "status": "missing"},
                    {"path": "ci/student-1.md", "status": "missing"},
                ],
                "checks": [_check("a", "passed")],
            }
        )


def test_review_output_must_cite_bundle_evidence_and_respect_the_floor() -> None:
    bundle = _bundle(
        _check("cloud.smoke", "passed"), _check("cloud.https", "failed", required=False)
    )
    finding = {
        "severity": "medium",
        "area": "cloud",
        "message": "HTTPS is not configured.",
        "evidence_refs": ["cloud.https", "cloud/smoke.json#checks"],
    }
    valid = EvidenceReviewOutput.model_validate(
        {"summary": "s", "findings": [finding], "verdict": "pass_with_risks"}
    )

    assert validate_review_output(valid, bundle) is valid
    assert is_known_ref("cloud/smoke.json:12", bundle.evidence_refs())
    assert not is_known_ref("cloud/other.json", bundle.evidence_refs())
    with pytest.raises(ValueError, match="more lenient"):
        validate_review_output(valid.evolve(verdict="pass"), bundle)
    invented = valid.evolve(findings=[{**finding, "evidence_refs": ["cloud/invented.md"]}])
    with pytest.raises(ValueError, match=r"cloud/invented.md"):
        validate_review_output(invented, bundle)
    assert validate_review_output(valid.evolve(verdict="fail"), bundle).verdict is (
        ReviewVerdict.FAIL
    )
