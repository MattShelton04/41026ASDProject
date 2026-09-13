from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx
from flask.testing import FlaskClient

from propertyscope_data_platform.app import create_app
from propertyscope_data_platform.clients import AiModeClient, DataStoreClient

SOURCE_ID = "10000000-0000-4000-8000-000000000001"


def _source(**overrides: Any) -> dict[str, Any]:
    return {
        "id": SOURCE_ID,
        "version": 3,
        "name": "Example source",
        "publisher": "Example publisher",
        "source_url": "https://example.test/source",
        "adapter_key": "fixture-source",
        "cadence": "monthly",
        "licence_id": "cc-by-4.0",
        "licence_url": "https://example.test/licence",
        "redistribution_policy": "attributed",
        "target_features_json": ["feature-1"],
        "status": "draft",
        "notes": "Fixture evidence",
        "created_at": "2026-08-29T00:00:00Z",
        "updated_at": "2026-08-29T00:00:00Z",
    } | overrides


def _form(**overrides: str) -> dict[str, str]:
    return {
        "name": "Created source",
        "publisher": "Fixture publisher",
        "source_url": "https://example.test/created",
        "adapter_key": "fixture-source",
        "cadence": "monthly",
        "licence_id": "cc-by-4.0",
        "licence_url": "https://example.test/licence",
        "redistribution_policy": "attributed",
        "target_features": '["feature-1"]',
        "status": "draft",
        "notes": "Created in a component test",
    } | overrides


def _client(handler: Callable[[httpx.Request], httpx.Response]) -> FlaskClient:
    transport = httpx.MockTransport(handler)
    store = DataStoreClient("http://database", "secret", client=httpx.Client(transport=transport))
    ai = AiModeClient("http://ai", client=httpx.Client(transport=transport))
    return create_app(store_client=store, ai_mode_client=ai).test_client()


def test_source_list_fragment_is_html_escaped_and_uses_real_htmx_actions() -> None:
    def database(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/internal/data-platform/v1/sources"
        assert request.headers["X-PropertyScope-Internal-Token"] == "secret"
        return httpx.Response(200, json={"items": [_source(name="<script>unsafe</script>")]})

    response = _client(database).get(
        "/fragments/data-platform/v1/sources?status=all",
        headers={"X-Request-ID": "fragment-list-request"},
    )

    assert response.status_code == 200
    assert response.content_type == "text/html; charset=utf-8"
    assert response.headers["Cache-Control"] == "no-store"
    assert b"&lt;script&gt;unsafe&lt;/script&gt;" in response.data
    assert b"<script>unsafe</script>" not in response.data
    assert b'hx-get="/fragments/data-platform/v1/sources/new"' in response.data
    assert (
        b'hx-get="/fragments/data-platform/v1/sources?status=all" '
        b'hx-target="#source-crud-region" hx-swap="outerHTML" hx-disabled-elt="this"'
        in response.data
    )
    assert b"hx-put=" not in response.data
    assert b"/api/data-platform/v1/sources" not in response.data
    assert response.headers["X-Request-ID"] == "fragment-list-request"


def test_source_list_groups_registered_defaults_and_keeps_custom_names() -> None:
    def database(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "items": [
                    _source(name="G-NAF Open NSW", adapter_key="gnaf-bulk"),
                    _source(name="Team sales source", adapter_key="psi-bulk"),
                ]
            },
        )

    response = _client(database).get("/fragments/data-platform/v1/sources?status=all")

    assert response.status_code == 200
    assert b"Foundational property data" in response.data
    assert b"G-NAF addresses" in response.data
    assert b"Foundational address identity and location" in response.data
    assert b"Team sales source" in response.data


