"""Health endpoint tests for the AI-mode application scaffold."""

from importlib.metadata import PackageNotFoundError
from unittest.mock import patch

import pytest
from flask.testing import FlaskClient

from agent_core import ProviderHealth
from ai_mode import create_app
from ai_mode.configuration import Settings
from ai_mode.services import AppServices
from shared_testkit import ScriptedLLMProvider


def test_liveness_does_not_require_external_dependencies(app_services: AppServices) -> None:
    client: FlaskClient = create_app(services=app_services).test_client()

    response = client.get("/health/live")

    assert response.status_code == 200
    payload = response.get_json()
    assert isinstance(payload, dict)
    service_version = payload.pop("version")
    assert isinstance(service_version, str)
    assert service_version
    assert payload == {
        "checks": {},
        "service": "ai-mode",
        "status": "healthy",
    }


def test_readiness_reports_current_scaffold_check(app_services: AppServices) -> None:
    client: FlaskClient = create_app(services=app_services).test_client()

    response = client.get("/health/ready")

    assert response.status_code == 200
    assert response.get_json()["checks"]["application"]["status"] == "healthy"


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
    assert response.get_json()["status"] == "degraded"


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
    assert response.get_json()["status"] == "degraded"


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
