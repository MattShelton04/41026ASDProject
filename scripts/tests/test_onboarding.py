"""Tests for enabled-only feature onboarding discovery."""

from __future__ import annotations

from pathlib import Path

import pytest
from scripts.onboarding import (
    OnboardingConfigurationError,
    discover_quality_inputs,
    discover_tool_catalogs,
    load_enabled_projection,
)


def _repository(tmp_path: Path) -> Path:
    root = tmp_path / "repository"
    (root / "deployment").mkdir(parents=True)
    _write_manifest(root, "student-1", "student-1-enabled", enabled_metadata=True)
    _write_manifest(root, "student-2", "student-2-disabled", enabled_metadata=False)
    (root / "student-1" / "tests").mkdir()
    (root / "student-1" / "tests" / "test_feature.py").write_text("", encoding="utf-8")
    (root / "student-1" / "tests" / "frontend.test.mjs").write_text("", encoding="utf-8")
    (root / "student-1" / "tool-catalog.yaml").write_text("services: []\n", encoding="utf-8")
    package = root / "student-1" / "backend" / "src" / "student_1_feature"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    (root / "deployment" / "features.yaml").write_text(
        """
schema_version: 1
features:
  - feature_key: student-1-enabled
    enabled: true
  - feature_key: student-2-disabled
    enabled: false
""".lstrip(),
        encoding="utf-8",
    )
    return root


def _write_manifest(root: Path, owner: str, feature_key: str, *, enabled_metadata: bool) -> None:
    path = root / owner / "feature.yaml"
    path.parent.mkdir(parents=True)
    onboarding = (
        f"""
onboarding:
  ai:
    tool_catalog: {owner}/tool-catalog.yaml
    runtime_path: /etc/ai-mode/{owner}.yaml
  quality:
    python_test_paths: [{owner}/tests]
    node_test_files: [{owner}/tests/frontend.test.mjs]
    coverage_packages: [student_1_feature]
    coverage_fail_under: 70
  databases:
    - database_service: {owner}-postgres
      volumes: [{owner}-postgres-data]
"""
        if enabled_metadata
        else ""
    )
    path.write_text(
        f"""
schema_version: 1
feature_key: {feature_key}
display_name: Example {owner}
owner: {owner}
frontend_base_path: /features/{owner}/
backend_base_path: /api/{owner}/v1
health_path: /health/ready
ai_capabilities: []
{onboarding}
""".lstrip(),
        encoding="utf-8",
    )


def test_only_enabled_feature_inputs_and_catalogues_are_discovered(tmp_path: Path) -> None:
    root = _repository(tmp_path)

    projection = load_enabled_projection(root)
    quality = discover_quality_inputs(root)
    catalogs = discover_tool_catalogs(root)

    assert [feature.feature_key for feature in projection.features] == ["student-1-enabled"]
    assert quality.python_test_paths == ("student-1/tests",)
    assert quality.node_test_files == ("student-1/tests/frontend.test.mjs",)
    assert quality.features[0].coverage_packages == ("student_1_feature",)
    assert quality.features[0].coverage_fail_under == 70
    assert catalogs == (root / "student-1" / "tool-catalog.yaml",)


def test_unknown_selected_feature_is_rejected_even_when_disabled(tmp_path: Path) -> None:
    root = _repository(tmp_path)
    selection = root / "deployment" / "features.yaml"
    selection.write_text(
        "schema_version: 1\nfeatures:\n  - feature_key: student-3-unknown\n    enabled: false\n",
        encoding="utf-8",
    )

    with pytest.raises(OnboardingConfigurationError, match="unknown feature"):
        load_enabled_projection(root)


def test_enabled_feature_requires_onboarding_metadata(tmp_path: Path) -> None:
    root = _repository(tmp_path)
    selection = root / "deployment" / "features.yaml"
    selection.write_text(
        "schema_version: 1\nfeatures:\n  - feature_key: student-2-disabled\n    enabled: true\n",
        encoding="utf-8",
    )

    with pytest.raises(OnboardingConfigurationError, match="has no onboarding"):
        load_enabled_projection(root)


def test_quality_and_catalog_paths_must_stay_in_owning_slice(tmp_path: Path) -> None:
    root = _repository(tmp_path)
    manifest = root / "student-1" / "feature.yaml"
    source = manifest.read_text(encoding="utf-8")
    manifest.write_text(source.replace("student-1/tests]", "student-2/tests]"), encoding="utf-8")

    with pytest.raises(OnboardingConfigurationError, match="must be owned by student-1"):
        discover_quality_inputs(root)

    manifest.write_text(
        source.replace("student-1/tool-catalog.yaml", "student-2/tool-catalog.yaml"),
        encoding="utf-8",
    )
    with pytest.raises(OnboardingConfigurationError, match="must be owned by student-1"):
        load_enabled_projection(root)


def test_enabled_ai_catalogue_must_exist_during_projection_load(tmp_path: Path) -> None:
    root = _repository(tmp_path)
    (root / "student-1" / "tool-catalog.yaml").unlink()

    with pytest.raises(OnboardingConfigurationError, match="AI tool catalogue does not exist"):
        load_enabled_projection(root)


def test_enabled_quality_path_must_exist(tmp_path: Path) -> None:
    root = _repository(tmp_path)
    manifest = root / "student-1" / "feature.yaml"
    manifest.write_text(
        manifest.read_text(encoding="utf-8").replace(
            "student-1/tests]", "student-1/missing-tests]"
        ),
        encoding="utf-8",
    )

    with pytest.raises(OnboardingConfigurationError, match="does not exist"):
        discover_quality_inputs(root)


def test_coverage_package_must_be_owned_by_enabled_feature(tmp_path: Path) -> None:
    root = _repository(tmp_path)
    manifest = root / "student-1" / "feature.yaml"
    manifest.write_text(
        manifest.read_text(encoding="utf-8").replace(
            "coverage_packages: [student_1_feature]",
            "coverage_packages: [student_2_feature]",
        ),
        encoding="utf-8",
    )

    with pytest.raises(OnboardingConfigurationError, match="coverage package is not owned"):
        discover_quality_inputs(root)


def test_enabled_frontend_and_evidence_paths_are_owned_and_exist(tmp_path: Path) -> None:
    root = _repository(tmp_path)
    manifest = root / "student-1" / "feature.yaml"
    source = manifest.read_text(encoding="utf-8")
    source += """  frontend:
    asset_root: student-2/frontend
    service: f1-frontend
    internal_port: 8080
    host_port_variable: F1_PORT
    host_port_default: 5200
"""
    manifest.write_text(source, encoding="utf-8")

    with pytest.raises(OnboardingConfigurationError, match="frontend asset root must be owned"):
        load_enabled_projection(root)

    manifest.write_text(
        manifest.read_text(encoding="utf-8").replace(
            "student-2/frontend", "student-1/missing-frontend"
        ),
        encoding="utf-8",
    )
    with pytest.raises(OnboardingConfigurationError, match="asset root does not exist"):
        load_enabled_projection(root)
