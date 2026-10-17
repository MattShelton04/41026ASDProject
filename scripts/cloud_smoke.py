"""Public smoke test for a deployed PropertyScope stack (Release 2, R2-44).

Run it against the Azure edge after every deployment, or against a local stack:

    uv run python scripts/cloud_smoke.py --base-url https://<label>.australiaeast.cloudapp.azure.com
    uv run python scripts/cloud_smoke.py --base-url http://localhost:5100 --output-dir out/

It checks, only through the public edge:

- the Shared home page ``/`` and the edge liveness route ``/healthz``;
- every enabled feature's frontend route and its health projection;
- one self-cleaning CRUD case per feature, owned by that feature: create a uniquely named
  resource, read it back, update it where the feature registers an update (Feature 1), delete it
  and confirm it is gone;
- that the shared AI tier reports itself disabled (the cloud baseline), or with ``--expect-ai``
  that it is reachable (bonus tiers).

Results are written as ``cloud-smoke.json`` and ``cloud-smoke.md``. Every CRUD case deletes what
it created, even when a later step fails. The script sends no credentials and never calls an AI
route that would create a run.

The JSON document is the contract the Cloud Deployment Report Review reads
(``scripts/devtools/review/cloud.py``; documented in docs/release-2/review-modes.md):
``schema_version`` 2, ``base_url``, ``commit_sha``, ``image_tag``, ``registry``, ``images``
(service -> reference), ``images_source``, ``ai_enabled`` (observed by the AI check: ``false``
only for an explicit ``ai_disabled`` answer), ``ai_state``, ``started_at``/``finished_at``,
``passed``, ``summary`` and ``checks`` (``name``, ``owner``, ``category``, ``operation``,
``passed``, ``detail``, ``method``, ``path``, ``status_code``, ``duration_ms``). The deployment
identity comes from ``--commit-sha``/``--image-tag``/``--registry``/``--image`` or, as
``deploy.sh smoke`` runs it, from ``PROPERTYSCOPE_DEPLOY_SHA`` (or ``PROPERTYSCOPE_GIT_SHA``),
``IMAGE_TAG`` and ``ACR_LOGIN_SERVER`` (``deploy.sh smoke`` passes all three as options). The
image list is, in order of preference: ``--image`` arguments; the images the VM reported running
(``--vm-log vm-deploy.log``, its ``PROPERTYSCOPE_IMAGES`` line, with registry digests; ``deploy.sh
smoke`` passes it after a deploy); or every ``${IMAGE_TAG}`` image in ``docker-compose.azure.yml``.
``images_source`` says which one was used.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import uuid
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
ENABLED_FEATURES = REPOSITORY_ROOT / "deployment" / "enabled-features.v1.json"
SHARED_OWNER = "shared"
SMOKE_PREFIX = "cloud-smoke"
# Feature 1's seeded showcase property (11 Example Street); used when search finds nothing.
SHOWCASE_PROPERTY_REF = "a0000000-0000-0000-0000-000000000001"
SHOWCASE_ADDRESS = "11 Example Street, Sydney NSW 2000"
PROPERTY_QUERIES = ("11 Example Street", "1 Fixture Street")
AI_HEALTH_PATH = "/api/shared-health/ai-mode"
SCHEMA_VERSION = 2
SMOKE_JSON = "cloud-smoke.json"
SMOKE_MARKDOWN = "cloud-smoke.md"
AZURE_COMPOSE_FILE = REPOSITORY_ROOT / "docker-compose.azure.yml"
AZURE_IMAGE = re.compile(r"/propertyscope/([a-z0-9][a-z0-9-]*):\$\{IMAGE_TAG\b")
COMMIT_SHA = re.compile(r"[0-9a-f]{40}")
IMAGE_TAG = re.compile(r"[A-Za-z0-9_.-]{1,128}")
REGISTRY = re.compile(r"[A-Za-z0-9.-]{1,253}(:[0-9]{1,5})?")
SERVICE_NAME = re.compile(r"[a-z0-9][a-z0-9-]*")
IMAGE_REFERENCE = re.compile(r"[A-Za-z0-9./:@_-]{1,512}")
# propertyscope-vm.sh prints the images its running containers use (with registry digests).
VM_IMAGES_LINE = re.compile(r"^PROPERTYSCOPE_IMAGES=(\{.*\})\s*$", re.MULTILINE)
VM_IMAGES_SOURCE = "the VM (docker compose ps, PROPERTYSCOPE_IMAGES in vm-deploy.log)"
# What the Feature 1 update writes and then reads back.
UPDATED_NOTES = "Updated by scripts/cloud_smoke.py; deleted at the end of the case."


@dataclass(frozen=True, slots=True)
class CheckResult:
    """One observation, attributed to the feature (or the shared platform) that owns it."""

    name: str
    owner: str
    category: str
    passed: bool
    detail: str
    method: str = "GET"
    path: str = ""
    status_code: int | None = None
    duration_ms: int = 0
    # CRUD step: create, read, update, confirm-update, delete, confirm-deleted, cleanup-retry,
    # request (a transport failure) or missing-case; empty for page, health and AI checks.
    operation: str = ""


@dataclass(frozen=True, slots=True)
class FeatureRoutes:
    """The public routes one enabled feature publishes through the edge."""

    feature_key: str
    owner: str
    slug: str
    frontend_path: str
    api_prefix: str

    @property
    def health_path(self) -> str:
        return f"/api/shared-health/{self.slug}"


@dataclass(slots=True)
class CrudCase:
    """A create -> read -> [update] -> delete -> confirm-gone cycle on one feature resource.

    ``update`` builds the PUT body from the create body and the record as read back; the case
    then checks that ``update_field`` changed in the PUT response and in a fresh read.
    """

    owner: str
    resource: str
    collection: str
    body: Callable[[Smoke, str], dict[str, Any]]
    extract: Callable[[dict[str, Any]], dict[str, Any]]
    name_field: str
    delete_statuses: tuple[int, ...] = (200, 204)
    update: Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]] | None = None
    update_field: str = ""
    update_statuses: tuple[int, ...] = (200,)
    created_id: str | None = field(default=None)


@dataclass(frozen=True, slots=True)
class DeploymentIdentity:
    """What was deployed, as the deployment told the smoke test (it cannot see the VM)."""

    commit_sha: str | None = None
    image_tag: str | None = None
    registry: str | None = None
    images: Mapping[str, str] = field(default_factory=dict)
    images_source: str = "not recorded"


def load_features(path: Path = ENABLED_FEATURES) -> tuple[FeatureRoutes, ...]:
    """Read the generated enabled-feature projection (the edge's own routing source)."""
    projection = json.loads(path.read_text(encoding="utf-8"))
    features: list[FeatureRoutes] = []
    for feature in projection.get("features", []):
        if not isinstance(feature, dict) or not feature.get("enabled", True):
            continue
        routes = {route["kind"]: route["path"] for route in feature.get("routes", [])}
        frontend, backend = routes.get("frontend"), routes.get("backend")
        if not isinstance(frontend, str) or not isinstance(backend, str):
            continue
        slug = backend.strip("/").split("/")[1]
        features.append(
            FeatureRoutes(
                feature_key=str(feature["feature_key"]),
                owner=str(feature["owner"]),
                slug=slug,
                frontend_path=frontend,
                api_prefix=backend.rstrip("/"),
            )
        )
    return tuple(features)


def azure_image_services(path: Path = AZURE_COMPOSE_FILE) -> tuple[str, ...]:
    """Services whose Azure image is tagged ``${IMAGE_TAG}`` (third-party mirrors excluded)."""
    if not path.is_file():
        return ()
    return tuple(sorted(set(AZURE_IMAGE.findall(path.read_text(encoding="utf-8")))))


def vm_images(text: str) -> dict[str, str]:
    """The last service -> image object the VM printed (``PROPERTYSCOPE_IMAGES=``), or ``{}``.

    run-command returns only the tail of the output, so a cut-off line is ignored rather than
    trusted in part.
    """
    for candidate in reversed(VM_IMAGES_LINE.findall(text)):
        try:
            value = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if (
            isinstance(value, dict)
            and value
            and all(isinstance(key, str) and isinstance(item, str) for key, item in value.items())
        ):
            return dict(value)
    return {}


def deployment_identity(
    *,
    commit_sha: str | None,
    image_tag: str | None,
    registry: str | None,
    images: Mapping[str, str] | None = None,
    services: Sequence[str] = (),
    observed: Mapping[str, str] | None = None,
) -> DeploymentIdentity:
    """Validate the deployment identity and derive the image references from the tag.

    Explicit ``images`` win, then the images the VM reported running (``observed``), then
    references derived from the tag for every ``services`` entry.
    """
    commit = (commit_sha or "").strip().lower() or None
    if commit is not None and not COMMIT_SHA.fullmatch(commit):
        raise ValueError("the commit SHA must be 40 hexadecimal characters")
    tag = (image_tag or "").strip() or None
    if tag is not None and not IMAGE_TAG.fullmatch(tag):
        raise ValueError("the image tag must match [A-Za-z0-9_.-]{1,128}")
    host = (registry or "").strip().rstrip("/") or None
    if host is not None and not REGISTRY.fullmatch(host):
        raise ValueError("the registry must be a host name, e.g. example.azurecr.io")
    explicit = dict(images or {})
    reported = dict(observed or {})
    for service, reference in (*explicit.items(), *reported.items()):
        if not SERVICE_NAME.fullmatch(service) or not IMAGE_REFERENCE.fullmatch(reference):
            raise ValueError(f"invalid image reference {service}={reference}")
    if explicit:
        return DeploymentIdentity(commit, tag, host, explicit, "--image arguments")
    if reported:
        return DeploymentIdentity(commit, tag, host, reported, VM_IMAGES_SOURCE)
    if tag is not None and services:
        prefix = f"{host}/" if host else ""
        derived = {service: f"{prefix}propertyscope/{service}:{tag}" for service in services}
        return DeploymentIdentity(
            commit, tag, host, derived, "docker-compose.azure.yml with IMAGE_TAG"
        )
    return DeploymentIdentity(commit, tag, host)


def _bare(payload: dict[str, Any]) -> dict[str, Any]:
    return payload


def _wrapped(key: str) -> Callable[[dict[str, Any]], dict[str, Any]]:
    def extract(payload: dict[str, Any]) -> dict[str, Any]:
        value = payload.get(key)
        if not isinstance(value, dict):
            raise ValueError(f"response has no '{key}' object")
        return value

    return extract


def _feature_1_source(_smoke: Smoke, name: str) -> dict[str, Any]:
    return {
        "name": name,
        "publisher": "PropertyScope cloud smoke test",
        "source_url": "https://example.com/propertyscope-smoke",
        "adapter_key": "fixture-snapshot",
        "cadence": "monthly",
        "licence_id": "smoke-test-only",
        "licence_url": "https://example.com/propertyscope-smoke/licence",
        "redistribution_policy": "metadata-only",
        "target_features": ["feature-1"],
        "status": "draft",
        "notes": "Created and deleted by scripts/cloud_smoke.py.",
    }


def _feature_1_source_update(body: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    """Feature 1 ``SourceDefinitionUpdate``: the full definition plus the version read back."""
    version = current.get("version")
    if not isinstance(version, int) or isinstance(version, bool):
        raise ValueError("the read-back source definition has no integer version")
    return {**body, "notes": UPDATED_NOTES, "version": version}


def _feature_2_case(smoke: Smoke, name: str) -> dict[str, Any]:
    reference, address = smoke.property_reference("/api/market-intelligence/v1")
    return {
        "name": name,
        "property_ref": reference,
        "address_display": address,
        "date_from": "2024-01-01",
        "date_to": "2025-12-31",
        "notes": "Created and deleted by scripts/cloud_smoke.py.",
    }


def _feature_3_comparison(_smoke: Smoke, name: str) -> dict[str, Any]:
    return {
        "name": name,
        "localities": ["Parramatta", "Newtown"],
        "from_month": "2025-01",
        "to_month": "2025-06",
        "measure": "count",
    }


def _feature_4_review(smoke: Smoke, name: str) -> dict[str, Any]:
    reference, address = smoke.property_reference("/api/due-diligence/v1")
    return {"property_ref": reference, "address_display": address, "title": name}


def _feature_5_case(_smoke: Smoke, name: str) -> dict[str, Any]:
    return {"name": name}


# One case per feature, chosen from each slice's routes and contracts: every resource is created
# by its owner's public API, has no side effects outside that feature and is hard-deleted.
CRUD_CASES: Mapping[str, Callable[[], CrudCase]] = {
    "student-1-propertyscope-data-platform": lambda: CrudCase(
        owner="student-1",
        resource="source definition",
        collection="/api/data-platform/v1/sources",
        body=_feature_1_source,
        extract=_wrapped("source"),
        name_field="name",
        delete_statuses=(204,),
        update=_feature_1_source_update,
        update_field="notes",
    ),
    "student-2-market-intelligence": lambda: CrudCase(
        owner="student-2",
        resource="market case",
        collection="/api/market-intelligence/v1/market-cases",
        body=_feature_2_case,
        extract=_bare,
        name_field="name",
    ),
    "student-3-suburb-analytics": lambda: CrudCase(
        owner="student-3",
        resource="saved suburb comparison",
        collection="/api/suburb-analytics/v1/suburb-comparisons",
        body=_feature_3_comparison,
        extract=_wrapped("comparison"),
        name_field="name",
    ),
    "student-4-due-diligence": lambda: CrudCase(
        owner="student-4",
        resource="site review",
        collection="/api/due-diligence/v1/site-reviews",
        body=_feature_4_review,
        extract=_bare,
        name_field="title",
    ),
    "student-5-buyer-journey": lambda: CrudCase(
        owner="student-5",
        resource="buyer case",
        collection="/api/buyer-workspaces/v1/buyer-cases",
        body=_feature_5_case,
        extract=_bare,
        name_field="name",
    ),
}


class Smoke:
    """Runs every check against one base URL and records the results in order."""

    def __init__(
        self,
        client: httpx.Client,
        *,
        base_url: str,
        ai_timeout: float = 15.0,
        unique: Callable[[], str] | None = None,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.client = client
        self.base_url = base_url.rstrip("/")
        self.ai_timeout = ai_timeout
        self.cleanup_attempts = 3
        self.cleanup_delay = 2.0
        self.results: list[CheckResult] = []
        # What the AI check observed: disabled, available, unreachable; None when not checked.
        self.ai_state: str | None = None
        self._unique = unique or (lambda: uuid.uuid4().hex[:10])
        self._monotonic = monotonic
        self._property: tuple[str, str] | None = None

    # --- recording -------------------------------------------------------------------------

    def record(self, result: CheckResult) -> CheckResult:
        self.results.append(result)
        verdict = "PASS" if result.passed else "FAIL"
        print(f"{verdict} [{result.owner}] {result.name}: {result.detail}", flush=True)
        return result

    @contextmanager
    def timed(self) -> Iterator[Callable[[], int]]:
        started = self._monotonic()
        yield lambda: int((self._monotonic() - started) * 1000)

    def unique_name(self, kind: str) -> str:
        return f"{SMOKE_PREFIX}-{kind}-{self._unique()}"

    def request(
        self, method: str, path: str, *, timeout: float | None = None, **kwargs: Any
    ) -> httpx.Response:
        headers = {"X-Request-ID": f"{SMOKE_PREFIX}-{uuid.uuid4().hex[:16]}"}
        headers.update(kwargs.pop("headers", {}))
        return self.client.request(
            method,
            self.base_url + path,
            headers=headers,
            timeout=timeout if timeout is not None else httpx.USE_CLIENT_DEFAULT,
            **kwargs,
        )

    # --- page and health checks ------------------------------------------------------------

    def check_page(self, name: str, owner: str, path: str, *, marker: str | None = None) -> None:
        with self.timed() as elapsed:
            try:
                response = self.request("GET", path, follow_redirects=True)
            except httpx.HTTPError as exc:
                self.record(CheckResult(name, owner, "frontend", False, _error(exc), path=path))
                return
        content_type = response.headers.get("content-type", "")
        passed = response.status_code == 200 and "text/html" in content_type
        if passed and marker is not None:
            passed = marker in response.text
        detail = f"HTTP {response.status_code} {content_type.split(';')[0] or 'no content type'}"
        if marker is not None and response.status_code == 200 and marker not in response.text:
            detail += f"; page does not contain {marker!r}"
        self.record(
            CheckResult(
                name,
                owner,
                "frontend",
                passed,
                detail,
                path=path,
                status_code=response.status_code,
                duration_ms=elapsed(),
            )
        )

    def check_health(self, name: str, owner: str, path: str) -> None:
        with self.timed() as elapsed:
            try:
                response = self.request("GET", path)
            except httpx.HTTPError as exc:
                self.record(CheckResult(name, owner, "health", False, _error(exc), path=path))
                return
        status = "unknown"
        try:
            payload = response.json()
            if isinstance(payload, dict):
                status = str(payload.get("status", "unknown"))
        except ValueError:
            status = response.text.strip()[:40] or "empty body"
        passed = response.status_code == 200 and status in {"healthy", "ready", "ok", "degraded"}
        self.record(
            CheckResult(
                name,
                owner,
                "health",
                passed,
                f"HTTP {response.status_code}, status {status}",
                path=path,
                status_code=response.status_code,
                duration_ms=elapsed(),
            )
        )

    # --- CRUD ------------------------------------------------------------------------------

    def property_reference(self, feature_api: str) -> tuple[str, str]:
        """Pick a Feature 1 property the calling feature accepts (cached for the run)."""
        if self._property is not None:
            return self._property
        candidates: list[tuple[str, str]] = []
        for query in PROPERTY_QUERIES:
            try:
                response = self.request(
                    "GET",
                    "/api/data-platform/v1/properties/search",
                    params={"q": query, "state": "NSW", "limit": 1},
                )
                items = response.json().get("items", []) if response.status_code == 200 else []
            except (httpx.HTTPError, ValueError, AttributeError):
                items = []
            for item in items:
                reference, address = item.get("property_ref"), item.get("address_display")
                if isinstance(reference, str) and isinstance(address, str):
                    candidates.append((reference, address))
        candidates.append((SHOWCASE_PROPERTY_REF, SHOWCASE_ADDRESS))
        for reference, address in candidates:
            try:
                response = self.request("GET", f"{feature_api}/properties/{reference}/validate")
                state = response.json().get("state") if response.status_code == 200 else None
            except (httpx.HTTPError, ValueError, AttributeError):
                state = None
            # "unavailable" still lets the owning feature create the record (it labels it).
            if state != "not_found":
                self._property = (reference, address)
                return self._property
        raise ValueError("no Feature 1 property is available to reference")

    def run_crud(self, case: CrudCase) -> None:
        name = self.unique_name(case.owner)
        label = f"CRUD {case.resource}"
        try:
            self._crud_steps(case, name, label)
        except httpx.HTTPError as exc:
            self.record(
                CheckResult(
                    f"{label}: request",
                    case.owner,
                    "crud",
                    False,
                    _error(exc),
                    path=case.collection,
                    operation="request",
                )
            )
        finally:
            if case.created_id is not None:
                self._cleanup(case, label)

    def _crud_steps(self, case: CrudCase, name: str, label: str) -> None:
        try:
            body = case.body(self, name)
        except ValueError as exc:
            self.record(
                CheckResult(
                    f"{label}: create",
                    case.owner,
                    "crud",
                    False,
                    f"prerequisite failed: {exc}",
                    "POST",
                    case.collection,
                    operation="create",
                )
            )
            return
        body[case.name_field] = name
        with self.timed() as elapsed:
            response = self.request("POST", case.collection, json=body)
        created: dict[str, Any] = {}
        try:
            created = case.extract(response.json()) if response.status_code == 201 else {}
        except ValueError:
            created = {}
        identifier = created.get("id")
        if isinstance(identifier, str):
            case.created_id = identifier
        self.record(
            CheckResult(
                f"{label}: create",
                case.owner,
                "crud",
                response.status_code == 201 and case.created_id is not None,
                f"HTTP {response.status_code}"
                + (f", id {case.created_id}" if case.created_id else f": {_problem(response)}"),
                "POST",
                case.collection,
                response.status_code,
                elapsed(),
                operation="create",
            )
        )
        if case.created_id is None:
            return
        item = f"{case.collection}/{case.created_id}"
        with self.timed() as elapsed:
            response = self.request("GET", item)
        current = _extracted(case, response, (200,))
        read_name = current.get(case.name_field)
        read_ok = response.status_code == 200 and read_name == name
        self.record(
            CheckResult(
                f"{label}: read",
                case.owner,
                "crud",
                read_ok,
                f"HTTP {response.status_code}, {case.name_field} "
                + ("matches" if read_name == name else f"is {read_name!r}"),
                "GET",
                item,
                response.status_code,
                elapsed(),
                operation="read",
            )
        )
        if case.update is not None and read_ok:
            self._update_steps(case, case.update, body, current, label)

    def _update_steps(
        self,
        case: CrudCase,
        build: Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]],
        body: dict[str, Any],
        current: dict[str, Any],
        label: str,
    ) -> None:
        """PUT a changed field, then read the record again to prove the change persisted."""
        item = f"{case.collection}/{case.created_id}"
        try:
            update = build(dict(body), current)
        except ValueError as exc:
            self.record(
                CheckResult(
                    f"{label}: update",
                    case.owner,
                    "crud",
                    False,
                    f"prerequisite failed: {exc}",
                    "PUT",
                    item,
                    operation="update",
                )
            )
            return
        wanted = update.get(case.update_field)
        with self.timed() as elapsed:
            response = self.request("PUT", item, json=update)
        accepted = response.status_code in case.update_statuses
        updated = _extracted(case, response, case.update_statuses).get(case.update_field)
        changed = accepted and updated == wanted
        if changed:
            outcome = "changed"
        elif accepted:
            outcome = f"is {updated!r}"
        else:
            outcome = f"not changed: {_problem(response)}"
        self.record(
            CheckResult(
                f"{label}: update",
                case.owner,
                "crud",
                changed,
                f"HTTP {response.status_code}, {case.update_field} {outcome}",
                "PUT",
                item,
                response.status_code,
                elapsed(),
                operation="update",
            )
        )
        if not changed:
            return
        with self.timed() as elapsed:
            response = self.request("GET", item)
        persisted = _extracted(case, response, (200,)).get(case.update_field)
        self.record(
            CheckResult(
                f"{label}: confirm update",
                case.owner,
                "crud",
                response.status_code == 200 and persisted == wanted,
                f"HTTP {response.status_code}, {case.update_field} "
                + ("persisted" if persisted == wanted else f"is {persisted!r}"),
                "GET",
                item,
                response.status_code,
                elapsed(),
                operation="confirm-update",
            )
        )

    def _cleanup(self, case: CrudCase, label: str) -> None:
        item = f"{case.collection}/{case.created_id}"
        try:
            with self.timed() as elapsed:
                response = self.request("DELETE", item)
            deleted = response.status_code in case.delete_statuses
            self.record(
                CheckResult(
                    f"{label}: delete",
                    case.owner,
                    "crud",
                    deleted,
                    f"HTTP {response.status_code}" + ("" if deleted else f": {_problem(response)}"),
                    "DELETE",
                    item,
                    response.status_code,
                    elapsed(),
                    operation="delete",
                )
            )
            with self.timed() as elapsed:
                response = self.request("GET", item)
            self.record(
                CheckResult(
                    f"{label}: confirm deleted",
                    case.owner,
                    "crud",
                    response.status_code == 404,
                    f"HTTP {response.status_code} after delete",
                    "GET",
                    item,
                    response.status_code,
                    elapsed(),
                    operation="confirm-deleted",
                )
            )
            if response.status_code != 404:
                self._retry_cleanup(case, label, item)
        except httpx.HTTPError as exc:
            self.record(
                CheckResult(
                    f"{label}: delete",
                    case.owner,
                    "crud",
                    False,
                    f"{_error(exc)}; remove {item} manually",
                    "DELETE",
                    item,
                    operation="delete",
                )
            )

    def _retry_cleanup(self, case: CrudCase, label: str, item: str) -> None:
        """Never leave smoke data behind: retry a failed delete. The failure stays reported."""
        status: int | None = None
        for _attempt in range(self.cleanup_attempts):
            time.sleep(self.cleanup_delay)
            status = self.request("GET", item).status_code
            if status == 404:
                break
            status = self.request("DELETE", item).status_code
        self.record(
            CheckResult(
                f"{label}: cleanup retry",
                case.owner,
                "cleanup",
                status == 404 or status in case.delete_statuses,
                f"record {'removed' if status in (404, *case.delete_statuses) else 'still present'}"
                f" after retry (last HTTP {status}); the failure above is still reported",
                "DELETE",
                item,
                status,
                operation="cleanup-retry",
            )
        )

    # --- AI tier ---------------------------------------------------------------------------

    def check_ai(self, *, expect_ai: bool) -> None:
        """The cloud baseline keeps the AI tier off; the bonus tiers expect it reachable."""
        with self.timed() as elapsed:
            try:
                response: httpx.Response | None = self.request(
                    "GET", AI_HEALTH_PATH, timeout=self.ai_timeout
                )
            except httpx.HTTPError as exc:
                response = None
                failure = _error(exc)
        if response is None:
            state, status_code, detail = "unreachable", None, failure
        else:
            status_code = response.status_code
            code = _problem_code(response)
            if response.status_code == 503 and code == "ai_disabled":
                state = "disabled"
            elif response.status_code == 200:
                state = "available"
            else:
                state = "unreachable"
            detail = f"HTTP {response.status_code}" + (f", code {code}" if code else "")
        self.ai_state = state
        if expect_ai:
            passed = state == "available"
            name = "AI tier reachable (--expect-ai)"
        else:
            # The required baseline: explicitly disabled at the edge. An unreachable AI-mode on a
            # local stack also means no AI is served, but it is reported as not explicit.
            passed = state in {"disabled", "unreachable"}
            name = "AI tier disabled by default"
        self.record(
            CheckResult(
                name,
                SHARED_OWNER,
                "ai",
                passed,
                f"{state}: {detail}",
                path=AI_HEALTH_PATH,
                status_code=status_code,
                duration_ms=elapsed(),
            )
        )

    # --- orchestration ---------------------------------------------------------------------

    def run(
        self,
        features: Sequence[FeatureRoutes],
        *,
        expect_ai: bool,
        check_ai: bool = True,
        crud: bool = True,
    ) -> list[CheckResult]:
        self.check_page("Shared home page", SHARED_OWNER, "/", marker="PropertyScope")
        self.check_health("Shared edge liveness", SHARED_OWNER, "/healthz")
        for feature in features:
            self.check_page(f"{feature.slug} frontend", feature.owner, feature.frontend_path)
            self.check_health(f"{feature.slug} health", feature.owner, feature.health_path)
        if crud:
            for feature in features:
                factory = CRUD_CASES.get(feature.feature_key)
                if factory is None:
                    self.record(
                        CheckResult(
                            f"{feature.slug} CRUD case",
                            feature.owner,
                            "crud",
                            False,
                            "no cloud CRUD smoke case is registered for this feature",
                            operation="missing-case",
                        )
                    )
                    continue
                self.run_crud(factory())
        if check_ai:
            self.check_ai(expect_ai=expect_ai)
        return self.results


def _error(exc: httpx.HTTPError) -> str:
    return f"{type(exc).__name__}: {exc}"[:300]


def _extracted(case: CrudCase, response: httpx.Response, statuses: Sequence[int]) -> dict[str, Any]:
    """The feature's record from a response with an accepted status, or ``{}``."""
    if response.status_code not in statuses:
        return {}
    try:
        payload = response.json()
        return case.extract(payload) if isinstance(payload, dict) else {}
    except ValueError:
        return {}


def _problem_code(response: httpx.Response) -> str | None:
    try:
        payload = response.json()
    except ValueError:
        return None
    code = payload.get("code") if isinstance(payload, dict) else None
    return code if isinstance(code, str) else None


def _problem(response: httpx.Response) -> str:
    code = _problem_code(response)
    if code:
        return code
    return response.text.strip().replace("\n", " ")[:120] or "empty body"


def summarise(results: Sequence[CheckResult]) -> dict[str, Any]:
    owners: dict[str, dict[str, int]] = {}
    for result in results:
        counts = owners.setdefault(result.owner, {"passed": 0, "failed": 0})
        counts["passed" if result.passed else "failed"] += 1
    return {
        "total": len(results),
        "passed": sum(result.passed for result in results),
        "failed": sum(not result.passed for result in results),
        "by_owner": owners,
    }


def ai_enabled(state: str | None) -> bool | None:
    """The observed AI flag: only an explicit answer counts; unreachable proves nothing."""
    return {"disabled": False, "available": True}.get(state or "")


def build_document(
    *,
    base_url: str,
    results: Sequence[CheckResult],
    expect_ai: bool,
    started_at: datetime,
    finished_at: datetime | None = None,
    identity: DeploymentIdentity | None = None,
    ai_state: str | None = None,
) -> dict[str, Any]:
    """The cloud-smoke.json document (schema version 2, see the module docstring)."""
    deployed = identity or DeploymentIdentity()
    summary = summarise(results)
    finished = finished_at or datetime.now(UTC)
    return {
        "schema_version": SCHEMA_VERSION,
        "tool": "scripts/cloud_smoke.py",
        "base_url": base_url,
        "commit_sha": deployed.commit_sha,
        "image_tag": deployed.image_tag,
        "registry": deployed.registry,
        "images": dict(sorted(deployed.images.items())),
        "images_source": deployed.images_source,
        "ai_enabled": ai_enabled(ai_state),
        "ai_state": ai_state or "not_checked",
        "expect_ai": expect_ai,
        "started_at": started_at.isoformat(timespec="seconds"),
        "finished_at": finished.isoformat(timespec="seconds"),
        "passed": summary["failed"] == 0,
        "summary": summary,
        "checks": [asdict(result) for result in results],
    }


def write_reports(
    output_dir: Path,
    *,
    base_url: str,
    results: Sequence[CheckResult],
    expect_ai: bool,
    started_at: datetime,
    identity: DeploymentIdentity | None = None,
    ai_state: str | None = None,
) -> dict[str, Any]:
    """Write cloud-smoke.json and cloud-smoke.md; return the JSON document."""
    output_dir.mkdir(parents=True, exist_ok=True)
    document = build_document(
        base_url=base_url,
        results=results,
        expect_ai=expect_ai,
        started_at=started_at,
        identity=identity,
        ai_state=ai_state,
    )
    (output_dir / SMOKE_JSON).write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    (output_dir / SMOKE_MARKDOWN).write_text(render_markdown(document), encoding="utf-8")
    return document


def render_markdown(document: Mapping[str, Any]) -> str:
    summary = document["summary"]
    verdict = "PASSED" if document["passed"] else "FAILED"
    images = document.get("images") or {}
    lines = [
        "# Cloud smoke test",
        "",
        f"- Target: `{document['base_url']}`",
        f"- Commit: `{document.get('commit_sha') or 'not recorded'}`; image tag "
        f"`{document.get('image_tag') or 'not recorded'}`; {len(images)} image reference(s) "
        f"from {document.get('images_source', 'not recorded')}",
        f"- Started: {document['started_at']} (finished {document['finished_at']})",
        f"- AI expectation: {'reachable (--expect-ai)' if document['expect_ai'] else 'disabled'}; "
        f"observed: {document.get('ai_state', 'not_checked')}",
        f"- Result: **{verdict}**, {summary['passed']} of {summary['total']} checks passed",
        "",
        "| Owner | Passed | Failed |",
        "|---|---|---|",
    ]
    for owner, counts in sorted(summary["by_owner"].items()):
        lines.append(f"| {owner} | {counts['passed']} | {counts['failed']} |")
    lines += [
        "",
        "| Result | Owner | Category | Check | Request | Detail | ms |",
        "|---|---|---|---|---|---|---|",
    ]
    for check in document["checks"]:
        request = f"`{check['method']} {check['path']}`" if check["path"] else ""
        detail = str(check["detail"]).replace("|", "\\|")
        lines.append(
            f"| {'PASS' if check['passed'] else 'FAIL'} | {check['owner']} | {check['category']} "
            f"| {check['name']} | {request} | {detail} | {check['duration_ms']} |"
        )
    lines += [
        "",
        "Every CRUD case creates a uniquely named record through the owning feature's public API, "
        "reads it back, updates it where the feature registers an update, deletes it and "
        "confirms the delete. No credentials are sent.",
        "",
    ]
    if images:
        lines += ["| Service | Image |", "|---|---|"]
        lines += [f"| {service} | `{reference}` |" for service, reference in images.items()]
        lines.append("")
    return "\n".join(lines)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--base-url", required=True, help="Public edge, e.g. https://host")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=REPOSITORY_ROOT / ".propertyscope-runtime" / "cloud" / "smoke",
        help="Where cloud-smoke.json and cloud-smoke.md are written",
    )
    parser.add_argument(
        "--expect-ai",
        action="store_true",
        help="Require the AI tier to be reachable (bonus tiers) instead of disabled",
    )
    parser.add_argument(
        "--skip-ai-check", action="store_true", help="Do not check the AI tier at all"
    )
    parser.add_argument("--no-crud", action="store_true", help="Only pages and health")
    parser.add_argument("--timeout", type=float, default=20.0, help="Per-request timeout (s)")
    parser.add_argument(
        "--insecure",
        action="store_true",
        help="Skip TLS verification (only before the first certificate is issued)",
    )
    identity = parser.add_argument_group(
        "deployment identity", "Recorded in cloud-smoke.json for the Cloud Deployment Review"
    )
    identity.add_argument(
        "--commit-sha",
        help="Deployed commit (default: $PROPERTYSCOPE_DEPLOY_SHA, then $PROPERTYSCOPE_GIT_SHA)",
    )
    identity.add_argument("--image-tag", help="Deployed image tag (default: $IMAGE_TAG)")
    identity.add_argument("--registry", help="Image registry (default: $ACR_LOGIN_SERVER)")
    identity.add_argument(
        "--image",
        action="append",
        default=[],
        metavar="SERVICE=REFERENCE",
        help="An explicit image reference, e.g. a digest; replaces the derived list",
    )
    identity.add_argument(
        "--vm-log",
        type=Path,
        help="vm-deploy.log from deploy.sh deploy: record the images the VM reported running "
        "(its PROPERTYSCOPE_IMAGES line) instead of deriving them from the tag",
    )
    return parser


