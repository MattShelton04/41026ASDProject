"""Verify the bounded Shared and Feature 1 Release 0 Compose stack."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener


class VerificationError(RuntimeError):
    """A release smoke assertion did not pass before its deadline."""


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(
        self,
        req: Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> None:
        return None


ResponseValidator = Callable[[int, Mapping[str, str], bytes], None]


@dataclass(frozen=True)
class HttpCheck:
    """One externally reachable stack assertion."""

    name: str
    url: str
    expected_status: int = 200
    follow_redirects: bool = True
    validator: ResponseValidator | None = None


def _json_object(body: bytes) -> dict[str, object]:
    value = json.loads(body.decode("utf-8"))
    if not isinstance(value, dict):
        raise VerificationError("response body must be a JSON object")
    return value


def _validate_property_search(_status: int, _headers: Mapping[str, str], body: bytes) -> None:
    payload = _json_object(body)
    items = payload.get("items")
    if not isinstance(items, list) or not items:
        raise VerificationError("property search returned no fixture records")


def _validate_redirect(_status: int, headers: Mapping[str, str], _body: bytes) -> None:
    if headers.get("Location") != "/#features":
        raise VerificationError("planned feature route did not return the shared feature index")


def _validate_problem(_status: int, _headers: Mapping[str, str], body: bytes) -> None:
    payload = _json_object(body)
    request_id = payload.get("request_id")
    if (
        payload.get("code") != "route_not_found"
        or not isinstance(request_id, str)
        or not request_id
    ):
        raise VerificationError("404 response is missing its structured error code or request ID")


def _request(check: HttpCheck, *, deadline_seconds: float) -> dict[str, object]:
    opener = build_opener() if check.follow_redirects else build_opener(_NoRedirect())
    deadline = time.monotonic() + deadline_seconds
    last_error = "request was not attempted"
    attempts = 0

    while time.monotonic() < deadline:
        attempts += 1
        try:
            request = Request(check.url, headers={"Accept": "application/json, text/html;q=0.9"})
            try:
                response = opener.open(request, timeout=min(5.0, deadline_seconds))
            except HTTPError as exc:
                response = exc
            with response:
                status = response.status
                headers = dict(response.headers.items())
                body = response.read()
            if status != check.expected_status:
                raise VerificationError(f"expected HTTP {check.expected_status}, received {status}")
            if check.validator is not None:
                check.validator(status, headers, body)
            return {
                "name": check.name,
                "target": check.url,
                "status": "passed",
                "http_status": status,
                "attempts": attempts,
            }
        except (OSError, URLError, VerificationError, json.JSONDecodeError) as exc:
            last_error = str(exc)
            remaining = deadline - time.monotonic()
            if remaining > 0:
                time.sleep(min(1.0, remaining))

    raise VerificationError(
        f"{check.name} did not pass within {deadline_seconds:.0f}s after {attempts} attempts: "
        f"{last_error}"
    )


def _compose_python(service: str, source: str) -> str:
    command = [
        "docker",
        "compose",
        "--profile",
        "release-0",
        "exec",
        "-T",
        service,
        "python",
        "-c",
        source,
    ]
    completed = subprocess.run(command, check=True, capture_output=True, text=True, timeout=30)
    return completed.stdout.strip()


def _verify_internal_services() -> list[dict[str, object]]:
    health_source = (
        "import urllib.request; "
        "response=urllib.request.urlopen('http://127.0.0.1:{port}/health/ready', timeout=2); "
        "assert response.status == 200"
    )
    results: list[dict[str, object]] = []
    for name, port in (("f1-db-api", 5202), ("f1-backend", 5201)):
        _compose_python(name, health_source.format(port=port))
        results.append({"name": f"{name} internal readiness", "status": "passed"})

    fingerprint_source = (
        "import json,os,urllib.request; "
        "request=urllib.request.Request("
        "'http://127.0.0.1:5202/internal/data-platform/v1/schema/fingerprint',"
        "headers={'X-PropertyScope-Internal-Token':os.environ['PROPERTYSCOPE_INTERNAL_TOKEN']}); "
        "print(json.dumps(json.load(urllib.request.urlopen(request, timeout=2))))"
    )
    fingerprint = _json_object(_compose_python("f1-db-api", fingerprint_source).encode())
    digest = fingerprint.get("fingerprint")
    if fingerprint.get("algorithm") != "sha256" or not isinstance(digest, str) or len(digest) != 64:
        raise VerificationError("database service returned an invalid schema fingerprint")
    results.append(
        {
            "name": "Feature 1 database schema fingerprint",
            "status": "passed",
            "algorithm": "sha256",
            "fingerprint": digest,
        }
    )
    return results


def _checks(shared_origin: str, feature_origin: str) -> tuple[HttpCheck, ...]:
    search = "api/data-platform/v1/properties/search?q=11%20Example%20Street&state=NSW&limit=10"
    return (
        HttpCheck("Shared home", f"{shared_origin}/"),
        HttpCheck("Shared runtime configuration", f"{shared_origin}/config.js"),
        HttpCheck("Shared Feature 1 route", f"{shared_origin}/features/data-platform/"),
        HttpCheck(
            "Shared Feature 1 application asset", f"{shared_origin}/features/data-platform/app.js"
        ),
        HttpCheck(
            "Shared Feature 1 design tokens",
            f"{shared_origin}/features/data-platform/design-system/tokens.css",
        ),
        HttpCheck("Shared AI-mode operations route", f"{shared_origin}/operations/ai-mode/"),
        HttpCheck("Feature 1 home", f"{feature_origin}/"),
        HttpCheck(
            "Feature 1 property search",
            f"{feature_origin}/{search}",
            validator=_validate_property_search,
        ),
        HttpCheck(
            "Shared property-search proxy",
            f"{shared_origin}/{search}",
            validator=_validate_property_search,
        ),
        HttpCheck(
            "Planned feature redirect",
            f"{shared_origin}/features/market-intelligence/",
            expected_status=307,
            follow_redirects=False,
            validator=_validate_redirect,
        ),
        HttpCheck(
            "Shared structured 404",
            f"{shared_origin}/api/does-not-exist",
            expected_status=404,
            follow_redirects=False,
            validator=_validate_problem,
        ),
    )


def _write_evidence(path: Path, checks: list[dict[str, object]], *, status: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    document = {
        "schema_version": "propertyscope.release-0-ci-evidence.v1",
        "status": status,
        "checked_at": datetime.now(UTC).isoformat(),
        "repository": os.getenv("GITHUB_REPOSITORY"),
        "workflow": os.getenv("GITHUB_WORKFLOW"),
        "run_id": os.getenv("GITHUB_RUN_ID"),
        "commit_sha": os.getenv("GITHUB_SHA"),
        "ref": os.getenv("GITHUB_REF"),
        "checks": checks,
    }
    path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")


def verify(
    *,
    shared_origin: str,
    feature_origin: str,
    deadline_seconds: float,
    evidence_path: Path,
) -> None:
    """Run the public and internal Release 0 assertions and retain their evidence."""
    results: list[dict[str, object]] = []
    try:
        for check in _checks(shared_origin.rstrip("/"), feature_origin.rstrip("/")):
            result = _request(check, deadline_seconds=deadline_seconds)
            results.append(result)
            print(f"PASS: {check.name}", flush=True)
        for result in _verify_internal_services():
            results.append(result)
            print(f"PASS: {result['name']}", flush=True)
    except (OSError, subprocess.SubprocessError, VerificationError, json.JSONDecodeError) as exc:
        results.append({"name": "verification", "status": "failed", "error": str(exc)})
        _write_evidence(evidence_path, results, status="failed")
        raise VerificationError(str(exc)) from exc
    _write_evidence(evidence_path, results, status="passed")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--shared-origin", default="http://127.0.0.1:5100")
    parser.add_argument("--feature-origin", default="http://127.0.0.1:5200")
    parser.add_argument("--deadline-seconds", type=float, default=30.0)
    parser.add_argument(
        "--evidence",
        type=Path,
        default=Path(".propertyscope-runtime/ci/release-0-smoke.json"),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the verifier as a command-line program."""
    arguments = _parser().parse_args(argv)
    try:
        verify(
            shared_origin=arguments.shared_origin,
            feature_origin=arguments.feature_origin,
            deadline_seconds=arguments.deadline_seconds,
            evidence_path=arguments.evidence,
        )
    except VerificationError as exc:
        print(f"Release 0 stack verification failed: {exc}", file=sys.stderr)
        return 1
    print(f"Release 0 stack evidence: {arguments.evidence}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
