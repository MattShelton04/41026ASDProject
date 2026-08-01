"""Health endpoint tests for the AI-mode application scaffold."""

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
