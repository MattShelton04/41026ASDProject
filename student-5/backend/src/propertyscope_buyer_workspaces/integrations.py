"""Bounded public-feature evidence and shared AI-mode HTTP adapters."""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from typing import Any, Protocol
from urllib.parse import urlencode

from propertyscope_buyer_workspaces.clients import (
    ClientResponse,
    DatabaseProtocolError,
    DatabaseUnavailableError,
    HttpTransport,
    UrllibTransport,
)
from propertyscope_buyer_workspaces.suburb_evidence import normalise_locality, project_context

_MAX_PROPERTIES = 10
_PAGE_SIZE = 25


class IntegrationUnavailableError(RuntimeError):
    """A public feature or AI-mode cannot currently be reached."""


class EvidenceGateway(Protocol):
    def collect(
        self,
        property_refs: Sequence[str],
        *,
        request_id: str,
        target_suburbs: Sequence[Mapping[str, str]] = (),
    ) -> dict[str, Any]: ...

    def validate_property(self, property_ref: str, *, request_id: str) -> dict[str, str]: ...


class AiModeGateway(Protocol):
    def create_run(
        self, values: Mapping[str, Any], *, request_id: str, idempotency_key: str | None
    ) -> ClientResponse: ...

    def get_run(self, run_id: str, *, request_id: str) -> ClientResponse: ...

    def get_events(self, run_id: str, *, after: int, request_id: str) -> ClientResponse: ...

    def cancel_run(self, run_id: str, *, request_id: str) -> ClientResponse: ...


