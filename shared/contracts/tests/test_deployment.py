from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import ValidationError

from shared_contracts import (
    DeploymentSelectionV1,
    FeatureManifest,
    HealthStatus,
    ReadinessCheckProjection,
    TypedHealthProjection,
    build_deployment_projection,
    load_feature_manifest,
    project_readiness,
)

ROOT = Path(__file__).resolve().parents[3]


def _manifest(
    owner: str = "student-1",
    *,
    onboarding: dict[str, object] | None = None,
    frontend_base_path: str | None = None,
    backend_base_path: str | None = None,
) -> FeatureManifest:
    return FeatureManifest.model_validate(
        {
            "schema_version": 1,
            "feature_key": f"{owner}-example",
            "display_name": f"{owner} example",
            "owner": owner,
            "frontend_base_path": frontend_base_path or f"/features/{owner}/",
            "backend_base_path": backend_base_path or f"/api/{owner}/v1",
            "health_path": "/health/ready",
            "ai_capabilities": [],
            **({"onboarding": onboarding} if onboarding is not None else {}),
        }
    )


def _onboarding(owner: str = "student-1", *, volume: str | None = None) -> dict[str, Any]:
    return {
        "frontend": {
            "asset_root": f"{owner}/frontend",
            "service": f"{owner}-frontend",
            "internal_port": 8080,
            "host_port_variable": f"{owner.replace('-', '_').upper()}_PORT",
            "host_port_default": 5200,
            "route_fragment": f"{owner}/frontend/routes.js",
        },
        "backend": {
            "service": f"{owner}-backend",
            "internal_port": 5201,
            "additional_paths": [f"/fragments/{owner}/"],
        },
        "ai": {
            "tool_catalog": f"{owner}/tool-catalog.yaml",
            "runtime_path": f"/etc/ai-mode/{owner}-tools.yaml",
        },
        "quality": {
            "python_test_paths": [f"{owner}/tests"],
            "node_test_files": [f"{owner}/tests/frontend/core.test.mjs"],
            "coverage_packages": [f"{owner.replace('-', '_')}_feature"],
            "coverage_fail_under": 60,
        },
        "databases": [
            {
                "database_service": f"{owner}-database",
                "volumes": [volume or f"{owner}-database-data"],
            }
        ],
        "evidence_adapter": {"path": f"{owner}/scripts/evidence.py"},
    }


def test_feature_manifest_onboarding_is_optional_and_closed() -> None:
    assert _manifest().onboarding is None
    manifest = _manifest(onboarding=_onboarding())
    assert manifest.onboarding is not None
    assert manifest.onboarding.ai is not None
    assert manifest.onboarding.ai.runtime_path == "/etc/ai-mode/student-1-tools.yaml"

    invalid = _onboarding()
    invalid["unexpected"] = True
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        _manifest(onboarding=invalid)


@pytest.mark.parametrize(
    ("section", "field", "value"),
    [
        ("frontend", "asset_root", "../student-1/frontend"),
        ("ai", "tool_catalog", "/student-1/tool-catalog.yaml"),
        ("ai", "runtime_path", "workspace/tool-catalog.yaml"),
        ("evidence_adapter", "path", "student-1/../private/evidence.py"),
    ],
)
def test_onboarding_paths_cannot_escape_declared_boundaries(
    section: str, field: str, value: str
) -> None:
    onboarding = _onboarding()
    target = onboarding[section]
    assert isinstance(target, dict)
    target[field] = value
    with pytest.raises(ValidationError):
        _manifest(onboarding=onboarding)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("tool_catalog", "student-1/tool-catalog.json", "YAML catalogue"),
        ("runtime_path", "/app/ai_mode/app.py", "under /etc/ai-mode"),
        ("runtime_path", "/etc/ai-mode/nested/tools.yaml", "under /etc/ai-mode"),
    ],
)
def test_ai_catalogue_mount_is_confined_to_the_dedicated_runtime_directory(
    field: str, value: str, message: str
) -> None:
    onboarding = _onboarding()
    ai = onboarding["ai"]
    assert isinstance(ai, dict)
    ai[field] = value

    with pytest.raises(ValidationError, match=message):
        _manifest(onboarding=onboarding)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("frontend_base_path", "/features/x { return 200; } location /escape"),
        ("backend_base_path", "/api/x;return/v1"),
    ],
)
def test_enabled_projection_rejects_nginx_configuration_injection(field: str, value: str) -> None:
    paths = {field: value}
    manifest = _manifest(onboarding=_onboarding(), **paths)
    selection = DeploymentSelectionV1(
        features=({"feature_key": manifest.feature_key, "enabled": True},)
    )

    with pytest.raises(ValidationError, match="safe unreserved URI path segments"):
        build_deployment_projection((manifest,), selection)


