"""Fakes for the cloud deployment tools and the real evidence documents they produce.

``FakeEdge`` answers the public routes ``scripts/cloud_smoke.py`` calls (pages, health, each
feature's CRUD collection and the AI health projection). ``smoke_document`` runs the real
``cloud_smoke.Smoke`` against it and serialises the result with the real ``build_document``.
``release_gate_document`` and ``image_build_document`` do the same for
``scripts/verify_release_gate.py`` and ``scripts/validate_release_images.py`` with fake ``gh`` and
``docker`` answers. The review fixtures therefore use exactly the shapes the deployment workflow
writes, and a change to a producer shows up in the review tests. No network, gh or Docker.
"""

from __future__ import annotations

import base64
import itertools
import json
import re
import subprocess
from collections.abc import Callable, Iterator, Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

import httpx
from scripts import cloud_smoke, validate_release_images, verify_release_gate

# collection -> (response wrapper key or None, DELETE status)
COLLECTIONS: dict[str, tuple[str | None, int]] = {
    "/api/data-platform/v1/sources": ("source", 204),
    "/api/market-intelligence/v1/market-cases": (None, 200),
    "/api/suburb-analytics/v1/suburb-comparisons": ("comparison", 200),
    "/api/due-diligence/v1/site-reviews": (None, 200),
    "/api/buyer-workspaces/v1/buyer-cases": (None, 200),
}
STARTED_AT = datetime(2026, 10, 20, 3, 14, 0, tzinfo=UTC)
FINISHED_AT = datetime(2026, 10, 20, 3, 15, 0, tzinfo=UTC)


class FakeEdge:
    """A small stateful stand-in for the PropertyScope edge with versioned records."""

    def __init__(
        self,
        *,
        ai: str = "disabled",
        fail_create: str | None = None,
        site_login: tuple[str, str] | None = None,
        enforce_site_login: bool = True,
    ) -> None:
        self.ai = ai
        self.fail_create = fail_create
        # (user, password) of the Caddy site-wide login; None: the edge sees no credentials.
        self.site_login = site_login
        self.enforce_site_login = enforce_site_login
        self.store: dict[str, dict[str, dict[str, Any]]] = {path: {} for path in COLLECTIONS}
        self.requests: list[tuple[str, str]] = []
        self.anonymous: list[str] = []
        self._ids: Iterator[int] = itertools.count(1)

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        self.requests.append((request.method, path))
        assert request.headers["X-Request-ID"].startswith("cloud-smoke-")
        authorization = request.headers.get("authorization")
        if self.site_login is None:
            assert authorization is None
        elif authorization is None:
            self.anonymous.append(path)
        if self.site_login is not None and self.enforce_site_login and path != "/healthz":
            expected = base64.b64encode(":".join(self.site_login).encode()).decode()
            if authorization != f"Basic {expected}":
                return httpx.Response(
                    401, headers={"www-authenticate": 'Basic realm="PropertyScope"'}
                )
        if request.method == "GET" and (path == "/" or path.startswith("/features/")):
            return httpx.Response(
                200,
                text="<html><title>PropertyScope NSW</title></html>",
                headers={"content-type": "text/html; charset=utf-8"},
            )
        if path == "/healthz":
            return httpx.Response(200, text="ok\n")
        if path == cloud_smoke.AI_HEALTH_PATH:
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
            response = self._collection(request, collection, wrapper, delete_status)
            if response is not None:
                return response
        return httpx.Response(404, json={"code": "route_not_found"})

    def _collection(
        self, request: httpx.Request, collection: str, wrapper: str | None, delete_status: int
    ) -> httpx.Response | None:
        items = self.store[collection]
        path = request.url.path
        if path == collection and request.method == "POST":
            if self.fail_create == collection:
                return httpx.Response(422, json={"code": "invalid_request"})
            identifier = f"00000000-0000-4000-8000-{next(self._ids):012d}"
            items[identifier] = {"id": identifier, **json.loads(request.content), "version": 1}
            return httpx.Response(201, json=_wrap(wrapper, items[identifier]))
        match = re.fullmatch(re.escape(collection) + r"/([0-9a-f-]+)", path)
        if match is None:
            return None
        identifier = match.group(1)
        if identifier not in items:
            return httpx.Response(404, json={"code": "not_found"})
        if request.method == "GET":
            return httpx.Response(200, json=_wrap(wrapper, items[identifier]))
        if request.method == "PUT":
            body = json.loads(request.content)
            if body.get("version") != items[identifier]["version"]:
                return httpx.Response(409, json={"code": "version_conflict"})
            items[identifier] = {**body, "id": identifier, "version": body["version"] + 1}
            return httpx.Response(200, json=_wrap(wrapper, items[identifier]))
        if request.method == "DELETE":
            del items[identifier]
            return httpx.Response(delete_status)
        return httpx.Response(405, json={"code": "method_not_allowed"})


