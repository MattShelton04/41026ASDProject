"""Public smoke test for a deployed PropertyScope stack (Release 2, R2-44).

Run it against the Azure edge after every deployment, or against a local stack:

    uv run python scripts/cloud_smoke.py --base-url https://<label>.australiaeast.cloudapp.azure.com
    uv run python scripts/cloud_smoke.py --base-url http://localhost:5100 --output-dir out/

It checks, only through the public edge:

- the Shared home page ``/`` and the edge liveness route ``/healthz``;
- every enabled feature's frontend route and its health projection;
- one self-cleaning CRUD case per feature, owned by that feature: create a uniquely named
  resource, read it back, delete it and confirm it is gone;
- that the shared AI tier reports itself disabled (the cloud baseline), or with ``--expect-ai``
  that it is reachable (bonus tiers).

Results are written as ``cloud-smoke.json`` and ``cloud-smoke.md``. Every CRUD case deletes what
it created, even when a later step fails. The script sends no credentials and never calls an AI
route that would create a run.
"""

from __future__ import annotations

import argparse
import json
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
    """A create -> read -> delete -> confirm-gone cycle on one feature-owned resource."""

    owner: str
    resource: str
    collection: str
    body: Callable[[Smoke, str], dict[str, Any]]
    extract: Callable[[dict[str, Any]], dict[str, Any]]
    name_field: str
    delete_statuses: tuple[int, ...] = (200, 204)
    created_id: str | None = field(default=None)


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


def _unique_name(kind: str) -> str:
    return f"{SMOKE_PREFIX}-{kind}-{uuid.uuid4().hex[:10]}"


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

    def __init__(self, client: httpx.Client, *, base_url: str, ai_timeout: float = 15.0) -> None:
        self.client = client
        self.base_url = base_url.rstrip("/")
        self.ai_timeout = ai_timeout
        self.cleanup_attempts = 3
        self.cleanup_delay = 2.0
        self.results: list[CheckResult] = []
        self._property: tuple[str, str] | None = None

    # --- recording -------------------------------------------------------------------------

    def record(self, result: CheckResult) -> CheckResult:
        self.results.append(result)
        verdict = "PASS" if result.passed else "FAIL"
        print(f"{verdict} [{result.owner}] {result.name}: {result.detail}", flush=True)
        return result

    @contextmanager
    def timed(self) -> Iterator[Callable[[], int]]:
        started = time.monotonic()
        yield lambda: int((time.monotonic() - started) * 1000)

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
        name = _unique_name(case.owner)
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
            )
        )
        if case.created_id is None:
            return
        item = f"{case.collection}/{case.created_id}"
        with self.timed() as elapsed:
            response = self.request("GET", item)
        read_name: object = None
        try:
            read_name = case.extract(response.json()).get(case.name_field)
        except (ValueError, AttributeError):
            read_name = None
        self.record(
            CheckResult(
                f"{label}: read",
                case.owner,
                "crud",
                response.status_code == 200 and read_name == name,
                f"HTTP {response.status_code}, {case.name_field} "
                + ("matches" if read_name == name else f"is {read_name!r}"),
                "GET",
                item,
                response.status_code,
                elapsed(),
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
                        )
                    )
                    continue
                self.run_crud(factory())
        if check_ai:
            self.check_ai(expect_ai=expect_ai)
        return self.results


def _error(exc: httpx.HTTPError) -> str:
    return f"{type(exc).__name__}: {exc}"[:300]


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


def write_reports(
    output_dir: Path,
    *,
    base_url: str,
    results: Sequence[CheckResult],
    expect_ai: bool,
    started_at: datetime,
) -> dict[str, Any]:
    """Write cloud-smoke.json and cloud-smoke.md; return the JSON document."""
    output_dir.mkdir(parents=True, exist_ok=True)
    summary = summarise(results)
    document: dict[str, Any] = {
        "schema_version": 1,
        "tool": "scripts/cloud_smoke.py",
        "base_url": base_url,
        "started_at": started_at.isoformat(timespec="seconds"),
        "finished_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "expect_ai": expect_ai,
        "passed": summary["failed"] == 0,
        "summary": summary,
        "checks": [asdict(result) for result in results],
    }
    (output_dir / "cloud-smoke.json").write_text(
        json.dumps(document, indent=2) + "\n", encoding="utf-8"
    )
    (output_dir / "cloud-smoke.md").write_text(render_markdown(document), encoding="utf-8")
    return document


def render_markdown(document: Mapping[str, Any]) -> str:
    summary = document["summary"]
    verdict = "PASSED" if document["passed"] else "FAILED"
    lines = [
        "# Cloud smoke test",
        "",
        f"- Target: `{document['base_url']}`",
        f"- Started: {document['started_at']} (finished {document['finished_at']})",
        f"- AI expectation: {'reachable (--expect-ai)' if document['expect_ai'] else 'disabled'}",
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
        "reads it back, deletes it and confirms the delete. No credentials are sent.",
        "",
    ]
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
    return parser


def main(argv: Sequence[str] | None = None, *, transport: httpx.BaseTransport | None = None) -> int:
    arguments = _parser().parse_args(argv)
    base_url = arguments.base_url.rstrip("/")
    if not base_url.startswith(("http://", "https://")):
        print("--base-url must start with http:// or https://", file=sys.stderr)
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
