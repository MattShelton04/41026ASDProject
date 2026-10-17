"""The Cloud Deployment Report Review collector against what the cloud tools really write."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from scripts import cloud_smoke, validate_release_images, verify_release_gate
from scripts.devtools.review.workflow import collect_bundle
from scripts.tests import cloud_fixtures
from scripts.tests import review_fixtures as fixtures

from shared_contracts.evidence_review import CheckStatus, EvidenceReviewBundle


def _failed(bundle: EvidenceReviewBundle) -> set[str]:
    return {check.id for check in bundle.checks if check.status is CheckStatus.FAILED}


def _check(bundle: EvidenceReviewBundle, check_id: str) -> str:
    return next(check.detail for check in bundle.checks if check.id == check_id)


@pytest.fixture
def evidence(tmp_path: Path) -> Path:
    root = tmp_path / "evidence"
    fixtures.write_cloud(root)
    return root


def test_the_real_tool_outputs_copied_as_documented_pass_the_review(tmp_path: Path) -> None:
    """Run the producers' own CLIs into the artifact layout and review the copied files."""
    root = tmp_path / "evidence"
    fixtures.write_cloud(root)
    for name in (fixtures.SMOKE_PATH, fixtures.GATE_PATH, fixtures.BUILD_PATH):
        (root / name).unlink()
    artifact = root / "cloud"  # the README copies smoke/, gate/ and build/ unchanged
    assert (
        cloud_smoke.main(
            ["--base-url", fixtures.CLOUD_URL, "--output-dir", str(artifact / "smoke")],
            transport=httpx.MockTransport(cloud_fixtures.FakeEdge()),
            environment={
                "PROPERTYSCOPE_DEPLOY_SHA": fixtures.COMMIT,
                "IMAGE_TAG": fixtures.COMMIT,
                "ACR_LOGIN_SERVER": fixtures.REGISTRY,
            },
        )
        == 0
    )
    assert (
        verify_release_gate.main(
            [
                "--repo",
                fixtures.GITHUB_REPOSITORY,
                "--sha",
                fixtures.COMMIT,
                "--output-dir",
                str(artifact / "gate"),
            ],
            api=cloud_fixtures.green_gate_api(fixtures.COMMIT, fixtures.GITHUB_REPOSITORY),
        )
        == 0
    )
    assert (
        validate_release_images.main(
            ["--sha", fixtures.COMMIT, "--output-dir", str(artifact / "build")],
            runner=cloud_fixtures.FakeDocker(),
        )
        == 0
    )

    bundle = collect_bundle("cloud", root)

    assert _failed(bundle) == set()
    assert bundle.facts["smoke_file"] == "cloud/smoke/cloud-smoke.json"
    assert bundle.facts["crud"] == dict.fromkeys(fixtures.STUDENTS, "passed")
    operations = bundle.facts["crud_operations"]
    assert isinstance(operations, dict)
    assert operations["student-1"] == [
        "create",
        "read",
        "update",
        "confirm-update",
        "delete",
        "confirm-deleted",
    ]
    assert bundle.facts["ai_state"] == "disabled"
    assert "18 image(s)" in _check(bundle, "cloud.images")
    assert "All 6 workflows green" in _check(bundle, "cloud.release-gate")
    inputs = {item.path for item in bundle.inputs}
    assert {"cloud/gate/release-gate.json", "cloud/build/image-build.json"} <= inputs


def test_complete_fixture_evidence_passes_every_check(evidence: Path) -> None:
    bundle = collect_bundle("cloud", evidence)

    assert _failed(bundle) == set()
    ids = [check.id for check in bundle.checks]
    assert ids[:3] == ["cloud.report", "cloud.release-gate", "cloud.build"]
    assert {f"cloud.crud.{student}" for student in fixtures.STUDENTS} <= set(ids)


def test_crud_cases_are_attributed_by_owner_and_need_the_full_cycle(evidence: Path) -> None:
    value = fixtures.smoke()
    checks = value["checks"]
    assert isinstance(checks, list)
    value["checks"] = [
        check
        for check in checks
        if not (check["owner"] == "student-4" and check["operation"] == "confirm-deleted")
        and check["owner"] != "student-5"
    ]
    fixtures.write_json(evidence / fixtures.SMOKE_PATH, value)

    bundle = collect_bundle("cloud", evidence)

    assert {"cloud.crud.student-4", "cloud.crud.student-5"} <= _failed(bundle)
    assert "cloud.crud.student-1" not in _failed(bundle)
    assert "missing step(s): confirm-deleted" in _check(bundle, "cloud.crud.student-4")
    crud = bundle.facts["crud"]
    assert isinstance(crud, dict) and crud["student-5"] == "missing"


def test_an_unreachable_ai_tier_is_not_proof_that_it_is_disabled(evidence: Path) -> None:
    fixtures.write_json(
        evidence / fixtures.SMOKE_PATH, fixtures.smoke(ai_enabled=None, ai_state="unreachable")
    )

    bundle = collect_bundle("cloud", evidence)

    assert "cloud.ai-disabled" in _failed(bundle)
    assert "observed: unreachable" in _check(bundle, "cloud.ai-disabled")


