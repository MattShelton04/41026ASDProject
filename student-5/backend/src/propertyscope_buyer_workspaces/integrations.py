"""Bounded public-feature evidence and shared AI-mode HTTP adapters."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Protocol

from propertyscope_buyer_workspaces.clients import (
    ClientResponse,
    DatabaseProtocolError,
    DatabaseUnavailableError,
    HttpTransport,
    UrllibTransport,
)

_MAX_PROPERTIES = 10
_PAGE_SIZE = 25


class IntegrationUnavailableError(RuntimeError):
    """A public feature or AI-mode cannot currently be reached."""


class EvidenceGateway(Protocol):
    def collect(self, property_refs: Sequence[str], *, request_id: str) -> dict[str, Any]: ...

    def validate_property(self, property_ref: str, *, request_id: str) -> dict[str, str]: ...


class AiModeGateway(Protocol):
    def create_run(
        self, values: Mapping[str, Any], *, request_id: str, idempotency_key: str | None
    ) -> ClientResponse: ...

    def get_run(self, run_id: str, *, request_id: str) -> ClientResponse: ...


class PublicEvidenceClient:
    """Collect small evidence projections without importing another feature."""

    def __init__(
        self,
        data_platform_url: str,
        market_intelligence_url: str,
        due_diligence_url: str,
        *,
        transport: HttpTransport | None = None,
        timeout_seconds: float = 4,
    ) -> None:
        self._origins = {
            "feature_1": data_platform_url.rstrip("/"),
            "feature_2": market_intelligence_url.rstrip("/"),
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

    def collect(self, property_refs: Sequence[str], *, request_id: str) -> dict[str, Any]:
        refs = list(dict.fromkeys(property_refs))[:_MAX_PROPERTIES]
        sections = {
            "feature_1": self._feature_one(refs, request_id),
            "feature_2": self._matched_feature(
                refs,
                request_id,
                feature="feature_2",
                list_path="/api/market-intelligence/v1/market-cases",
                detail_segment="market-cases",
                identifier="market_case_id",
                evidence_keys=("sales",),
            ),
            "feature_3": self._section(
                "unavailable", [], ["Feature 3 has no available Release 0 public API."]
            ),
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
        return {
            "state": overall,
            "sections": sections,
            "evidence_references": list(dict.fromkeys(references))[:50],
            "limitations": [
                "Evidence is bounded to 10 shortlisted properties and the first 25 "
                "matching records per feature.",
                "Feature 3 is unavailable and is not inferred from other sources.",
            ],
        }

    @staticmethod
    def _section(state: str, items: list[dict[str, Any]], limitations: list[str]) -> dict[str, Any]:
        return {"state": state, "items": items, "limitations": limitations}

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
                    items.append({"property_ref": property_ref, "state": "needs_verification"})
                    continue
                value = self._object(response)
                identity = value.get("identity")
                resolution = (
                    identity.get("resolution_status") if isinstance(identity, dict) else None
                )
                states = {
                    "verified": "complete" if value.get("release_evidence") else "partial",
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
        return self._section(state, items, [] if refs else ["No shortlisted properties to verify."])

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
                self._origins[feature], list_path, request_id, {"page": 1, "page_size": _PAGE_SIZE}
            )
            if response.status_code != 200:
                raise IntegrationUnavailableError("Evidence list unavailable")
            envelope = self._object(response)
            records = envelope.get("items")
            if not isinstance(records, list):
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
                populated = any(
                    isinstance(evidence.get(key), list) and evidence[key] for key in evidence_keys
                )
                items.append(
                    {
                        "property_ref": property_ref,
                        "state": "complete" if populated else "partial",
                        identifier: record_id,
                        "evidence": evidence,
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
            return self._section(state, items, [])
        except IntegrationUnavailableError:
            return self._section(
                "unavailable", [], [f"{feature.replace('_', ' ').title()} is unavailable."]
            )


class AiModeClient:
    """HTTP adapter for the shared AI-mode run API."""

    def __init__(
        self, base_url: str, *, transport: HttpTransport | None = None, timeout_seconds: float = 5
    ) -> None:
        self._origin = base_url.rstrip("/")
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
