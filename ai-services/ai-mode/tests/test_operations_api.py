"""Component tests for the flagged operations HTTP and dashboard surface."""

from pathlib import Path
from uuid import uuid4

from flask import Flask

from ai_mode import create_app
from ai_mode.configuration import ConfigurationError, Settings
from ai_mode.services import AppServices
from shared_contracts import REQUEST_ID_HEADER
from shared_testkit import assert_problem_detail


def _enabled_app(app_services: AppServices) -> Flask:
    app = create_app(Settings(operations_enabled=True), services=app_services)
    app.config.update(TESTING=True)
    return app


def test_operations_surface_is_absent_by_default(app: Flask) -> None:
    client = app.test_client()

    assert client.get("/operations/ai-mode/").status_code == 404
    assert client.get("/api/v1/agent-runs").status_code == 405
    assert client.get(f"/api/v1/operations/agent-runs/{uuid4()}").status_code == 404


def test_enabled_dashboard_serves_hardened_assets(app_services: AppServices) -> None:
    client = _enabled_app(app_services).test_client()

    page = client.get("/operations/ai-mode/")
    script = client.get("/operations/ai-mode/assets/app.js")
    polling = client.get("/operations/ai-mode/assets/polling.js")
    tokens = client.get("/operations/ai-mode/design-system/tokens.css")
    blocked_design_asset = client.get("/operations/ai-mode/design-system/components.css")
    test_asset = client.get("/operations/ai-mode/assets/polling.test.mjs")

    assert page.status_code == 200
    assert b"PropertyScope | Agent activity" in page.data
    assert b"Shared operational evidence" in page.data
    assert b"http://localhost:5100/" in page.data
    assert page.headers["Cache-Control"] == "no-store"
    assert "frame-ancestors 'none'" in page.headers["Content-Security-Policy"]
    assert script.status_code == 200
    assert script.headers["X-Content-Type-Options"] == "nosniff"
    assert b"innerHTML" not in script.data
    assert polling.status_code == 200
    assert polling.headers["X-Content-Type-Options"] == "nosniff"
    assert b"RequestTimeoutError" in polling.data
    assert tokens.status_code == 200
    assert b"--ps-ocean-700" in tokens.data
    assert blocked_design_asset.status_code == 404
    assert test_asset.status_code == 404


def test_enabled_run_index_filters_and_returns_projected_detail(
    app_services: AppServices,
) -> None:
    client = _enabled_app(app_services).test_client()
    created = client.post(
        "/api/v1/agent-runs",
        json={"feature_key": "student-1-feature", "objective": "Inspect safe records"},
        headers={REQUEST_ID_HEADER: "operations-api-test"},
    )
    run_id = created.get_json()["id"]

    page = client.get("/api/v1/agent-runs?status=queued&feature_key=student-1-feature")
    evidence = client.get(f"/api/v1/operations/agent-runs/{run_id}")
    unchanged = client.get(
        f"/api/v1/operations/agent-runs/{run_id}",
        headers={"If-None-Match": evidence.headers["ETag"]},
    )

    assert page.status_code == 200
    assert page.headers[REQUEST_ID_HEADER]
    assert [item["id"] for item in page.get_json()["items"]] == [run_id]
    assert evidence.status_code == 200
    assert evidence.get_json()["objective"] == "Inspect safe records"
    assert evidence.get_json()["correlation"]["request_id"] == "operations-api-test"
    assert unchanged.status_code == 304
    assert unchanged.data == b""


def test_run_index_rejects_unknown_filters_bounds_and_cursors(
    app_services: AppServices,
) -> None:
    client = _enabled_app(app_services).test_client()

    unknown = client.get("/api/v1/agent-runs?search=secret")
    bad_limit = client.get("/api/v1/agent-runs?limit=101")
    bad_status = client.get("/api/v1/agent-runs?status=unknown")
    bad_cursor = client.get("/api/v1/agent-runs?cursor=not-base64!")
    absent = client.get(f"/api/v1/operations/agent-runs/{uuid4()}")

    assert_problem_detail(unknown.get_json(), status=400, code="run_filter_invalid")
    assert_problem_detail(bad_limit.get_json(), status=400, code="run_filter_invalid")
    assert_problem_detail(bad_status.get_json(), status=400, code="run_filter_invalid")
    assert_problem_detail(bad_cursor.get_json(), status=400, code="run_cursor_invalid")
    assert_problem_detail(absent.get_json(), status=404, code="agent_run_not_found")


def test_enabled_dashboard_fails_fast_when_assets_are_missing(
    app_services: AppServices, tmp_path: Path
) -> None:
    missing = tmp_path / "missing-assets"

    try:
        create_app(
            Settings(operations_enabled=True, operations_assets_path=missing),
            services=app_services,
        )
    except ConfigurationError as exc:
        assert "operations assets are unavailable" in str(exc)
    else:
        raise AssertionError("missing operations assets must fail startup")