def _wrap(wrapper: str | None, value: dict[str, Any]) -> dict[str, Any]:
    return {wrapper: value} if wrapper else value


def run_smoke(
    edge: FakeEdge, *, expect_ai: bool = False, base_url: str = "https://edge.example"
) -> cloud_smoke.Smoke:
    """Run every smoke case against ``edge`` with deterministic names and timings."""
    names = itertools.count(1)
    with httpx.Client(transport=httpx.MockTransport(edge)) as client:
        smoke = cloud_smoke.Smoke(
            client,
            base_url=base_url,
            unique=lambda: f"{next(names):010d}",
            monotonic=lambda: 0.0,
        )
        smoke.cleanup_delay = 0
        smoke.run(cloud_smoke.load_features(), expect_ai=expect_ai)
    return smoke


def smoke_document(
    *,
    base_url: str,
    commit_sha: str,
    registry: str,
    edge: FakeEdge | None = None,
    image_tag: str | None = None,
) -> dict[str, Any]:
    """The cloud-smoke.json the workflow would write for a deployment of ``commit_sha``."""
    smoke = run_smoke(edge or FakeEdge(), base_url=base_url)
    identity = cloud_smoke.deployment_identity(
        commit_sha=commit_sha,
        image_tag=image_tag or commit_sha,
        registry=registry,
        services=cloud_smoke.azure_image_services(),
    )
    document = cloud_smoke.build_document(
        base_url=base_url,
        results=smoke.results,
        expect_ai=False,
        started_at=STARTED_AT,
        finished_at=FINISHED_AT,
        identity=identity,
        ai_state=smoke.ai_state,
    )
    return _as_file(document)


def _as_file(document: dict[str, Any]) -> dict[str, Any]:
    """Round-trip through JSON exactly as the file on disk would be read."""
    value = json.loads(json.dumps(document))
    assert isinstance(value, dict)
    return value


def green_gate_api(sha: str, repository: str) -> Callable[[str, str | None], Any]:
    """A ``gh api`` stand-in where every required workflow succeeded at ``sha``."""

    def api(path: str, jq: str | None = None) -> Any:
        prefix = f"repos/{repository}/actions/workflows/"
        assert path.startswith(prefix), path
        number = sum(map(ord, path[len(prefix) :].split("/")[0]))
        run_id = 37_000_000_000 + number
        return [
            {
                "id": run_id,
                "run_number": number,
                "run_attempt": 1,
                "head_sha": sha,
                "event": "push",
                "status": "completed",
                "conclusion": "success",
                "html_url": f"https://github.com/{repository}/actions/runs/{run_id}",
                "created_at": "2026-10-20T03:00:00Z",
            }
        ]

    return api


def release_gate_document(*, sha: str, repository: str) -> dict[str, Any]:
    """The release-gate.json the workflow's first job writes for an all-green commit."""
    gate = verify_release_gate.Gate(green_gate_api(sha, repository), repository, sha)
    verdicts = verify_release_gate.verify(gate, log=lambda _: None)
    return _as_file(verify_release_gate.build_document(gate, verdicts, checked_at=STARTED_AT))


class FakeDocker:
    """Answers the read-only docker commands of ``validate_release_images``."""

    def __init__(self, *, users: dict[str, str] | None = None, invalid: str | None = None):
        self.services: list[str] = list(cloud_smoke.azure_image_services())
        self.users = users or {}
        self.invalid = invalid
        self.calls: list[tuple[str, ...]] = []

    def __call__(
        self, arguments: Sequence[str], environment: Mapping[str, str]
    ) -> subprocess.CompletedProcess[str]:
        call = tuple(arguments)
        self.calls.append(call)
        if call[0] == "compose" and call[-1] == "--quiet":
            assert environment["ACR_LOGIN_SERVER"] == "validation.azurecr.io"
            failed = self.invalid is not None and self.invalid in call
            return subprocess.CompletedProcess(
                call, 1 if failed else 0, "", "service x: invalid\n" if failed else ""
            )
        if call[0] == "compose" and call[-1] == "--images":
            images = "".join(f"propertyscope/{name}:dev\r\n" for name in self.services)
            return subprocess.CompletedProcess(call, 0, images + "docker.io/library/caddy:2\n", "")
        if call[:2] == ("image", "inspect"):
            service = call[2].split("/")[1].split(":")[0]
            details = {
                "Id": f"sha256:{sum(map(ord, service)):064x}",
                "Size": 200_000_000,
                "Created": "2026-10-20T03:05:00Z",
                "Config": {"User": self.users.get(service, "propertyscope")},
            }
            return subprocess.CompletedProcess(call, 0, json.dumps([details]), "")
        raise AssertionError(f"unexpected docker call {call}")


def image_build_document(*, sha: str) -> dict[str, Any]:
    """The image-build.json the workflow's Docker build and validation job writes."""
    document = validate_release_images.validate(sha, runner=FakeDocker())
    return _as_file({**document, "checked_at": STARTED_AT.isoformat(timespec="seconds")})