def test_source_groups_have_unique_accessible_names_and_bounded_paging() -> None:
    observed_query: dict[str, str] = {}

    def database(request: httpx.Request) -> httpx.Response:
        observed_query.update(dict(request.url.params))
        return httpx.Response(
            200,
            json={
                "items": [
                    _source(name="G-NAF Open NSW", adapter_key="gnaf-bulk"),
                    _source(
                        name="ABS All groups CPI Sydney and Australia", adapter_key="abs-cpi-source"
                    ),
                ],
                "count": 2,
                "limit": 100,
                "offset": 100,
                "next_offset": 200,
            },
        )

    response = _client(database).get(
        "/fragments/data-platform/v1/sources?q=NSW%20data&status=all&offset=100"
    )

    assert response.status_code == 200
    assert observed_query == {"limit": "100", "offset": "100", "q": "NSW data"}
    assert b'aria-label="Foundational property data data sources"' in response.data
    assert (
        b'<caption class="visually-hidden">Economic context data sources</caption>' in response.data
    )
    assert b"Showing 101\xe2\x80\x93102" in response.data
    assert (
        b'hx-get="/fragments/data-platform/v1/sources?q=NSW+data&amp;status=all"' in response.data
    )
    assert (
        b'hx-get="/fragments/data-platform/v1/sources?q=NSW+data&amp;status=all&amp;offset=200"'
        in response.data
    )


def test_source_page_offset_is_bounded() -> None:
    response = _client(lambda _: httpx.Response(500)).get(
        "/fragments/data-platform/v1/sources?offset=1000001"
    )

    assert response.status_code == 422
    assert b"Page offset must be between 0 and 1000000" in response.data


def test_catalogue_presentation_endpoint_is_read_only_and_bounded() -> None:
    client = _client(lambda _: httpx.Response(500))

    response = client.get("/api/data-platform/v1/catalogue-presentation")
    invalid = client.get("/api/data-platform/v1/catalogue-presentation?status=ready")

    assert response.status_code == 200
    assert response.get_json()["schema_version"] == "propertyscope.catalogue-presentation.v1"
    assert len(response.get_json()["groups"]) == 6
    assert len(response.get_json()["datasets"]) == 16
    assert invalid.status_code == 422


def test_create_and_edit_form_fragments_are_populated_without_browser_domain_logic() -> None:
    def database(request: httpx.Request) -> httpx.Response:
        assert request.url.path == f"/internal/data-platform/v1/sources/{SOURCE_ID}"
        return httpx.Response(
            200,
            json={"source": _source(name="Source <unsafe>", notes='Keep "quoted" text')},
        )

    client = _client(database)
    create = client.get("/fragments/data-platform/v1/sources/new")
    edit = client.get(f"/fragments/data-platform/v1/sources/{SOURCE_ID}/edit")

    assert create.status_code == 200
    assert b'data-source-mode="create"' in create.data
    assert b'hx-post="/fragments/data-platform/v1/sources"' in create.data
    assert b"[&#34;feature-1&#34;]" in create.data
    assert edit.status_code == 200
    assert b'data-source-mode="edit"' in edit.data
    assert b'value="3"' in edit.data
    assert b"Source &lt;unsafe&gt;" in edit.data
    assert b"Keep &#34;quoted&#34; text" in edit.data


def test_invalid_create_retains_values_and_returns_field_errors_for_htmx_swap() -> None:
    response = _client(lambda _: httpx.Response(500)).post(
        "/fragments/data-platform/v1/sources",
        data=_form(name="<unsafe retained>", target_features="not-json"),
    )

    assert response.status_code == 422
    assert response.headers["HX-Retarget"] == "#entity-form"
    assert response.headers["HX-Reswap"] == "innerHTML"
    assert b"&lt;unsafe retained&gt;" in response.data
    assert b"Research area keys must be a non-empty JSON list" in response.data
    assert b'aria-invalid="true"' in response.data


