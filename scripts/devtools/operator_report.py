"""Read-only operational projection for the supported local data workflow."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import httpx

MAX_RESPONSE_BYTES = 1_048_576
MAX_PROJECTED_ITEMS = 100


class OperatorReportError(RuntimeError):
    """The running stack did not expose a valid bounded operator projection."""


def _object(response: httpx.Response, *, label: str) -> dict[str, Any]:
    response.raise_for_status()
    if len(response.content) > MAX_RESPONSE_BYTES:
        raise OperatorReportError(f"{label} exceeds the {MAX_RESPONSE_BYTES}-byte response limit")
    try:
        payload = response.json()
    except ValueError as exc:
        raise OperatorReportError(f"{label} did not return JSON") from exc
    if not isinstance(payload, dict):
        raise OperatorReportError(f"{label} did not return a JSON object")
    return payload


def _items(payload: Mapping[str, Any], *, label: str) -> list[dict[str, Any]]:
    value = payload.get("items")
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise OperatorReportError(f"{label} did not return an item collection")
    return value


def _health(client: httpx.Client, url: str, *, label: str) -> dict[str, Any]:
    try:
        response = client.get(url, headers={"Accept": "application/json"}, timeout=5.0)
        if len(response.content) > MAX_RESPONSE_BYTES:
            raise OperatorReportError(
                f"{label} exceeds the {MAX_RESPONSE_BYTES}-byte response limit"
            )
        payload = _object(response, label=label) if response.status_code < 400 else response.json()
    except (httpx.HTTPError, ValueError, OperatorReportError) as exc:
        return {"service": label, "http_status": None, "status": "unavailable", "detail": str(exc)}
    if not isinstance(payload, dict):
        payload = {}
    return {
        "service": str(payload.get("service", label)),
        "http_status": response.status_code,
        "status": str(payload.get("status", "unknown")),
        "checks": payload.get("checks", payload.get("dependencies", {})),
    }


def _prerequisite(status: str) -> str:
    return {
        "draft": "candidate construction must complete",
        "candidate": "submit for explicit human review",
        "awaiting_review": "explicit approval and consumer acceptance are required",
        "accepted": "complete",
        "superseded": "complete; a newer accepted release is live",
        "rejected": "terminal; create a corrected candidate",
        "abandoned": "terminal; create or reconcile a corrected candidate",
    }.get(status, "inspect the release before taking action")


def collect_operator_report(
    client: httpx.Client,
    *,
    data_base_url: str,
    feature_health_url: str,
    ai_health_url: str,
) -> dict[str, Any]:
    """Collect bounded public evidence without reviewing, publishing, or mutating state."""
    base = data_base_url.rstrip("/") + "/"
    products = _items(
        _object(client.get(f"{base}data-products", timeout=10.0), label="product catalogue"),
        label="product catalogue",
    )
    releases = _items(
        _object(
            client.get(f"{base}dataset-releases", params={"limit": 100, "offset": 0}, timeout=10.0),
            label="release catalogue",
        ),
        label="release catalogue",
    )
    if len(products) > MAX_PROJECTED_ITEMS or len(releases) > MAX_PROJECTED_ITEMS:
        raise OperatorReportError("operator report collections exceed the supported 100-item bound")

    operations: list[dict[str, Any]] = []
    activations: list[dict[str, Any]] = []
    prerequisites: list[dict[str, str]] = []
    for release in releases:
        release_id = release.get("id")
        status = str(release.get("status", "unknown"))
        prerequisites.append(
            {
                "release_id": str(release_id or "unknown"),
                "status": status,
                "next_required": _prerequisite(status),
            }
        )
        if not isinstance(release_id, str) or not release_id:
            continue
        detail = _object(
            client.get(f"{base}dataset-releases/{release_id}", timeout=10.0),
            label=f"release {release_id}",
        )
        for operation in detail.get("consumer_imports", []):
            if isinstance(operation, dict) and len(operations) < MAX_PROJECTED_ITEMS:
                operations.append(dict(operation))
        for activation in detail.get("activations", []):
            if isinstance(activation, dict) and len(activations) < MAX_PROJECTED_ITEMS:
                activations.append(dict(activation))

    accepted = [
        {
            "dataset_id": item.get("dataset_id"),
            "release": item.get("latest_accepted_release"),
        }
        for item in products
        if item.get("latest_accepted_release") is not None
    ]
    return {
        "registered_products": products,
        "accepted_releases": accepted,
        "review_publication_prerequisites": prerequisites,
        "consumer_import_operations": operations,
        "activations": activations,
        "health": [
            _health(client, feature_health_url, label="feature-1"),
            _health(client, ai_health_url, label="ai-mode"),
        ],
    }


def _identifier(value: object) -> str:
    text = str(value or "unknown")
    return text if len(text) <= 80 else f"{text[:77]}..."


def render_operator_report(report: Mapping[str, Any]) -> str:
    """Render concise evidence and make the read-only boundary explicit."""
    lines = ["PropertyScope operator report (read-only)"]
    products = report.get("registered_products", [])
    lines.append(f"Registered products: {len(products) if isinstance(products, Sequence) else 0}")
    for item in products if isinstance(products, Sequence) else ():
        if isinstance(item, Mapping):
            lines.append(
                f"  - {_identifier(item.get('dataset_id'))}: schema "
                f"{_identifier(item.get('product_schema_version'))}"
            )
    accepted = report.get("accepted_releases", [])
    lines.append(f"Accepted releases: {len(accepted) if isinstance(accepted, Sequence) else 0}")
    for item in accepted if isinstance(accepted, Sequence) else ():
        if isinstance(item, Mapping) and isinstance(item.get("release"), Mapping):
            release = item["release"]
            lines.append(
                f"  - {_identifier(item.get('dataset_id'))}: {_identifier(release.get('id'))} "
                f"({release.get('record_count', 0)} records)"
            )
    prerequisites = report.get("review_publication_prerequisites", [])
    lines.append("Review/publication prerequisites:")
    for item in prerequisites if isinstance(prerequisites, Sequence) else ():
        if isinstance(item, Mapping):
            lines.append(
                f"  - {_identifier(item.get('release_id'))} [{_identifier(item.get('status'))}]: "
                f"{_identifier(item.get('next_required'))}"
            )
    for key, label in (
        ("consumer_import_operations", "Consumer-import operations"),
        ("activations", "Activations"),
    ):
        values = report.get(key, [])
        lines.append(f"{label}: {len(values) if isinstance(values, Sequence) else 0}")
        for item in values if isinstance(values, Sequence) else ():
            if isinstance(item, Mapping):
                lines.append(
                    f"  - {_identifier(item.get('id'))}: {_identifier(item.get('status'))}"
                )
    lines.append("Health and optional dependencies:")
    health = report.get("health", [])
    for item in health if isinstance(health, Sequence) else ():
        if isinstance(item, Mapping):
            lines.append(
                f"  - {_identifier(item.get('service'))}: {_identifier(item.get('status'))} "
                f"(HTTP {_identifier(item.get('http_status'))})"
            )
    lines.append("No review, publication, import, or activation action was performed.")
    return "\n".join(lines)
