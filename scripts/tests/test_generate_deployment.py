"""Tests for generated enabled-feature projections."""

from __future__ import annotations

import json
from pathlib import Path

import yaml
from scripts.generate_deployment import generated_outputs


def _repository(tmp_path: Path, *, enabled: bool) -> Path:
    root = tmp_path / "repository"
    (root / "deployment").mkdir(parents=True)
    (root / "student-1").mkdir()
    (root / "student-1" / "frontend").mkdir()
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
        },
    }
    (root / "deployment" / "features.yaml").write_text(
        yaml.safe_dump(selection, sort_keys=False), encoding="utf-8"
    )
    (root / "student-1" / "feature.yaml").write_text(
        yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8"
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
    assert json.loads(disabled[Path("deployment/enabled-features.v1.json")])["features"] == []
    assert (
        "student-1-example" not in disabled[Path("shared/frontend/generated/enabled-features.js")]
    )
    assert disabled[Path("deployment/enabled-features.compose.yml")] == "services: {}\n"
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
        },
    }
    (second_root / "feature.yaml").write_text(
        yaml.safe_dump(second_manifest, sort_keys=False), encoding="utf-8"
    )
    selection_path = root / "deployment" / "features.yaml"
    selection = yaml.safe_load(selection_path.read_text(encoding="utf-8"))
    selection["features"].append({"feature_key": "student-2-second", "enabled": True})
    selection_path.write_text(yaml.safe_dump(selection, sort_keys=False), encoding="utf-8")

    outputs = generated_outputs(root)

    javascript = outputs[Path("shared/frontend/generated/enabled-features.js")]
    assert '"featureKey": "student-2-second"' in javascript
    assert '"displayName": "Second enabled feature"' in javascript
    assert (
        "location ^~ /features/second/"
        in outputs[Path("shared/frontend/generated/enabled-feature-routes.conf")]
    )
    assert (
        'data-feature-id="second"' in outputs[Path("shared/frontend/fragments/research-areas.html")]
    )
