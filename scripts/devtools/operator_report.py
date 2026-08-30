"""Read-only operational projection for the supported local data workflow."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import httpx

MAX_RESPONSE_BYTES = 1_048_576
MAX_PROJECTED_ITEMS = 100


class OperatorReportError(RuntimeError):
    """The running stack did not expose a valid bounded operator projection."""


def _bounded_get(
    client: httpx.Client,
    url: str,
    *,
    label: str,
    timeout: float,
    params: Mapping[str, str | int | float | bool | None] | None = None,
) -> httpx.Response:
    content = bytearray()
    with client.stream(
        "GET",
        url,
        params=params,
        headers={"Accept": "application/json"},
        timeout=timeout,
    ) as response:
        for chunk in response.iter_bytes():
            if len(content) + len(chunk) > MAX_RESPONSE_BYTES:
                raise OperatorReportError(
                    f"{label} exceeds the {MAX_RESPONSE_BYTES}-byte response limit"
                )
            content.extend(chunk)
        return httpx.Response(
            response.status_code,
            headers=response.headers,
            content=bytes(content),
            request=response.request,
        )


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
        response = _bounded_get(client, url, label=label, timeout=5.0)
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


def _operation_statuses(items: object) -> tuple[str, ...]:
    if not isinstance(items, list):
        return ()
    return tuple(str(item.get("status", "unknown")) for item in items if isinstance(item, dict))


def _prerequisite(
    status: str,
    *,
    consumer_imports: object = (),
    activations: object = (),
) -> str:
    if status == "awaiting_review":
        activation_states = _operation_statuses(activations)
        if "succeeded" in activation_states:
            return "activation succeeded; release-status reconciliation is pending"
        for state in ("running", "claimed", "queued", "interrupted"):
            if state in activation_states:
                return f"consumer accepted; activation is {state}"
        if "failed" in activation_states:
            return "activation failed; inspect the durable operation before a reviewed retry"

        import_states = _operation_statuses(consumer_imports)
        if "published" in import_states:
            return "activation succeeded; release-status reconciliation is pending"
        if "activation_queued" in import_states:
            return "consumer accepted; activation is queued"
        if "activation_pending" in import_states:
            return "consumer accepted; activation queueing or reconciliation is pending"
        if "receipt_pending" in import_states:
            return "consumer finished; receipt validation and persistence are pending"
        for state in ("running", "polling", "claimed", "queued", "interrupted"):
            if state in import_states:
                return f"explicit approval recorded; consumer import is {state}"
        for state in ("rejected", "failed"):
            if state in import_states:
                return f"consumer import is {state}; inspect it before a reviewed retry"
        return "explicit approval and consumer acceptance are required"
    return {
        "draft": "candidate construction must complete",
        "candidate": "submit for explicit human review",
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
        _object(
            _bounded_get(
                client,
                f"{base}data-products",
                label="product catalogue",
                timeout=10.0,
            ),
            label="product catalogue",
        ),
        label="product catalogue",
    )
    releases = _items(
        _object(
            _bounded_get(
                client,
                f"{base}dataset-releases",
                params={"limit": 100, "offset": 0},
                label="release catalogue",
                timeout=10.0,
            ),
            label="release catalogue",
        ),
        label="release catalogue",
    )
    if len(products) > MAX_PROJECTED_ITEMS or len(releases) > MAX_PROJECTED_ITEMS:
        raise OperatorReportError("operator report collections exceed the supported 100-item bound")

    operations: list[dict[str, Any]] = []
    activations: list[dict[str, Any]] = []
    prerequisites: list[dict[str, str]] = []
    bounded_evidence: list[dict[str, Any]] = []
    if len(products) == MAX_PROJECTED_ITEMS:
        bounded_evidence.append(
            {
                "collection": "registered products",
                "returned": len(products),
                "limit": MAX_PROJECTED_ITEMS,
                "possibly_truncated": True,
            }
        )
    if len(releases) == MAX_PROJECTED_ITEMS:
        bounded_evidence.append(
            {
                "collection": "release catalogue",
                "returned": len(releases),
                "limit": MAX_PROJECTED_ITEMS,
                "possibly_truncated": True,
            }
        )
    operations_truncated = False
    activations_truncated = False
    for release in releases:
        release_id = release.get("id")
        status = str(release.get("status", "unknown"))
        if not isinstance(release_id, str) or not release_id:
            prerequisites.append(
                {
                    "release_id": "unknown",
                    "status": status,
                    "next_required": _prerequisite(status),
                }
            )
            continue
        detail = _object(
            _bounded_get(
                client,
                f"{base}dataset-releases/{release_id}",
                label=f"release {release_id}",
                timeout=10.0,
            ),
            label=f"release {release_id}",
        )
        consumer_imports = detail.get("consumer_imports", [])
        release_activations = detail.get("activations", [])
        prerequisites.append(
            {
                "release_id": release_id,
                "status": status,
                "next_required": _prerequisite(
                    status,
                    consumer_imports=consumer_imports,
                    activations=release_activations,
                ),
            }
        )
        for operation in consumer_imports if isinstance(consumer_imports, list) else ():
            if isinstance(operation, dict) and len(operations) < MAX_PROJECTED_ITEMS:
                operations.append(dict(operation))
            elif isinstance(operation, dict):
                operations_truncated = True
        for activation in release_activations if isinstance(release_activations, list) else ():
            if isinstance(activation, dict) and len(activations) < MAX_PROJECTED_ITEMS:
                activations.append(dict(activation))
            elif isinstance(activation, dict):
                activations_truncated = True

    for collection, values, truncated in (
        ("consumer-import operations", operations, operations_truncated),
        ("activations", activations, activations_truncated),
    ):
        if truncated:
            bounded_evidence.append(
                {
                    "collection": collection,
                    "returned": len(values),
                    "limit": MAX_PROJECTED_ITEMS,
                    "possibly_truncated": True,
                }
            )

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
        "bounded_evidence": bounded_evidence,
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
    bounded = report.get("bounded_evidence", [])
    for item in bounded if isinstance(bounded, Sequence) else ():
        if isinstance(item, Mapping) and item.get("possibly_truncated") is True:
            lines.append(
                "Bounded evidence warning: "
                f"{_identifier(item.get('collection'))} may be partial; "
                f"showing {_identifier(item.get('returned'))} of an unknown total "
                f"at the {_identifier(item.get('limit'))}-item limit."
            )
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