def test_valid_create_reuses_private_store_boundary_and_returns_refreshed_region() -> None:
    calls: list[tuple[str, str, dict[str, Any] | None]] = []

    def database(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else None
        calls.append((request.method, request.url.path, body))
        assert request.headers["X-Request-ID"] == "create-source-request"
        assert request.headers["Idempotency-Key"] == "source-create-1"
        if request.method == "POST":
            return httpx.Response(201, json={"source": _source(name="Created source")})
        return httpx.Response(200, json={"items": [_source(name="Created source")]})

    response = _client(database).post(
        "/fragments/data-platform/v1/sources",
        data=_form(),
        headers={"X-Request-ID": "create-source-request", "Idempotency-Key": "source-create-1"},
    )

    assert response.status_code == 201
    assert b"Created source was created" in response.data
    assert response.headers["HX-Trigger-After-Swap"]
    assert [item[:2] for item in calls] == [
        ("POST", "/internal/data-platform/v1/sources"),
        ("GET", "/internal/data-platform/v1/sources"),
    ]
    assert calls[0][2] is not None
    assert calls[0][2]["target_features"] == ["feature-1"]


def test_valid_update_forwards_version_and_refreshes_the_region() -> None:
    calls: list[tuple[str, str, dict[str, Any] | None]] = []

    def database(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else None
        calls.append((request.method, request.url.path, body))
        assert request.headers["X-Request-ID"] == "update-source-request"
        assert request.headers["Idempotency-Key"] == "source-update-1"
        if request.method == "PUT":
            return httpx.Response(200, json={"source": _source(name="Updated source", version=4)})
        return httpx.Response(200, json={"items": [_source(name="Updated source", version=4)]})

    response = _client(database).put(
        f"/fragments/data-platform/v1/sources/{SOURCE_ID}",
        data=_form(name="Updated source", version="3"),
        headers={
            "X-Request-ID": "update-source-request",
            "Idempotency-Key": "source-update-1",
        },
    )

    assert response.status_code == 200
    assert b"Updated source was updated" in response.data
    assert [item[:2] for item in calls] == [
        ("PUT", f"/internal/data-platform/v1/sources/{SOURCE_ID}"),
        ("GET", "/internal/data-platform/v1/sources"),
    ]
    assert calls[0][2] is not None
    assert calls[0][2]["version"] == 3


def test_stale_update_returns_conflict_fragment_with_submitted_values() -> None:
    def database(request: httpx.Request) -> httpx.Response:
        assert request.method == "PUT"
        return httpx.Response(
            409,
            json={"detail": "source version does not match", "request_id": "conflict-request"},
            headers={"content-type": "application/problem+json"},
        )

    response = _client(database).put(
        f"/fragments/data-platform/v1/sources/{SOURCE_ID}",
        data=_form(name="Retained conflict value", version="2"),
    )

    assert response.status_code == 409
    assert response.headers["HX-Retarget"] == "#entity-form"
    assert b"Retained conflict value" in response.data
    assert b"source version does not match" in response.data
    assert b'hx-put="/fragments/data-platform/v1/sources/' in response.data


def test_delete_confirmation_and_successful_delete_refresh_the_list() -> None:
    calls: list[str] = []

    def database(request: httpx.Request) -> httpx.Response:
        calls.append(f"{request.method} {request.url.path}")
        if request.method == "GET" and request.url.path.endswith(SOURCE_ID) and len(calls) == 1:
            return httpx.Response(200, json={"source": _source()})
        if request.method == "DELETE":
            return httpx.Response(204)
        return httpx.Response(200, json={"items": []})

    client = _client(database)
    confirmation = client.get(
        f"/fragments/data-platform/v1/sources/{SOURCE_ID}/delete-confirmation"
    )
    assert confirmation.status_code == 200
    assert b'hx-delete="/fragments/data-platform/v1/sources/' in confirmation.data
    assert b"Delete definition" in confirmation.data

    deleted = client.delete(f"/fragments/data-platform/v1/sources/{SOURCE_ID}")
    assert deleted.status_code == 200
    assert b"source definition was deleted" in deleted.data.lower()
    assert f"DELETE /internal/data-platform/v1/sources/{SOURCE_ID}" in calls


def test_json_source_api_remains_a_json_proxy() -> None:
    def database(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"items": [_source()]})

    response = _client(database).get("/api/data-platform/v1/sources")

    assert response.status_code == 200
    assert response.content_type == "application/json"
    assert response.get_json()["items"][0]["id"] == SOURCE_ID


def test_not_found_and_dependency_failure_fragments_are_safe_and_retryable() -> None:
    missing = _client(
        lambda _: httpx.Response(
            404,
            json={"detail": "Source does not exist", "private_token": "must-not-leak"},
        )
    ).get(f"/fragments/data-platform/v1/sources/{SOURCE_ID}")

    def unavailable(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("database host and token must-not-leak", request=request)

    failed = _client(unavailable).get("/fragments/data-platform/v1/sources")

    assert missing.status_code == 404
    assert missing.headers["HX-Retarget"] == "#source-crud-region"
    assert b"Source does not exist" in missing.data
    assert b"must-not-leak" not in missing.data
    assert failed.status_code == 503
    assert failed.headers["HX-Retarget"] == "#source-crud-region"
    assert b"temporarily unavailable" in failed.data
    assert b"Retry" in failed.data
    assert b"database host" not in failed.data
