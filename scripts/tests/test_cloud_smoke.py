"""Cloud smoke test against an in-memory edge (httpx.MockTransport); no network."""

from __future__ import annotations

import json
import re
import uuid
from pathlib import Path
from typing import Any

import httpx
import pytest
from scripts import cloud_smoke
from scripts.cloud_smoke import CRUD_CASES, Smoke, load_features, main

COLLECTIONS = {
    "/api/data-platform/v1/sources": ("source", 204),
    "/api/market-intelligence/v1/market-cases": (None, 200),
    "/api/suburb-analytics/v1/suburb-comparisons": ("comparison", 200),
    "/api/due-diligence/v1/site-reviews": (None, 200),
    "/api/buyer-workspaces/v1/buyer-cases": (None, 200),
}


class FakeEdge:
    """A small stateful stand-in for the PropertyScope edge."""

    def __init__(self, *, ai: str = "disabled", fail_create: str | None = None) -> None:
        self.ai = ai
        self.fail_create = fail_create
        self.store: dict[str, dict[str, dict[str, Any]]] = {path: {} for path in COLLECTIONS}
        self.requests: list[tuple[str, str]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        self.requests.append((request.method, path))
        assert request.headers["X-Request-ID"].startswith("cloud-smoke-")
        assert "authorization" not in request.headers
        if request.method == "GET" and (path == "/" or path.startswith("/features/")):
            return httpx.Response(
                200, text="<html><title>PropertyScope NSW</title></html>", headers=_html()
            )
        if path == "/healthz":
            return httpx.Response(200, text="ok\n")
        if path == "/api/shared-health/ai-mode":
            if self.ai == "disabled":
                return httpx.Response(503, json={"code": "ai_disabled", "status": 503})
            if self.ai == "available":
                return httpx.Response(200, json={"status": "healthy"})
            raise httpx.ConnectTimeout("timed out", request=request)
        if path.startswith("/api/shared-health/"):
            return httpx.Response(200, json={"status": "healthy"})
        if path.endswith("/validate"):
            return httpx.Response(200, json={"state": "verified"})
        if path.endswith("/properties/search"):
            return httpx.Response(200, json={"items": []})
        for collection, (wrapper, delete_status) in COLLECTIONS.items():
            items = self.store[collection]
            if path == collection and request.method == "POST":
                if self.fail_create == collection:
                    return httpx.Response(422, json={"code": "invalid_request"})
                body = json.loads(request.content)
                identifier = str(uuid.uuid4())
                items[identifier] = {"id": identifier, **body}
                return httpx.Response(201, json=_wrap(wrapper, items[identifier]))
            if match := re.fullmatch(re.escape(collection) + r"/([0-9a-f-]+)", path):
                identifier = match.group(1)
                if identifier not in items:
                    return httpx.Response(404, json={"code": "not_found"})
                if request.method == "GET":
                    return httpx.Response(200, json=_wrap(wrapper, items[identifier]))
                if request.method == "DELETE":
                    del items[identifier]
                    return httpx.Response(delete_status)
        return httpx.Response(404, json={"code": "route_not_found"})


def _html() -> dict[str, str]:
    return {"content-type": "text/html; charset=utf-8"}


def _wrap(wrapper: str | None, value: dict[str, Any]) -> dict[str, Any]:
    return {wrapper: value} if wrapper else value


def _run(edge: FakeEdge, *, expect_ai: bool = False) -> list[cloud_smoke.CheckResult]:
    with httpx.Client(transport=httpx.MockTransport(edge)) as client:
        smoke = Smoke(client, base_url="https://edge.example")
        return smoke.run(load_features(), expect_ai=expect_ai)


def test_every_enabled_feature_has_a_registered_crud_case() -> None:
    features = load_features()
    assert {feature.owner for feature in features} == {f"student-{n}" for n in range(1, 6)}
    for feature in features:
        assert feature.feature_key in CRUD_CASES
        assert CRUD_CASES[feature.feature_key]().owner == feature.owner
        assert feature.health_path == f"/api/shared-health/{feature.slug}"


def test_full_pass_creates_reads_deletes_and_leaves_nothing_behind() -> None:
    edge = FakeEdge()

    results = _run(edge)

    assert all(result.passed for result in results), [r for r in results if not r.passed]
    assert all(not items for items in edge.store.values())
    deletes = [path for method, path in edge.requests if method == "DELETE"]
    assert len(deletes) == 5
    crud = [result for result in results if result.category == "crud"]
    assert {result.owner for result in crud} == {f"student-{n}" for n in range(1, 6)}
    assert len(crud) == 20
    ai = results[-1]
    assert ai.owner == "shared" and ai.detail.startswith("disabled")


def test_failed_create_is_reported_and_owned_by_the_feature() -> None:
    edge = FakeEdge(fail_create="/api/suburb-analytics/v1/suburb-comparisons")

    results = _run(edge)

    failed = [result for result in results if not result.passed]
    assert len(failed) == 1
    assert failed[0].owner == "student-3"
    assert "invalid_request" in failed[0].detail


def test_cleanup_runs_even_when_the_read_back_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    edge = FakeEdge()
    original = edge.__call__

    def broken_read(request: httpx.Request) -> httpx.Response:
        if (
            request.method == "GET"
            and "/api/buyer-workspaces/v1/buyer-cases/" in request.url.path
            and edge.store["/api/buyer-workspaces/v1/buyer-cases"]
        ):
            raise httpx.ReadTimeout("slow", request=request)
        return original(request)

    with httpx.Client(transport=httpx.MockTransport(broken_read)) as client:
        results = Smoke(client, base_url="https://edge.example").run(
            load_features(), expect_ai=False
        )

    assert not edge.store["/api/buyer-workspaces/v1/buyer-cases"]
    failed = [result for result in results if not result.passed]
    assert [result.name for result in failed] == ["CRUD buyer case: request"]
    assert failed[0].owner == "student-5"
    assert any(result.name == "CRUD buyer case: delete" and result.passed for result in results)


@pytest.mark.parametrize(
    ("ai", "expect_ai", "passed"),
    [
        ("disabled", False, True),
        ("unreachable", False, True),
        ("available", False, False),
        ("available", True, True),
        ("disabled", True, False),
    ],
)
def test_ai_expectation(ai: str, expect_ai: bool, passed: bool) -> None:
    results = _run(FakeEdge(ai=ai), expect_ai=expect_ai)

    assert results[-1].category == "ai"
    assert results[-1].passed is passed


def test_main_writes_json_and_markdown_and_sets_the_exit_code(tmp_path: Path) -> None:
    status = main(
        ["--base-url", "https://edge.example/", "--output-dir", str(tmp_path)],
        transport=httpx.MockTransport(FakeEdge()),
    )

    assert status == 0
    document = json.loads((tmp_path / "cloud-smoke.json").read_text(encoding="utf-8"))
    assert document["passed"] is True
    assert document["base_url"] == "https://edge.example"
    assert document["summary"]["by_owner"]["student-1"]["failed"] == 0
    markdown = (tmp_path / "cloud-smoke.md").read_text(encoding="utf-8")
    assert "**PASSED**" in markdown
    assert "CRUD source definition: create" in markdown

    status = main(
        ["--base-url", "https://edge.example", "--output-dir", str(tmp_path)],
        transport=httpx.MockTransport(FakeEdge(ai="available")),
    )
    assert status == 1


def test_main_rejects_a_base_url_without_a_scheme(tmp_path: Path) -> None:
    assert main(["--base-url", "edge.example", "--output-dir", str(tmp_path)]) == 2
