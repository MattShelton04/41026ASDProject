from __future__ import annotations

import httpx

from propertyscope_data_platform.app import create_app as create_backend_app
from propertyscope_data_platform.clients import AiModeClient, DataStoreClient


def test_backend_proxies_property_search_and_preserves_expected_negative() -> None:
    def database(request: httpx.Request) -> httpx.Response:
        assert request.headers["X-PropertyScope-Internal-Token"] == "secret"
        if request.url.path == "/health/ready":
            return httpx.Response(200, json={"status": "healthy"})
        assert request.url.params["state"] == "VIC"
        return httpx.Response(
            200,
            json={"items": [], "count": 0, "query": "10 Example Street", "supported": False},
        )

    store = DataStoreClient(
        "http://database", "secret", client=httpx.Client(transport=httpx.MockTransport(database))
    )
    app = create_backend_app(
        store_client=store,
        ai_mode_client=AiModeClient(
            "http://ai",
            client=httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(503))),
        ),
    )
    response = app.test_client().get(
        "/api/data-platform/v1/properties/search?q=10%20Example%20Street&state=VIC"
    )
    assert response.status_code == 200
    assert response.json["supported"] is False


def test_backend_protects_runner_and_publication() -> None:
    transport = httpx.MockTransport(lambda _: httpx.Response(500, json={"code": "unexpected"}))
    app = create_backend_app(
        store_client=DataStoreClient(
            "http://database", "secret", client=httpx.Client(transport=transport)
        ),
        ai_mode_client=AiModeClient("http://ai", client=httpx.Client(transport=transport)),
    )
    client = app.test_client()
    assert client.post("/internal/data-platform/v1/worker/tasks/claim", json={}).status_code == 401
    response = client.post(
        "/api/data-platform/v1/dataset-releases/60000000-0000-0000-0000-000000000011/publish",
        json={"version": 1, "comment": "reviewed", "approved": False},
    )
    assert response.status_code == 422
    assert response.content_type == "application/problem+json"


def test_ai_unavailable_does_not_break_readiness() -> None:
    def database(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": "healthy"})

    store = DataStoreClient(
        "http://database", "secret", client=httpx.Client(transport=httpx.MockTransport(database))
    )
    app = create_backend_app(
        store_client=store,
        ai_mode_client=AiModeClient(
            "http://ai",
            client=httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(503))),
        ),
    )
    response = app.test_client().get("/health/ready")
    assert response.status_code == 200
    assert response.json["dependencies"]["database"] is True