class PublicEvidenceClient:
    """Collect small evidence projections without importing another feature."""

    def __init__(
        self,
        data_platform_url: str,
        market_intelligence_url: str,
        due_diligence_url: str,
        *,
        suburb_analytics_url: str = "http://f3-backend:5301",
        transport: HttpTransport | None = None,
        timeout_seconds: float = 4,
    ) -> None:
        self._origins = {
            "feature_1": data_platform_url.rstrip("/"),
            "feature_2": market_intelligence_url.rstrip("/"),
            "feature_3": suburb_analytics_url.rstrip("/"),
            "feature_4": due_diligence_url.rstrip("/"),
        }
        self._transport = transport or UrllibTransport()
        self._timeout = timeout_seconds

    def _get(
        self, origin: str, path: str, request_id: str, params: Mapping[str, int] | None = None
    ) -> ClientResponse:
        try:
            return self._transport.request(
                "GET",
                f"{origin}{path}",
                headers={"X-Request-ID": request_id},
                params=params,
                json_body=None,
                timeout_seconds=self._timeout,
            )
        except (DatabaseProtocolError, DatabaseUnavailableError) as exc:
            raise IntegrationUnavailableError("Evidence dependency unavailable") from exc

    @staticmethod
    def _object(response: ClientResponse) -> dict[str, Any]:
        try:
            value = response.json()
        except DatabaseProtocolError as exc:
            raise IntegrationUnavailableError("Evidence dependency returned invalid data") from exc
        if not isinstance(value, dict):
            raise IntegrationUnavailableError("Evidence dependency returned invalid data")
        return dict(value)

    def validate_property(self, property_ref: str, *, request_id: str) -> dict[str, str]:
        response = self._get(
            self._origins["feature_1"],
            f"/api/data-platform/v1/properties/{property_ref}/report-section",
            request_id,
        )
        if response.status_code == 404:
            return {"state": "unknown"}
        if response.status_code != 200:
            raise IntegrationUnavailableError("Property validation unavailable")
        value = self._object(response)
        identity = value.get("identity")
        if value.get("property_ref") != property_ref or not isinstance(identity, dict):
            raise IntegrationUnavailableError("Property validation returned invalid data")
        resolution = identity.get("resolution_status")
        states = {
            "verified": "validated",
            "provisional": "pending",
            "unresolved": "pending",
            "retired": "pending",
        }
        state = states.get(resolution) if isinstance(resolution, str) else None
        address = value.get("address_display")
        if state is None or not isinstance(address, str) or not address.strip():
            raise IntegrationUnavailableError("Property validation returned invalid data")
        return {"state": state, "label": address.strip()}

    def collect(
        self,
        property_refs: Sequence[str],
        *,
        request_id: str,
        target_suburbs: Sequence[Mapping[str, str]] = (),
    ) -> dict[str, Any]:
        refs = list(dict.fromkeys(property_refs))[:_MAX_PROPERTIES]
        discovery = self._feature_one(refs, request_id)
        sections = {
            "feature_1": discovery,
            "feature_2": self._matched_feature(
                refs,
                request_id,
                feature="feature_2",
                list_path="/api/market-intelligence/v1/market-cases",
                detail_segment="market-cases",
                identifier="market_case_id",
                evidence_keys=("sales",),
            ),
            "feature_3": self._suburbs(discovery, target_suburbs, request_id),
            "feature_4": self._matched_feature(
                refs,
                request_id,
                feature="feature_4",
                list_path="/api/due-diligence/v1/site-reviews",
                detail_segment="site-reviews",
                identifier="site_review_id",
                evidence_keys=("constraints", "buildings"),
            ),
        }
        states = [section["state"] for section in sections.values()]
        overall = "complete" if all(state == "complete" for state in states) else "partial"
        references: list[str] = []
        for feature, section in sections.items():
            for item in section["items"]:
                property_ref = item.get("property_ref")
                if isinstance(property_ref, str):
                    references.append(f"{feature}:property_ref:{property_ref}")
                for key in ("market_case_id", "site_review_id"):
                    identifier = item.get(key)
                    if isinstance(identifier, str):
                        references.append(f"{feature}:{key}:{identifier}")
                if feature == "feature_3" and item.get("locality"):
                    references.append(f"{feature}:{item['context_kind']}:NSW:{item['locality']}")
        return {
            "state": overall,
            "sections": sections,
            "evidence_references": list(dict.fromkeys(references))[:50],
            "limitations": [
                "Evidence is bounded to 10 shortlisted properties, 10 target suburbs, "
                "10 distinct locality requests and the first 25 "
                "Sales research/Due diligence records.",
                "Case target suburbs are buyer preferences, not verified property locations. "
                "Exact locality names do not establish geographic boundary equivalence.",
            ],
        }

    @staticmethod
    def _section(state: str, items: list[dict[str, Any]], limitations: list[str]) -> dict[str, Any]:
        return {"state": state, "items": items, "limitations": limitations}

    def _suburbs(
        self, discovery: dict[str, Any], targets: Sequence[Mapping[str, str]], request_id: str
    ) -> dict[str, Any]:
        contexts: list[dict[str, Any]] = []
        for target in targets[:10]:
            locality = target.get("locality")
            if target.get("state") == "NSW" and isinstance(locality, str) and locality.strip():
                contexts.append(
                    {"context_kind": "case_target", "locality": normalise_locality(locality)}
                )
        for item in discovery["items"]:
            identity = item.get("identity") or {}
            locality = identity.get("locality")
            if (
                identity.get("resolution_status") == "verified"
                and identity.get("state") == "NSW"
                and isinstance(locality, str)
                and locality.strip()
            ):
                contexts.append(
                    {
                        "context_kind": "verified_property_location",
                        "property_ref": item["property_ref"],
                        "locality": normalise_locality(locality),
                    }
                )
        cache: dict[str, dict[str, Any]] = {}
        items = []
        for context in contexts:
            locality = context["locality"]
            if locality not in cache:
                if len(cache) >= 10:
                    items.append(
                        {
                            **context,
                            "state": "partial",
                            "limitations": [
                                "Locality request limit reached; evidence not retrieved."
                            ],
                        }
                    )
                    continue
                try:
                    response = self._get(
                        self._origins["feature_3"],
                        "/api/suburb-analytics/v1/published/context?"
                        + urlencode({"locality": locality}),
                        request_id,
                    )
                    if response.status_code != 200:
                        raise IntegrationUnavailableError("Suburb analytics unavailable")
                    cache[locality] = project_context(self._object(response), locality)
                except (IntegrationUnavailableError, ValueError):
                    cache[locality] = {
                        "state": "unavailable",
                        "limitations": [
                            "Suburb analytics is unavailable or returned invalid locality evidence."
                        ],
                    }
            items.append({**context, "state_code": "NSW", **cache[locality]})
        state = (
            "needs_verification"
            if any(item["state"] == "needs_verification" for item in items)
            else "partial"
            if any(item["state"] != "unavailable" for item in items)
            else "unavailable"
        )
        return self._section(
            state,
            items,
            [
                "Case target context and verified property-location context are separate; "
                "neither is substituted for the other.",
                "Only exact normalized NSW source localities are requested; "
                "no postcode or boundary inference.",
            ],
        )

    def _feature_one(self, refs: list[str], request_id: str) -> dict[str, Any]:
        items: list[dict[str, Any]] = []
        unavailable = False
        for property_ref in refs:
            try:
                response = self._get(
                    self._origins["feature_1"],
                    f"/api/data-platform/v1/properties/{property_ref}/report-section",
                    request_id,
                )
                if response.status_code != 200:
                    unavailable = unavailable or response.status_code != 404
                    items.append(
                        {
                            "property_ref": property_ref,
                            "state": "needs_verification"
                            if response.status_code == 404
                            else "unavailable",
                        }
                    )
                    continue
                value = self._object(response)
                identity = value.get("identity")
                releases = value.get("release_evidence")
                if (
                    value.get("property_ref") != property_ref
                    or not isinstance(identity, dict)
                    or not isinstance(value.get("address_display"), str)
                    or not isinstance(releases, list)
                    or len(releases) > 25
                    or any(not isinstance(release, dict) for release in releases)
                ):
                    raise IntegrationUnavailableError("Invalid Property discovery evidence")
                complete = bool(releases) and all(
                    release.get("coverage_status") == "supported"
                    and isinstance(release.get("coverage_scope"), dict)
                    and release["coverage_scope"].get("complete") is not False
                    and release["coverage_scope"].get("synthetic") is not True
                    and "showcase" not in str(release["coverage_scope"].get("profile", ""))
                    for release in releases
                )
                resolution = (
                    identity.get("resolution_status") if isinstance(identity, dict) else None
                )
                states = {
                    "verified": "complete" if complete else "partial",
                    "provisional": "needs_verification",
                    "unresolved": "needs_verification",
                    "retired": "conflicting",
                }
                state = (
                    states.get(resolution, "needs_verification")
                    if isinstance(resolution, str)
                    else "needs_verification"
                )
                items.append(
                    {
                        "property_ref": property_ref,
                        "state": state,
                        "address_display": value.get("address_display"),
                        "identity": identity,
                        "release_evidence": value.get("release_evidence", [])[:25]
                        if isinstance(value.get("release_evidence", []), list)
                        else [],
                    }
                )
            except IntegrationUnavailableError:
                unavailable = True
                items.append({"property_ref": property_ref, "state": "unavailable"})
        if unavailable and all(item["state"] == "unavailable" for item in items):
            state = "unavailable"
        elif any(item["state"] == "conflicting" for item in items):
            state = "conflicting"
        elif any(item["state"] == "needs_verification" for item in items):
            state = "needs_verification"
        elif items and all(item["state"] == "complete" for item in items):
            state = "complete"
        else:
            state = "partial"
        return self._section(
            state,
            items,
            [
                "Property discovery release coverage is retained; fixture, stale and partial "
                "coverage is not complete official evidence."
            ]
            if refs
            else ["No shortlisted properties to verify."],
        )

    def _matched_feature(
        self,
        refs: list[str],
        request_id: str,
        *,
        feature: str,
        list_path: str,
        detail_segment: str,
        identifier: str,
        evidence_keys: tuple[str, ...],
    ) -> dict[str, Any]:
        if not refs:
            return self._section("partial", [], ["No shortlisted properties to match."])
        try:
            response = self._get(
                self._origins[feature], list_path, request_id, {"limit": _PAGE_SIZE}
            )
            if response.status_code != 200:
                raise IntegrationUnavailableError("Evidence list unavailable")
            envelope = self._object(response)
            records = envelope.get("items")
            if (
                not isinstance(records, list)
                or len(records) > _PAGE_SIZE
                or any(not isinstance(record, dict) for record in records)
            ):
                raise IntegrationUnavailableError("Evidence list invalid")
            items: list[dict[str, Any]] = []
            for property_ref in refs:
                matches = [
                    item
                    for item in records
                    if isinstance(item, dict) and item.get("property_ref") == property_ref
                ]
                if len(matches) > 1:
                    items.append({"property_ref": property_ref, "state": "conflicting"})
                    continue
                if not matches:
                    items.append({"property_ref": property_ref, "state": "partial"})
                    continue
                record_id = matches[0].get("id")
                if not isinstance(record_id, str):
                    items.append({"property_ref": property_ref, "state": "needs_verification"})
                    continue
                try:
                    uuid.UUID(record_id)
                except ValueError:
                    items.append({"property_ref": property_ref, "state": "needs_verification"})
                    continue
                namespace = "market-intelligence" if feature == "feature_2" else "due-diligence"
                detail = self._get(
                    self._origins[feature],
                    f"/api/{namespace}/v1/{detail_segment}/{record_id}/evidence",
                    request_id,
                )
                if detail.status_code != 200:
                    items.append({"property_ref": property_ref, "state": "unavailable"})
                    continue
                evidence = self._object(detail)
                parent = evidence.get("market_case" if feature == "feature_2" else "site_review")
                if (
                    not isinstance(parent, dict)
                    or parent.get("id") != record_id
                    or parent.get("property_ref") != property_ref
                ):
                    raise IntegrationUnavailableError("Mismatched evidence identity")
                for key in evidence_keys:
                    if not isinstance(evidence.get(key), list) or any(
                        not isinstance(row, dict) or row.get("property_ref") != property_ref
                        for row in evidence[key]
                    ):
                        raise IntegrationUnavailableError("Invalid evidence records")
                rows = [row for key in evidence_keys for row in evidence[key]]
                state = "partial"
                limitations = [
                    "Matching is restricted to the first 25 saved records; "
                    "no match does not mean no evidence exists."
                ]
                if feature == "feature_4":
                    states = [row.get("evidence_state") for row in rows]
                    if any(
                        value
                        not in {"confirmed", "non_intersection", "partial_coverage", "unavailable"}
                        for value in states
                    ):
                        raise IntegrationUnavailableError("Invalid Due diligence state")
                    if states and all(value == "unavailable" for value in states):
                        state = "unavailable"
                    elif all(evidence[key] for key in evidence_keys) and all(
                        value in {"confirmed", "non_intersection"} for value in states
                    ):
                        state = "complete"
                else:
                    summary = evidence.get("summary")
                    if not isinstance(summary, dict) or any(
                        type(summary.get(key)) is not int or summary[key] < 0
                        for key in ("eligible_sale_count", "excluded_sale_count")
                    ):
                        raise IntegrationUnavailableError("Invalid Sales research summary")
                    if not isinstance(summary.get("limitations"), list) or not all(
                        isinstance(text, str) for text in summary["limitations"]
                    ):
                        raise IntegrationUnavailableError("Invalid Sales research limitations")
                    limitations.extend(summary["limitations"][:20])
                    if (
                        summary["eligible_sale_count"] >= 3
                        and summary["excluded_sale_count"] == 0
                        and summary["eligible_sale_count"] <= len(rows)
                        and not any(row.get("synthetic") for row in rows)
                    ):
                        state = "complete"
                if len(records) == _PAGE_SIZE or any(
                    len(evidence[key]) > _PAGE_SIZE for key in evidence_keys
                ):
                    state = "partial" if state == "complete" else state
                    limitations.append("The bounded response may omit additional evidence records.")
                for key in evidence_keys:
                    evidence[key] = evidence[key][:_PAGE_SIZE]
                items.append(
                    {
                        "property_ref": property_ref,
                        "state": state,
                        identifier: record_id,
                        "evidence": evidence,
                        "limitations": limitations,
                    }
                )
            states = [item["state"] for item in items]
            state = (
                "conflicting"
                if "conflicting" in states
                else "needs_verification"
                if "needs_verification" in states
                else "unavailable"
                if states and all(value == "unavailable" for value in states)
                else "complete"
                if states and all(value == "complete" for value in states)
                else "partial"
            )
            return self._section(
                state,
                items,
                [
                    "Only the first 25 saved records are matched by exact property reference; "
                    "this is not an exhaustive search."
                ],
            )
        except IntegrationUnavailableError:
            return self._section(
                "unavailable",
                [],
                [
                    f"{'Sales research' if feature == 'feature_2' else 'Due diligence'} "
                    "is unavailable or returned invalid evidence."
                ],
            )


