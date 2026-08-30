"""Tests for generated enabled-feature projections."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from scripts.generate_deployment import generated_outputs


def _repository(tmp_path: Path, *, enabled: bool) -> Path:
    root = tmp_path / "repository"
    (root / "deployment").mkdir(parents=True)
    (root / "student-1").mkdir()
    (root / "student-1" / "frontend").mkdir()
    (root / "student-1" / "frontend" / "integration").mkdir()
    (root / "student-1" / "frontend" / "integration" / "evidence.js").write_text(
        "export function createShellEvidenceAdapter() {}\n", encoding="utf-8"
    )
    (root / "shared" / "frontend" / "fragments").mkdir(parents=True)
    (root / "shared" / "frontend" / "fragments" / "planned-research-areas.html").write_text(
        '<article data-feature-state="planned"></article>\n', encoding="utf-8"
    )
    selection = {
        "schema_version": 1,
        "features": [{"feature_key": "student-1-example", "enabled": enabled}],
    }
    manifest = {
        "schema_version": 1,
        "feature_key": "student-1-example",
        "display_name": "Example",
        "owner": "student-1",
        "frontend_base_path": "/features/example/",
        "backend_base_path": "/api/example/v1",
        "health_path": "/health/ready",
        "onboarding": {
            "frontend": {
                "asset_root": "student-1/frontend",
                "service": "example-frontend",
                "internal_port": 8080,
                "host_port_variable": "EXAMPLE_PORT",
                "host_port_default": 5200,
            },
            "backend": {"service": "example-backend", "internal_port": 5201},
            "evidence_adapter": {"path": "student-1/frontend/integration/evidence.js"},
        },
    }
    (root / "deployment" / "features.yaml").write_text(
        yaml.safe_dump(selection, sort_keys=False), encoding="utf-8"
    )
    (root / "student-1" / "feature.yaml").write_text(
        yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8"
    )
    (root / "docker-compose.yml").write_text(
        yaml.safe_dump(
            {
                "services": {
                    "example-frontend": {
                        "build": ".",
                        "labels": {"propertyscope.feature-key": "student-1-example"},
                    },
                    "example-backend": {
                        "build": ".",
                        "labels": {"propertyscope.feature-key": "student-1-example"},
                    },
                }
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return root


def test_outputs_expose_only_explicitly_enabled_features(tmp_path: Path) -> None:
    enabled = generated_outputs(_repository(tmp_path / "enabled", enabled=True))
    disabled = generated_outputs(_repository(tmp_path / "disabled", enabled=False))

    projection = json.loads(enabled[Path("deployment/enabled-features.v1.json")])
    assert projection["features"][0]["feature_key"] == "student-1-example"
    assert (
        '"featureKey": "student-1-example"'
        in enabled[Path("shared/frontend/generated/enabled-features.js")]
    )
    assert (
        '"evidenceAdapterPath": "/features/example/integration/evidence.js"'
        in enabled[Path("shared/frontend/generated/enabled-features.js")]
    )
    assert json.loads(disabled[Path("deployment/enabled-features.v1.json")])["features"] == []
    assert (
        "student-1-example" not in disabled[Path("shared/frontend/generated/enabled-features.js")]
    )
    assert disabled[Path("deployment/enabled-features.compose.yml")] == "services: {}\n"
    assert json.loads(enabled[Path("deployment/enabled-services.v1.json")])["services"] == [
        "example-backend",
        "example-frontend",
    ]
    assert json.loads(enabled[Path("deployment/enabled-services.v1.json")])["build_services"] == [
        "example-backend",
        "example-frontend",
    ]
    assert json.loads(disabled[Path("deployment/enabled-services.v1.json")])["build_services"] == []
    assert json.loads(disabled[Path("deployment/enabled-services.v1.json")])["services"] == []
    assert json.loads(enabled[Path("deployment/enabled-services.v1.json")])[
        "disabled_services"
    ] == []
    assert json.loads(disabled[Path("deployment/enabled-services.v1.json")])[
        "disabled_services"
    ] == ["example-backend", "example-frontend"]
    enabled_compose = yaml.safe_load(enabled[Path("deployment/enabled-features.compose.yml")])
    assert enabled_compose["services"]["example-backend"]["profiles"] == ["release-0"]
    assert (
        "example-frontend"
        not in disabled[Path("shared/frontend/generated/enabled-feature-routes.conf")]
    )


def test_second_enabled_manifest_needs_no_shared_registry_edit(tmp_path: Path) -> None:
    root = _repository(tmp_path, enabled=True)
    second_root = root / "student-2"
    (second_root / "frontend" / "integration").mkdir(parents=True)
    (second_root / "frontend" / "integration" / "area.html").write_text(
        '<article data-feature-id="second"></article>\n', encoding="utf-8"
    )
    (second_root / "frontend" / "integration" / "evidence.js").write_text(
        "export function createShellEvidenceAdapter() {}\n", encoding="utf-8"
    )
    second_manifest = {
        "schema_version": 1,
        "feature_key": "student-2-second",
        "display_name": "Second enabled feature",
        "owner": "student-2",
        "frontend_base_path": "/features/second/",
        "backend_base_path": "/api/second/v1",
        "health_path": "/health/ready",
        "onboarding": {
            "frontend": {
                "asset_root": "student-2/frontend",
                "service": "second-frontend",
                "internal_port": 8080,
                "host_port_variable": "SECOND_PORT",
                "host_port_default": 5300,
                "route_fragment": "student-2/frontend/integration/area.html",
            },
            "backend": {"service": "second-backend", "internal_port": 5301},
            "evidence_adapter": {"path": "student-2/frontend/integration/evidence.js"},
        },
    }
    (second_root / "feature.yaml").write_text(
        yaml.safe_dump(second_manifest, sort_keys=False), encoding="utf-8"
    )
    selection_path = root / "deployment" / "features.yaml"
    selection = yaml.safe_load(selection_path.read_text(encoding="utf-8"))
    selection["features"].append({"feature_key": "student-2-second", "enabled": True})
    selection_path.write_text(yaml.safe_dump(selection, sort_keys=False), encoding="utf-8")
    compose_path = root / "docker-compose.yml"
    compose = yaml.safe_load(compose_path.read_text(encoding="utf-8"))
    compose["services"]["second-frontend"] = {
        "labels": {"propertyscope.feature-key": "student-2-second"}
    }
    compose["services"]["second-backend"] = {
        "labels": {"propertyscope.feature-key": "student-2-second"}
    }
    compose_path.write_text(yaml.safe_dump(compose, sort_keys=False), encoding="utf-8")

    outputs = generated_outputs(root)

    javascript = outputs[Path("shared/frontend/generated/enabled-features.js")]
    assert '"featureKey": "student-2-second"' in javascript
    assert '"displayName": "Second enabled feature"' in javascript
    assert '"evidenceAdapterPath": "/features/second/integration/evidence.js"' in javascript
    assert (
        "location ^~ /features/second/"
        in outputs[Path("shared/frontend/generated/enabled-feature-routes.conf")]
    )
    assert (
        'data-feature-id="second"' in outputs[Path("shared/frontend/fragments/research-areas.html")]
    )
    services = json.loads(outputs[Path("deployment/enabled-services.v1.json")])["services"]
    assert "second-backend" in services
    assert "second-frontend" in services


def test_evidence_adapter_must_be_served_by_the_feature_frontend(tmp_path: Path) -> None:
    root = _repository(tmp_path, enabled=True)
    manifest_path = root / "student-1" / "feature.yaml"
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    manifest["onboarding"]["evidence_adapter"]["path"] = "student-1/private/evidence.js"
    (root / "student-1" / "private").mkdir()
    (root / "student-1" / "private" / "evidence.js").write_text("export {};\n", encoding="utf-8")
    manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")

    with pytest.raises(ValueError, match="must be served from its frontend asset root"):
        generated_outputs(root)


def test_declared_service_must_have_matching_compose_ownership(tmp_path: Path) -> None:
    root = _repository(tmp_path, enabled=True)
    compose_path = root / "docker-compose.yml"
    compose = yaml.safe_load(compose_path.read_text(encoding="utf-8"))
    del compose["services"]["example-backend"]["labels"]
    compose_path.write_text(yaml.safe_dump(compose, sort_keys=False), encoding="utf-8")

    with pytest.raises(ValueError, match="example-backend must declare feature ownership"):
        generated_outputs(root)
