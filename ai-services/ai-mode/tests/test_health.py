"""Health endpoint tests for the AI-mode application scaffold."""

from importlib.metadata import PackageNotFoundError
from unittest.mock import patch

import pytest
from flask.testing import FlaskClient

from ai_mode import create_app


def test_liveness_does_not_require_external_dependencies() -> None:
    client: FlaskClient = create_app().test_client()

    response = client.get("/health/live")

    assert response.status_code == 200
    assert response.get_json() == {
        "checks": {},
        "service": "ai-mode",
        "status": "healthy",
        "version": "0.1.0",
    }


def test_readiness_reports_current_scaffold_check() -> None:
    client: FlaskClient = create_app().test_client()

    response = client.get("/health/ready")

    assert response.status_code == 200
    assert response.get_json()["checks"]["application"]["status"] == "healthy"


@pytest.mark.parametrize("path", ["/health/live", "/health/ready"])
def test_health_endpoints_tolerate_missing_package_metadata(path: str) -> None:
    with patch("ai_mode.app.version", side_effect=PackageNotFoundError("ai-mode")):
        client: FlaskClient = create_app().test_client()

    response = client.get(path)

    assert response.status_code == 200
    assert response.get_json()["version"] == "0+unknown"
