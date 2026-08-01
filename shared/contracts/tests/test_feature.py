"""Tests for deterministic feature-manifest discovery."""

from pathlib import Path

import pytest

from shared_contracts import (
    FeatureManifestError,
    load_feature_manifest,
    load_feature_manifests,
)

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "features"
EXAMPLE_MANIFEST = (
    Path(__file__).resolve().parents[3] / "examples" / "integration-test-feature" / "feature.yaml"
)


def _write_manifest(path: Path, *, owner: str, feature_key: str, frontend: str) -> None:
    path.write_text(
        f"""schema_version: 1
feature_key: {feature_key}
display_name: Test feature
owner: {owner}
frontend_base_path: {frontend}
backend_base_path: /api/features/{owner}/v1
health_path: /health/ready
ai_capabilities: []
""",
        encoding="utf-8",
    )


def test_manifest_loads_safe_owned_routes(tmp_path: Path) -> None:
    path = tmp_path / "feature.yaml"
    _write_manifest(
        path,
        owner="student-1",
        feature_key="student-1-records",
        frontend="/features/student-1",
    )

    manifest = load_feature_manifest(path)

    assert manifest.owner == "student-1"
    assert manifest.feature_key == "student-1-records"


def test_five_owner_fixtures_form_a_complete_deterministic_catalogue() -> None:
    manifests = load_feature_manifests(FIXTURE_ROOT.glob("*.yaml"))

    assert [manifest.owner for manifest in manifests] == [
        f"student-{index}" for index in range(1, 6)
    ]


def test_integration_test_feature_uses_the_same_manifest_contract() -> None:
    manifest = load_feature_manifest(EXAMPLE_MANIFEST)

    assert manifest.feature_key == "student-1-integration-test"
    assert manifest.ai_capabilities == (
        "integration_test.records.search.v1",
        "integration_test.records.create.v1",
    )


@pytest.mark.parametrize(
    ("feature_key", "frontend"),
    [
        ("student-2-records", "/features/student-1"),
        ("student-1-records", "//external.example/path"),
        ("student-1-records", "/features/../admin"),
        ("student-1-records", "/features/student-1?next=external"),
    ],
)
def test_manifest_rejects_mismatched_or_unsafe_values(
    tmp_path: Path,
    feature_key: str,
    frontend: str,
) -> None:
    path = tmp_path / "feature.yaml"
    _write_manifest(path, owner="student-1", feature_key=feature_key, frontend=frontend)

    with pytest.raises(FeatureManifestError, match="invalid feature manifest"):
        load_feature_manifest(path)


def test_manifest_set_is_sorted_and_rejects_duplicate_routes(tmp_path: Path) -> None:
    second = tmp_path / "second.yaml"
    first = tmp_path / "first.yaml"
    _write_manifest(
        second,
        owner="student-2",
        feature_key="student-2-records",
        frontend="/features/student-2",
    )
    _write_manifest(
        first,
        owner="student-1",
        feature_key="student-1-records",
        frontend="/features/student-1",
    )

    manifests = load_feature_manifests([second, first])

    assert [manifest.owner for manifest in manifests] == ["student-1", "student-2"]
    second.write_text(
        second.read_text(encoding="utf-8").replace("/features/student-2", "/features/student-1"),
        encoding="utf-8",
    )
    with pytest.raises(FeatureManifestError, match="duplicate frontend_base_path"):
        load_feature_manifests([first, second])