def identity_from(
    arguments: argparse.Namespace, environment: Mapping[str, str]
) -> DeploymentIdentity:
    """Resolve the deployment identity from the CLI, then the deploy.sh environment."""
    images: dict[str, str] = {}
    for value in arguments.image:
        service, separator, reference = value.partition("=")
        if not separator:
            raise ValueError(f"--image must be SERVICE=REFERENCE, got {value!r}")
        images[service.strip()] = reference.strip()
    observed: dict[str, str] = {}
    if arguments.vm_log is not None:
        try:
            observed = vm_images(arguments.vm_log.read_text(encoding="utf-8", errors="replace"))
        except OSError as exc:
            raise ValueError(f"cannot read --vm-log {arguments.vm_log}: {exc}") from exc
    return deployment_identity(
        commit_sha=arguments.commit_sha
        or environment.get("PROPERTYSCOPE_DEPLOY_SHA")
        or environment.get("PROPERTYSCOPE_GIT_SHA"),
        image_tag=arguments.image_tag or environment.get("IMAGE_TAG"),
        registry=arguments.registry or environment.get("ACR_LOGIN_SERVER"),
        images=images,
        services=azure_image_services(),
        observed=observed,
    )


def main(
    argv: Sequence[str] | None = None,
    *,
    transport: httpx.BaseTransport | None = None,
    environment: Mapping[str, str] | None = None,
) -> int:
    arguments = _parser().parse_args(argv)
    base_url = arguments.base_url.rstrip("/")
    if not base_url.startswith(("http://", "https://")):
        print("--base-url must start with http:// or https://", file=sys.stderr)
        return 2
    try:
        identity = identity_from(arguments, os.environ if environment is None else environment)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    started_at = datetime.now(UTC)
    with httpx.Client(
        timeout=arguments.timeout,
        verify=not arguments.insecure,
        follow_redirects=False,
        transport=transport,
        headers={"User-Agent": "propertyscope-cloud-smoke/1"},
    ) as client:
        smoke = Smoke(client, base_url=base_url, ai_timeout=min(arguments.timeout, 15.0))
        results = smoke.run(
            load_features(),
            expect_ai=arguments.expect_ai,
            check_ai=not arguments.skip_ai_check,
            crud=not arguments.no_crud,
        )
    document = write_reports(
        arguments.output_dir,
        base_url=base_url,
        results=results,
        expect_ai=arguments.expect_ai,
        started_at=started_at,
        identity=identity,
        ai_state=smoke.ai_state,
    )
    summary = document["summary"]
    print(
        f"\n{summary['passed']}/{summary['total']} checks passed; "
        f"reports in {arguments.output_dir}",
        flush=True,
    )
    return 0 if document["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
