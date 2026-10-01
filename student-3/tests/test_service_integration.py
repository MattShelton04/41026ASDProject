"""Exercise the enabled WSGI services over real loopback HTTP without Docker or AI."""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from threading import Thread
from typing import Any
from wsgiref.simple_server import make_server

import pytest

from propertyscope_suburb_analytics.app import FEATURE_KEY, TOOL_ALLOWLIST, create_app
from propertyscope_suburb_analytics.clients import HttpClient, ServiceError
from propertyscope_suburb_store.app import create_app as create_store
from propertyscope_suburb_store.repository import Repository

BASE = "/api/suburb-analytics/v1"


@contextmanager
def serve(app: Any) -> Iterator[HttpClient]:
    with make_server("127.0.0.1", 0, app) as server:
        thread = Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
        thread.start()
        try:
            yield HttpClient(f"http://127.0.0.1:{server.server_port}")
        finally:
            server.shutdown()
            thread.join(timeout=2)


def optional_service(environ: dict[str, Any], start: Any) -> list[bytes]:
    path = environ["PATH_INFO"]
    if path.endswith("/map-context"):
        result = {"latitude": -33.815, "longitude": 151.001}
    elif path == "/api/v1/agent-runs/run-1":
        result = {
            "run": {
                "id": "run-1",
                "feature_key": FEATURE_KEY,
                "tool_allowlist": list(TOOL_ALLOWLIST),
                "status": "succeeded",
            }
        }
    elif path.endswith("/events"):
        result = {"items": []}
    else:
        result = {"id": "run-1", "status": "queued", "items": []}
    start("200 OK", [("Content-Type", "application/json")])
    return [json.dumps(result).encode()]


@pytest.fixture
def services(tmp_path: Path) -> Iterator[tuple[HttpClient, HttpClient]]:
    repository = Repository(tmp_path / "suburbs.sqlite3")
    with (
        serve(create_store(repository)) as store,
        serve(optional_service) as optional,
        serve(create_app(store, optional, optional)) as backend,
    ):
        yield backend, store


@pytest.mark.parametrize(
    "path,key",
    [
        ("/health/ready", "checks"),
        ("/health/live", "checks"),
        (f"{BASE}/suburbs", "items"),
        (f"{BASE}/suburbs?q=Parra&lga=Parramatta&amenity=school&sort=locality", "items"),
        (f"{BASE}/suburbs?sort=population&limit=2&cursor=1", "items"),
        (f"{BASE}/suburbs/NSW/Parramatta", "suburb"),
        (f"{BASE}/suburbs/NSW/Parramatta/places?type=school&limit=2", "items"),
        (f"{BASE}/suburbs/NSW/Parramatta/crime-series?measure=rate&offence=person", "items"),
        (f"{BASE}/suburbs/NSW/Parramatta/area-series?metric=population_density", "items"),
        (f"{BASE}/properties/example-property/nearby-places", "distance_label"),
        (f"{BASE}/crime/compare?localities=Parramatta,Newtown&measure=count", "series"),
        (f"{BASE}/crime/methodology", "zero_missing_rule"),
        (f"{BASE}/assistant/capabilities", "tools"),
        (f"{BASE}/assistant/turns/run-1", "run"),
        (f"{BASE}/assistant/turns/run-1/events?after=0", "items"),
    ],
)
def test_public_read_routes_cross_the_http_boundary(
    services: tuple[HttpClient, HttpClient], path: str, key: str
) -> None:
    assert key in services[0].request("GET", path)


def test_comparison_crud_persists_through_the_database_api(
    services: tuple[HttpClient, HttpClient],
) -> None:
    backend, store = services
    payload = {
        "name": "Integration comparison",
        "localities": ["Parramatta", "Newtown"],
        "from_month": "2026-01",
        "to_month": "2026-06",
        "measure": "count",
    }
    created = backend.request("POST", f"{BASE}/suburb-comparisons", payload)["comparison"]
    path = f"{BASE}/suburb-comparisons/{created['id']}"
    assert backend.request("GET", path)["comparison"]["name"] == payload["name"]
    assert (
        store.request("GET", f"/internal/v1/suburb-comparisons/{created['id']}")["comparison"][
            "version"
        ]
        == 1
    )
    assert any(
        item["id"] == created["id"]
        for item in backend.request("GET", f"{BASE}/suburb-comparisons")["items"]
    )
    updated = backend.request("PUT", path, payload | {"version": 1, "notes": "Reviewed"})
    assert updated["comparison"]["version"] == 2
    with pytest.raises(ServiceError) as error:
        backend.request("PUT", path, payload | {"version": 1})
    assert error.value.status == 409
    with pytest.raises(ServiceError) as error:
        backend.request("POST", f"{path}/agent-runs", {})
    assert error.value.status == 404
    assert backend.request("DELETE", path) == {"deleted": True}
    for method in ("GET", "DELETE", "PUT"):
        with pytest.raises(ServiceError) as error:
            backend.request(method, path, payload | {"version": 2})
        assert error.value.status == 404


@pytest.mark.parametrize(
    "tool,payload,key",
    [
        ("suburb.published-context.v1", {"locality": "Parramatta"}, "status"),
        ("suburb.snapshot.v1", {"locality": "Parramatta"}, "suburb"),
        ("crime.methodology.v1", {}, "rate_method"),
        (
            "crime.compare.v1",
            {"localities": ["Parramatta", "Newtown"], "measure": "rate"},
            "series",
        ),
    ],
)
def test_registered_tools_return_evidence(
    services: tuple[HttpClient, HttpClient], tool: str, payload: dict[str, Any], key: str
) -> None:
    assert key in services[0].request("POST", f"{BASE}/tools/{tool}", payload)


@pytest.mark.parametrize(
    "path,status",
    [
        ("/not-a-route", 404),
        (f"{BASE}/suburbs/NSW/Unknown", 404),
        (f"{BASE}/suburbs/NSW/Parramatta/crime-series?measure=mixed", 422),
        (f"{BASE}/suburbs/NSW/Parramatta/crime-series?offence=unknown", 422),
        (f"{BASE}/suburbs/NSW/Parramatta/area-series?metric=unknown", 422),
    ],
)
def test_public_errors_preserve_http_status(
    services: tuple[HttpClient, HttpClient], path: str, status: int
) -> None:
    with pytest.raises(ServiceError) as error:
        services[0].request("GET", path)
    assert error.value.status == status


def test_assistant_uses_the_configured_http_service(
    services: tuple[HttpClient, HttpClient],
) -> None:
    backend, _ = services
    assert (
        backend.request("POST", f"{BASE}/assistant/turns", {"message": "Show evidence"})["id"]
        == "run-1"
    )
    assert backend.request("POST", f"{BASE}/assistant/turns/run-1/cancel", {})["id"] == "run-1"
