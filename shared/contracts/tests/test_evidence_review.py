"""Evidence review contract: checklist verdict floor and evidence binding."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from shared_contracts import SUPPORTED_PROMPT_SETS
from shared_contracts.evidence_review import (
    REVIEW_MODES,
    REVIEW_PROMPT_SET_VERSIONS,
    REVIEW_PROMPT_SETS,
    EvidenceCheck,
    EvidenceReviewBundle,
    EvidenceReviewOutput,
    OwnerStatus,
    ReviewVerdict,
    blocked_by_root,
    checklist_verdict,
    is_known_ref,
    owner_coverage,
    stricter_verdict,
    validate_review_output,
)


def _check(
    check_id: str,
    status: str,
    *,
    required: bool = True,
    owner: str | None = None,
    blocked_by: str | None = None,
    refs: tuple[str, ...] = (),
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": check_id,
        "title": check_id,
        "status": status,
        "required": required,
        "detail": "detail",
        "evidence_refs": list(refs),
    }
    if owner is not None:
        payload["owner"] = owner
    if blocked_by is not None:
        payload["blocked_by"] = blocked_by
    return payload


def _bundle(*checks: dict[str, Any]) -> EvidenceReviewBundle:
    return EvidenceReviewBundle.model_validate(
        {
            "mode": "cloud",
            "inputs": [{"path": "cloud/smoke.json", "status": "read", "sha256": "b" * 64}],
            "checks": list(checks),
        }
    )


def test_every_review_mode_has_a_supported_prompt_set() -> None:
    assert set(REVIEW_PROMPT_SETS) == set(REVIEW_MODES) == set(REVIEW_PROMPT_SET_VERSIONS)
    assert set(REVIEW_PROMPT_SETS.values()) <= set(SUPPORTED_PROMPT_SETS)
    for mode, versions in REVIEW_PROMPT_SET_VERSIONS.items():
        assert set(versions) <= set(SUPPORTED_PROMPT_SETS)
        assert versions[-1] == REVIEW_PROMPT_SETS[mode] == f"review-{mode}.v2"
        assert f"review-{mode}.v1" in versions, "v1 stays valid for recorded runs"


def test_bundles_written_before_owners_and_blocking_still_parse() -> None:
    legacy = (
        '{"schema_version":"1.0","mode":"testing","inputs":[],"checks":[{"id":"ci.student-1.run",'
        '"title":"t","status":"failed","required":true,"detail":"missing","evidence_refs":[]}],'
        '"facts":{},"compacted":false}'
    )

    bundle = EvidenceReviewBundle.model_validate_json(legacy)

    assert bundle.checks[0].owner is None
    assert bundle.checks[0].blocked_by is None
    assert owner_coverage(bundle) == ()
    assert bundle.checklist_verdict() is ReviewVerdict.FAIL


def test_blocked_checks_name_a_failed_root() -> None:
    with pytest.raises(ValidationError, match="blocked_by is required"):
        EvidenceCheck.model_validate(_check("a", "blocked"))
    with pytest.raises(ValidationError, match="blocked_by is required"):
        EvidenceCheck.model_validate(_check("a", "failed", blocked_by="b"))
    with pytest.raises(ValidationError, match="cannot block itself"):
        EvidenceCheck.model_validate(_check("a", "blocked", blocked_by="a"))
    with pytest.raises(ValidationError, match="not a failed check"):
        _bundle(_check("root", "passed"), _check("child", "blocked", blocked_by="root"))
    with pytest.raises(ValidationError, match="not a failed check"):
        _bundle(_check("child", "blocked", blocked_by="absent"))

    bundle = _bundle(
        _check("root", "failed"),
        _check("child", "blocked", blocked_by="root"),
        _check("other", "blocked", required=False, blocked_by="root"),
    )
    assert blocked_by_root(bundle.checks) == {"root": ("child", "other")}


def test_blocked_checks_weigh_like_failures_in_the_verdict() -> None:
    root = EvidenceCheck.model_validate(_check("root", "failed", required=False))
    blocked_required = EvidenceCheck.model_validate(_check("a", "blocked", blocked_by="root"))
    blocked_advisory = EvidenceCheck.model_validate(
        _check("b", "blocked", required=False, blocked_by="root")
    )

    assert checklist_verdict([root, blocked_advisory]) is ReviewVerdict.PASS_WITH_RISKS
    assert checklist_verdict([root, blocked_required]) is ReviewVerdict.FAIL


def test_owner_coverage_attributes_each_owner_status() -> None:
    gate_2, gate_3 = "ci.student-2.evidence", "ci.student-3.evidence"
    bundle = EvidenceReviewBundle.model_validate(
        {
            "mode": "testing",
            "inputs": [
                {"path": "ci/student-2.md", "status": "missing"},
                {"path": "ci/student-3.md", "status": "invalid"},
            ],
            "checks": [
                _check("security.report", "passed", owner="shared"),
                _check("security.clean", "failed", required=False, owner="shared"),
                _check("ci.student-1.run", "passed", owner="student-1"),
                _check(gate_2, "failed", owner="student-2", refs=("ci/student-2.md",)),
                _check("ci.student-2.run", "blocked", owner="student-2", blocked_by=gate_2),
                _check(gate_3, "failed", owner="student-3", refs=("ci/student-3.md#line-1",)),
                _check("ci.student-3.run", "blocked", owner="student-3", blocked_by=gate_3),
                _check("ci.student-4.run", "failed", owner="student-4"),
                _check("ci.student-5.run", "blocked", owner="student-5", blocked_by=gate_2),
                _check("general", "passed"),
            ],
        }
    )

    coverage = {item.owner: item for item in owner_coverage(bundle)}

    assert list(coverage) == [
        "shared",
        "student-1",
        "student-2",
        "student-3",
        "student-4",
        "student-5",
        "unassigned",
    ]
    assert coverage["shared"].status is OwnerStatus.ADVISORY_GAPS
    assert coverage["student-1"].status is OwnerStatus.COMPLETE
    assert coverage["student-2"].status is OwnerStatus.EVIDENCE_NOT_SUBMITTED
    assert (coverage["student-2"].failed, coverage["student-2"].blocked) == (1, 1)
    assert coverage["student-2"].roots == (gate_2,)
    assert coverage["student-3"].status is OwnerStatus.EVIDENCE_INCOMPLETE
    assert coverage["student-4"].status is OwnerStatus.FAILING
    assert coverage["student-5"].status is OwnerStatus.BLOCKED_UPSTREAM
    assert coverage["unassigned"].status is OwnerStatus.COMPLETE
    assert OwnerStatus.EVIDENCE_NOT_SUBMITTED.label == "evidence not submitted"


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