def test_enabled_projection_rejects_shared_reserved_api_namespace() -> None:
    manifest = _manifest(
        onboarding=_onboarding(),
        frontend_base_path="/features/ai-mode/",
        backend_base_path="/api/ai-mode/v1",
    )
    selection = DeploymentSelectionV1(
        features=({"feature_key": manifest.feature_key, "enabled": True},)
    )

    with pytest.raises(ValidationError, match="Shared-reserved"):
        build_deployment_projection((manifest,), selection)


def test_enabled_projection_rejects_additional_path_outside_owned_namespace() -> None:
    onboarding = _onboarding()
    backend = onboarding["backend"]
    assert isinstance(backend, dict)
    backend["additional_paths"] = ["/fragments/another-feature/"]
    manifest = _manifest(onboarding=onboarding)
    selection = DeploymentSelectionV1(
        features=({"feature_key": manifest.feature_key, "enabled": True},)
    )

    with pytest.raises(ValueError, match="feature API or fragment namespace"):
        build_deployment_projection((manifest,), selection)


def test_enabled_projection_rejects_cross_feature_namespace_collision() -> None:
    first_onboarding = _onboarding("student-1")
    second_onboarding = _onboarding("student-2")
    first_onboarding.pop("frontend")
    second_onboarding.pop("frontend")
    first_backend = first_onboarding["backend"]
    second_backend = second_onboarding["backend"]
    assert isinstance(first_backend, dict)
    assert isinstance(second_backend, dict)
    first_backend["additional_paths"] = ["/api/common/v1/meta"]
    second_backend["additional_paths"] = ["/api/common/v2/meta"]
    first = _manifest(
        "student-1",
        onboarding=first_onboarding,
        backend_base_path="/api/common/v1",
    )
    second = _manifest(
        "student-2",
        onboarding=second_onboarding,
        backend_base_path="/api/common/v2",
    )
    selection = DeploymentSelectionV1(
        features=(
            {"feature_key": first.feature_key, "enabled": True},
            {"feature_key": second.feature_key, "enabled": True},
        )
    )

    with pytest.raises(ValidationError, match="route namespace"):
        build_deployment_projection((first, second), selection)


def test_projection_includes_only_explicitly_enabled_features_in_stable_order() -> None:
    first = _manifest("student-1", onboarding=_onboarding("student-1"))
    second = _manifest("student-2", onboarding=_onboarding("student-2"))
    selection = DeploymentSelectionV1.model_validate(
        {
            "schema_version": 1,
            "features": [
                {"feature_key": second.feature_key, "enabled": False},
                {"feature_key": first.feature_key, "enabled": True},
            ],
        }
    )

    projection = build_deployment_projection((second, first), selection)

    assert [feature.feature_key for feature in projection.features] == [first.feature_key]
    assert projection.features[0].enabled is True
    assert [(route.kind, route.path) for route in projection.features[0].routes] == [
        ("frontend", "/features/student-1/"),
        ("backend", "/api/student-1/v1"),
    ]
    assert projection.features[0].quality.python_test_paths == ("student-1/tests",)
    assert projection.features[0].quality.coverage_fail_under == 60


def test_repository_deployment_selection_builds_the_real_enabled_projection() -> None:
    manifest = load_feature_manifest(ROOT / "student-1/feature.yaml")
    selection = DeploymentSelectionV1.model_validate(
        yaml.safe_load((ROOT / "deployment/features.yaml").read_text("utf-8"))
    )

    projection = build_deployment_projection((manifest,), selection)

    assert len(projection.features) == 1
    feature = projection.features[0]
    assert feature.feature_key == "student-1-propertyscope-data-platform"
    assert {route.path for route in feature.routes} == {
        "/features/data-platform/",
        "/api/data-platform/v1",
    }
    assert feature.ai is not None
    assert feature.ai.runtime_path == "/etc/ai-mode/propertyscope-tools.yaml"
    assert feature.databases[0].database_service == "f1-postgres"
    assert feature.databases[0].volumes == ("f1-postgres-data",)
    assert feature.quality.coverage_packages == (
        "propertyscope_data_platform",
        "propertyscope_data_store",
    )


