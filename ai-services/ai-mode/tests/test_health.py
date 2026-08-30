"""Health endpoint tests for the AI-mode application scaffold."""

from importlib.metadata import PackageNotFoundError
from unittest.mock import patch

import pytest
from flask.testing import FlaskClient

from agent_core import ProviderHealth
from ai_mode import create_app
from ai_mode.configuration import Settings
from ai_mode.services import AppServices
from shared_contracts import TypedHealthProjection
from shared_testkit import ScriptedLLMProvider


def test_liveness_does_not_require_external_dependencies(app_services: AppServices) -> None:
    client: FlaskClient = create_app(services=app_services).test_client()

    response = client.get("/health/live")

    assert response.status_code == 200
    assert response.mimetype == "application/json"
    payload = response.get_json()
    assert isinstance(payload, dict)
    TypedHealthProjection.model_validate(payload)
    service_version = payload.pop("version")
    assert isinstance(service_version, str)
    assert service_version
    assert payload == {
        "checks": {
            "process": {
                "detail": "AI-mode process is accepting HTTP requests",
                "required": True,
                "status": "healthy",
            }
        },
        "http_status": 200,
        "media_type": "application/json",
        "schema_version": 1,
        "service": "ai-mode",
        "status": "healthy",
    }


def test_liveness_stays_healthy_during_optional_provider_degradation(
    app_services: AppServices,
) -> None:
    app_services.provider = ScriptedLLMProvider(
        [],
        health=ProviderHealth(reachable=False, detail="offline mode"),
    )
    client: FlaskClient = create_app(services=app_services).test_client()

    response = client.get("/health/live")

    assert response.status_code == 200
    payload = TypedHealthProjection.model_validate(response.get_json())
    assert payload.status.value == "healthy"
    assert payload.checks["process"].status.value == "healthy"


def test_readiness_reports_explicit_typed_projection(app_services: AppServices) -> None:
    client: FlaskClient = create_app(services=app_services).test_client()

    response = client.get("/health/ready")

    assert response.status_code == 200
    assert response.mimetype == "application/json"
    projection = TypedHealthProjection.model_validate(response.get_json())
    assert projection.status.value == "healthy"
    assert projection.http_status == response.status_code


def test_degraded_provider_is_available_when_strict_readiness_is_disabled(
    app_services: AppServices,
) -> None:
    app_services.provider = ScriptedLLMProvider(
        [],
        health=ProviderHealth(reachable=False, detail="configured model is missing"),
    )
    client: FlaskClient = create_app(services=app_services).test_client()

    response = client.get("/health/ready")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["status"] == "degraded"
    assert payload["http_status"] == 200
    assert payload["checks"]["llm_provider"] == {
        "required": False,
        "status": "degraded",
        "detail": "configured model is missing",
    }


def test_strict_readiness_requires_the_configured_provider_model(
    app_services: AppServices,
) -> None:
    app_services.provider = ScriptedLLMProvider(
        [],
        health=ProviderHealth(reachable=False, detail="configured model is missing"),
    )
    settings = Settings.from_env({"AI_MODE_REQUIRE_PROVIDER_READY": "true"})
    client: FlaskClient = create_app(settings, services=app_services).test_client()

    response = client.get("/health/ready")

    assert response.status_code == 503
    payload = response.get_json()
    assert payload["status"] == "unhealthy"
    assert payload["http_status"] == 503
    assert payload["checks"]["llm_provider"]["required"] is True
    assert payload["checks"]["llm_provider"]["status"] == "unhealthy"


def test_readiness_uses_provider_neutral_dependency_name(app_services: AppServices) -> None:
    client: FlaskClient = create_app(services=app_services).test_client()

    response = client.get("/health/ready")

    assert "llm_provider" in response.get_json()["checks"]
    assert "ollama" not in response.get_json()["checks"]


@pytest.mark.parametrize("path", ["/health/live", "/health/ready"])
def test_health_endpoints_tolerate_missing_package_metadata(
    path: str, app_services: AppServices
) -> None:
    with patch("ai_mode.app.version", side_effect=PackageNotFoundError("ai-mode")):
        client: FlaskClient = create_app(services=app_services).test_client()

    response = client.get(path)

    assert response.status_code == 200
    assert response.get_json()["version"] == "0+unknown"