class AiModeClient:
    """HTTP adapter for the shared AI-mode run API."""

    def __init__(
        self,
        base_url: str,
        *,
        service_token: str = "",
        transport: HttpTransport | None = None,
        timeout_seconds: float = 5,
    ) -> None:
        self._origin = base_url.rstrip("/")
        self._service_token = service_token
        self._transport = transport or UrllibTransport()
        self._timeout = timeout_seconds

    def _request(
        self,
        method: str,
        path: str,
        *,
        request_id: str,
        body: Mapping[str, Any] | None = None,
        idempotency_key: str | None = None,
    ) -> ClientResponse:
        headers = {"X-Request-ID": request_id}
        if self._service_token:
            headers["X-PropertyScope-AI-Token"] = self._service_token
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        try:
            return self._transport.request(
                method,
                f"{self._origin}{path}",
                headers=headers,
                params=None,
                json_body=body,
                timeout_seconds=self._timeout,
            )
        except (DatabaseProtocolError, DatabaseUnavailableError) as exc:
            raise IntegrationUnavailableError("AI-mode unavailable") from exc

    def create_run(
        self, values: Mapping[str, Any], *, request_id: str, idempotency_key: str | None
    ) -> ClientResponse:
        return self._request(
            "POST",
            "/api/v1/agent-runs",
            request_id=request_id,
            body=values,
            idempotency_key=idempotency_key,
        )

    def get_run(self, run_id: str, *, request_id: str) -> ClientResponse:
        return self._request("GET", f"/api/v1/agent-runs/{run_id}", request_id=request_id)

    def get_events(self, run_id: str, *, after: int, request_id: str) -> ClientResponse:
        return self._request(
            "GET",
            f"/api/v1/agent-runs/{run_id}/events?after={after}&limit=100",
            request_id=request_id,
        )

    def cancel_run(self, run_id: str, *, request_id: str) -> ClientResponse:
        return self._request("POST", f"/api/v1/agent-runs/{run_id}/cancel", request_id=request_id)