def test_missing_identity_fails_images_and_commit_consistency(evidence: Path) -> None:
    fixtures.write_json(evidence / fixtures.SMOKE_PATH, fixtures.smoke(commit_sha=None, images={}))

    failed = _failed(collect_bundle("cloud", evidence))

    assert {"cloud.images", "cloud.commit-consistency"} <= failed


def test_a_dirty_or_floating_image_tag_is_not_pinned(evidence: Path) -> None:
    value = fixtures.smoke()
    images = value["images"]
    assert isinstance(images, dict)
    images["f1-backend"] = f"{fixtures.REGISTRY}/propertyscope/f1-backend:{fixtures.COMMIT}-dirty"
    fixtures.write_json(evidence / fixtures.SMOKE_PATH, value)

    bundle = collect_bundle("cloud", evidence)

    assert "cloud.images" in _failed(bundle)
    assert "f1-backend" in _check(bundle, "cloud.images")


@pytest.mark.parametrize(
    ("change", "expected"),
    [
        ({"passed": False}, "The gate did not pass"),
        ({"deploy_sha": "a" * 40}, "not the deployed commit"),
    ],
    ids=["gate-failed", "other-commit"],
)
def test_the_release_gate_must_pass_for_the_deployed_commit(
    evidence: Path, change: dict[str, object], expected: str
) -> None:
    fixtures.write_json(evidence / fixtures.GATE_PATH, fixtures.release_gate(**change))

    bundle = collect_bundle("cloud", evidence)

    assert "cloud.release-gate" in _failed(bundle)
    assert expected in _check(bundle, "cloud.release-gate")


def test_the_release_gate_names_missing_and_red_workflows(evidence: Path) -> None:
    value = fixtures.release_gate()
    workflows = value["workflows"]
    assert isinstance(workflows, list)
    workflows[3].update(passed=False, state="failure", conclusion="failure")
    fixtures.write_json(evidence / fixtures.GATE_PATH, value)
    bundle = collect_bundle("cloud", evidence)
    assert "Not green: Student 3 CI (failure)" in _check(bundle, "cloud.release-gate")

    fixtures.write_json(evidence / fixtures.GATE_PATH, fixtures.release_gate(workflows=[]))
    bundle = collect_bundle("cloud", evidence)
    assert "does not record Integration CI" in _check(bundle, "cloud.release-gate")

    (evidence / fixtures.GATE_PATH).unlink()
    bundle = collect_bundle("cloud", evidence)
    assert "cloud.release-gate" in _failed(bundle)
    assert "Evidence gap: cloud/release-gate.json is missing" in _check(
        bundle, "cloud.release-gate"
    )


def test_the_image_build_record_is_advisory(evidence: Path) -> None:
    fixtures.write_json(evidence / fixtures.BUILD_PATH, fixtures.image_build(passed=False))

    bundle = collect_bundle("cloud", evidence)

    build = next(check for check in bundle.checks if check.id == "cloud.build")
    assert build.status is CheckStatus.FAILED and build.required is False


def test_a_legacy_smoke_document_is_still_read(evidence: Path) -> None:
    (evidence / fixtures.SMOKE_PATH).unlink()
    legacy = {
        "base_url": fixtures.CLOUD_URL,
        "commit_sha": fixtures.COMMIT,
        "ai_enabled": False,
        "images": {"f1-backend": f"{fixtures.REGISTRY}/propertyscope/f1-backend:{fixtures.COMMIT}"},
        "checks": [
            {"name": "shared home page", "category": "frontend", "passed": True},
            *(
                {"name": f"{s} CRUD", "category": "crud", "feature": s, "status": "success"}
                for s in fixtures.STUDENTS
            ),
            {"name": "AI routes disabled", "category": "ai_disabled", "passed": True},
        ],
    }
    fixtures.write_json(evidence / "cloud/smoke.json", legacy)

    bundle = collect_bundle("cloud", evidence)

    assert bundle.facts["smoke_file"] == "cloud/smoke.json"
    assert _failed(bundle) == set()


def test_the_current_smoke_file_wins_and_extra_copies_are_named(evidence: Path) -> None:
    fixtures.write_json(evidence / "cloud/smoke.json", {"checks": []})
    fixtures.write_json(evidence / "cloud/smoke/cloud-smoke.json", fixtures.smoke())

    bundle = collect_bundle("cloud", evidence)

    assert bundle.facts["smoke_file"] == fixtures.SMOKE_PATH
    assert "cloud/smoke/cloud-smoke.json" in _check(bundle, "cloud.smoke")
    assert "cloud.smoke" not in _failed(bundle)


def test_a_deploy_script_error_line_fails_the_workflow_check(evidence: Path) -> None:
    log = evidence / "cloud" / "logs" / "push.log"
    log.write_text("[deploy.sh] ERROR: ACR has no images for x; run push first\n", encoding="utf-8")

    bundle = collect_bundle("cloud", evidence)

    assert "cloud.workflow" in _failed(bundle)
    assert "cloud/logs/push.log#line-1" in _check(bundle, "cloud.workflow")
