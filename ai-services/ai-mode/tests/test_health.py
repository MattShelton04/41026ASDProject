"""Health endpoint tests for the AI-mode application scaffold."""

from importlib.metadata import PackageNotFoundError
from unittest.mock import patch

import pytest
from flask.testing import FlaskClient

from ai_mode import create_app
from ai_mode.services import AppServices


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


@pytest.mark.parametrize("path", ["/health/live", "/health/ready"])
def test_health_endpoints_tolerate_missing_package_metadata(
    path: str, app_services: AppServices
) -> None:
    with patch("ai_mode.app.version", side_effect=PackageNotFoundError("ai-mode")):
        client: FlaskClient = create_app(services=app_services).test_client()

    response = client.get(path)

    assert response.status_code == 200
    assert response.get_json()["version"] == "0+unknown"