def test_quality_coverage_policy_is_generic_and_closed() -> None:
    invalid = _onboarding()
    invalid["quality"] = {"coverage_packages": ["not-an-import"], "coverage_fail_under": 60}
    with pytest.raises(ValidationError, match="Python import names"):
        _manifest(onboarding=invalid)

    missing_package = _onboarding()
    missing_package["quality"] = {"coverage_fail_under": 60}
    with pytest.raises(ValidationError, match="requires at least one"):
        _manifest(onboarding=missing_package)


def test_projection_rejects_unregistered_or_incomplete_enablement() -> None:
    manifest = _manifest()
    enabled = DeploymentSelectionV1.model_validate(
        {"features": [{"feature_key": manifest.feature_key, "enabled": True}]}
    )
    with pytest.raises(ValueError, match="no onboarding declaration"):
        build_deployment_projection((manifest,), enabled)

    unknown = DeploymentSelectionV1.model_validate(
        {"features": [{"feature_key": "student-2-unknown", "enabled": False}]}
    )
    with pytest.raises(ValueError, match="unknown feature"):
        build_deployment_projection((manifest,), unknown)


@pytest.mark.parametrize(
    ("duplicate_kind", "message"),
    [
        ("route", "duplicate route"),
        ("ai", "duplicate ai_runtime_path"),
        ("database", "duplicate database_service"),
        ("volume", "duplicate volume"),
    ],
)
def test_projection_rejects_duplicate_routes_ai_mounts_and_database_owners(
    duplicate_kind: str, message: str
) -> None:
    first_onboarding = _onboarding("student-1")
    second_onboarding = _onboarding("student-2")
    second_frontend_path: str | None = None
    second_backend_path: str | None = None
    if duplicate_kind == "route":
        second_frontend_path = "/features/student-1/"
        second_backend_path = "/api/student-1/v1"
        second_backend = second_onboarding["backend"]
        assert isinstance(second_backend, dict)
        second_backend["additional_paths"] = ["/fragments/student-1/"]
    elif duplicate_kind == "ai":
        second_onboarding["ai"]["runtime_path"] = "/etc/ai-mode/student-1-tools.yaml"
    elif duplicate_kind == "database":
        second_onboarding["databases"][0]["database_service"] = "student-1-database"
    else:
        second_onboarding["databases"][0]["volumes"] = ["student-1-database-data"]
    first = _manifest("student-1", onboarding=first_onboarding)
    second = _manifest(
        "student-2",
        onboarding=second_onboarding,
        frontend_base_path=second_frontend_path,
        backend_base_path=second_backend_path,
    )
    selection = DeploymentSelectionV1.model_validate(
        {
            "features": [
                {"feature_key": first.feature_key, "enabled": True},
                {"feature_key": second.feature_key, "enabled": True},
            ]
        }
    )

    with pytest.raises(ValueError, match=message):
        build_deployment_projection((first, second), selection)


def test_deployment_selection_rejects_duplicate_feature_keys() -> None:
    with pytest.raises(ValidationError, match="duplicate feature_key"):
        DeploymentSelectionV1.model_validate(
            {
                "features": [
                    {"feature_key": "student-1-example", "enabled": True},
                    {"feature_key": "student-1-example", "enabled": False},
                ]
            }
        )


def test_optional_health_failure_is_explicit_degradation_without_503() -> None:
    projection = project_readiness(
        service="ai-mode",
        version="1.0.0",
        checks={
            "process": ReadinessCheckProjection(required=True, status=HealthStatus.HEALTHY),
            "provider": ReadinessCheckProjection(
                required=False,
                status=HealthStatus.UNHEALTHY,
                detail="offline mode",
            ),
        },
    )

    assert projection.status == HealthStatus.DEGRADED
    assert projection.http_status == 200
    assert projection.media_type == "application/json"


def test_required_health_failure_is_unhealthy_with_503() -> None:
    projection = project_readiness(
        service="feature-backend",
        version="1.0.0",
        checks={"database": ReadinessCheckProjection(required=True, status="unhealthy")},
    )
    assert projection.status == HealthStatus.UNHEALTHY
    assert projection.http_status == 503

    with pytest.raises(ValidationError, match="inconsistent"):
        TypedHealthProjection(
            service="feature-backend",
            version="1.0.0",
            status="healthy",
            http_status=200,
            checks={"database": ReadinessCheckProjection(required=True, status="unhealthy")},
        )
