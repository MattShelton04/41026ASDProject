"""Public HTTP composition root for the local Features 2-5 integration POC."""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from flask import Flask, Response, g, jsonify, request

from .ai_client import AiModeClient, AiModeUnavailableError
from .configuration import Settings
from .feature1_client import Feature1Client, Feature1ContractError, Feature1HttpError
from .publication_importer import (
    JsonSchemaRecordValidator,
    PublicationConflictError,
    PublicationImporter,
    PublicationImportError,
    contract_friction_notes,
)
from .store_client import StoreHttpClient, StoreHttpError

BASE = "/api/integration-poc/v1"
REQUEST_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
PRODUCTS = (
    ("nsw-psi-sales", "feature-2"),
    ("bocsar-crime", "feature-3"),
    ("nsw-government-schools", "feature-3"),
)
SCHEMA_FILES = {
    "propertyscope.property-snapshot.v1": "property-snapshot.v1.schema.json",
    "propertyscope.property-sales.v2": "property-sales.v2.schema.json",
    "propertyscope.crime-series.v1": "crime-series.v1.schema.json",
    "propertyscope.school-points.v1": "school-points.v1.schema.json",
}
RESOURCES = frozenset({"market-cases", "saved-places", "site-reviews", "buyer-cases"})


def create_app(
    config: Mapping[str, Any] | None = None,
    *,
    settings: Settings | None = None,
    feature1_client: Feature1Client | None = None,
    ai_mode_client: AiModeClient | None = None,
    store_client: StoreHttpClient | None = None,
    importer: PublicationImporter | None = None,
) -> Flask:
    """Create the POC backend with all network and persistence boundaries injected."""
    resolved = settings or Settings.from_environment()
    feature1 = feature1_client or Feature1Client(resolved.feature1_origin)
    ai_mode = ai_mode_client or AiModeClient(resolved.ai_mode_origin)
    store = store_client or StoreHttpClient(
        resolved.store_origin,
        resolved.internal_token,
        connect_timeout_seconds=resolved.store_connect_timeout_seconds,
        read_timeout_seconds=resolved.store_read_timeout_seconds,
        write_timeout_seconds=resolved.store_write_timeout_seconds,
        pool_timeout_seconds=resolved.store_pool_timeout_seconds,
    )
    publication_importer = importer or PublicationImporter(
        feature1,
        store,
        JsonSchemaRecordValidator(_load_schemas(resolved.contract_root)),
        maximum_artifact_bytes=resolved.maximum_artifact_bytes,
        maximum_legacy_json_bytes=resolved.maximum_legacy_json_bytes,
    )
    app = Flask(__name__)
    app.config.from_mapping(MAX_CONTENT_LENGTH=262_144)
    if config:
        app.config.update(config)
    app.extensions.update(
        feature1_client=feature1,
        ai_mode_client=ai_mode,
        integration_store_client=store,
        publication_importer=publication_importer,
    )

    @app.before_request
    def establish_request_id() -> None:
        supplied = request.headers.get("X-Request-ID", "")
        g.request_id = supplied if REQUEST_ID.fullmatch(supplied) else str(uuid.uuid4())

    @app.after_request
    def attach_request_id(response: Response) -> Response:
        response.headers["X-Request-ID"] = g.request_id
        return response

    @app.errorhandler(PublicationConflictError)
    def publication_conflict(error: PublicationConflictError) -> tuple[Response, int]:
        return _problem(409, "Publication conflict", str(error)), 409

    @app.errorhandler(PublicationImportError)
    @app.errorhandler(Feature1ContractError)
    @app.errorhandler(ValueError)
    def invalid_request(error: Exception) -> tuple[Response, int]:
        return _problem(422, "Unprocessable Content", str(error)), 422

    @app.errorhandler(Feature1HttpError)
    def provider_error(error: Feature1HttpError) -> tuple[Response, int]:
        status = error.status_code if error.status_code in {404, 409, 422} else 503
        return _problem(status, "Feature 1 dependency failure", error.detail), status

    @app.errorhandler(StoreHttpError)
    def store_error(error: StoreHttpError) -> tuple[Response, int]:
        status = error.status_code if error.status_code in {400, 404, 409, 422} else 503
        return _problem(status, "POC store dependency failure", error.detail), status

    @app.errorhandler(AiModeUnavailableError)
    def ai_mode_error(error: AiModeUnavailableError) -> tuple[Response, int]:
        return _problem(error.status_code, "AI mode unavailable", error.detail), error.status_code

    @app.get("/health/live")
    def live() -> Response:
        return jsonify({"status": "ok", "service": "feature-6-integration-poc"})

    @app.get("/health/ready")
    def ready() -> tuple[Response, int] | Response:
        store_ready = store.ready(headers=_forward_headers())
        provider = _provider_projection(feature1, store_ready=store_ready)
        ai_readiness = ai_mode.readiness()
        payload = {
            "status": "ready" if store_ready else "not_ready",
            "service": "feature-6-integration-poc",
            "store_ready": store_ready,
            "provider_state": provider["feature_1"]["state"],
            "ai_mode_state": ai_readiness["state"],
            "deterministic_crud_available": store_ready,
        }
        if store_ready:
            return jsonify(payload)
        return jsonify(payload), 503

    @app.post("/api/data-import/v1/propertyscope-releases")
    def publication_callback() -> Response:
        key = request.headers.get("Idempotency-Key", "").strip()
        receipt = publication_importer.import_callback(
            _body(), header_idempotency_key=key, headers=_forward_headers()
        )
        return jsonify(receipt.as_dict())

    @app.get(f"{BASE}/provider/status")
    def provider_status() -> Response:
        projection = _provider_projection(
            feature1, store_ready=store.ready(headers=_forward_headers())
        )
        projection["ai_mode"] = ai_mode.readiness()
        return jsonify(projection)

    @app.get(f"{BASE}/imports")
    def imports() -> Response:
        return jsonify(store.list_imports(headers=_forward_headers()))

    @app.post(f"{BASE}/imports/reconcile")
    def reconcile_imports() -> Response:
        body = _optional_body()
        selected = _selected_products(body)
        results: list[dict[str, Any]] = []
        for dataset_id, target_feature in selected:
            try:
                receipt = publication_importer.reconcile_accepted(
                    dataset_id, target_feature, headers=_forward_headers()
                )
                if receipt is None:
                    results.append(
                        {
                            "dataset_id": dataset_id,
                            "target_feature": target_feature,
                            "state": "unavailable",
                            "detail": "No accepted Feature 1 release is available.",
                        }
                    )
                else:
                    results.append(
                        {
                            "dataset_id": dataset_id,
                            "target_feature": target_feature,
                            "state": "complete",
                            "receipt": receipt.as_dict(),
                        }
                    )
            except (Feature1HttpError, Feature1ContractError, PublicationImportError) as exc:
                results.append(
                    {
                        "dataset_id": dataset_id,
                        "target_feature": target_feature,
                        "state": "unavailable",
                        "detail": str(exc),
                    }
                )
        return jsonify({"items": results, "count": len(results)})

    @app.get(f"{BASE}/properties/search")
    def property_search() -> Response:
        if set(request.args) - {"q", "limit"}:
            raise ValueError("property search contains unknown query fields")
        query = request.args.get("q", "").strip()
        if not 2 <= len(query) <= 200:
            raise ValueError("property search query must contain 2 to 200 characters")
        try:
            limit = int(request.args.get("limit", "25"))
        except ValueError as exc:
            raise ValueError("property search limit must be an integer") from exc
        return jsonify(feature1.property_search(query, limit=limit, headers=_forward_headers()))

    @app.get(f"{BASE}/properties/<uuid:property_ref>/research")
    def property_research(property_ref: uuid.UUID) -> Response:
        return jsonify(_compose_research(property_ref, feature1, store, _forward_headers()))

    @app.post(f"{BASE}/agent-runs")
    def create_agent_run() -> tuple[Response, int]:
        body = _body()
        if set(body) != {"property_ref", "question"}:
            raise ValueError("AI research requires exactly property_ref and question")
        try:
            property_ref = uuid.UUID(str(body["property_ref"]))
        except (KeyError, ValueError) as exc:
            raise ValueError("property_ref must be a UUID") from exc
        run = ai_mode.create_research_run(
            property_ref,
            str(body["question"]),
            idempotency_key=request.headers.get("Idempotency-Key", "").strip(),
            headers=_forward_headers(),
        )
        return jsonify({"ai_state": "queued", "run": run}), 202

    @app.get(f"{BASE}/agent-runs/<uuid:run_id>")
    def get_agent_run(run_id: uuid.UUID) -> Response:
        return jsonify(ai_mode.get_run(run_id, headers=_forward_headers()))

    @app.post(f"{BASE}/tools/research.compose.v1")
    def tool_research() -> Response:
        body = _body()
        if set(body) != {"property_ref"}:
            raise ValueError("research tool requires exactly property_ref")
        try:
            property_ref = uuid.UUID(str(body["property_ref"]))
        except (KeyError, ValueError) as exc:
            raise ValueError("property_ref must be a UUID") from exc
        composition = _compose_research(property_ref, feature1, store, _forward_headers())
        return jsonify(
            {
                key: composition[key]
                for key in ("property_ref", "identity", "sections", "limitations")
            }
        )

    @app.post(f"{BASE}/tools/provider.readiness.v1")
    def tool_readiness() -> Response:
        if _body():
            raise ValueError("provider readiness tool takes an empty object")
        projection = _provider_projection(
            feature1, store_ready=store.ready(headers=_forward_headers())
        )
        ai_readiness = ai_mode.readiness()
        return jsonify(
            {
                "feature_1": projection["feature_1"],
                "store": projection["store"],
                "catalogue": projection["catalogue"],
                "poc": {
                    "ai_mode_ready": ai_readiness["ready"],
                    "ai_mode_state": ai_readiness["state"],
                    "friction": projection["friction"],
                },
            }
        )

    @app.route(f"{BASE}/<resource>", methods=["GET", "POST"])
    def resource_collection(resource: str) -> Response | tuple[Response, int]:
        _public_resource(resource)
        if request.method == "GET":
            return jsonify(store.collection(resource, headers=_forward_headers()))
        payload = _normalise_create(resource, _body())
        return jsonify(
            store.collection(
                resource,
                method="POST",
                body=payload,
                headers=_forward_headers(),
            )
        ), 201

    @app.route(f"{BASE}/<resource>/<uuid:item_id>", methods=["GET", "PATCH", "DELETE"])
    def resource_item(resource: str, item_id: uuid.UUID) -> Response:
        _public_resource(resource)
        if request.method == "GET":
            return jsonify(_find_resource(store, resource, item_id, _forward_headers()))
        if request.method == "PATCH":
            body = _body()
            if not isinstance(body.get("expected_version"), int):
                raise ValueError("expected_version is required for updates")
            result = store.mutate_item(
                resource,
                item_id,
                method="PATCH",
                body=body,
                headers=_forward_headers(),
            )
            return jsonify(result)
        version = _delete_version(store, resource, item_id, _forward_headers())
        store.mutate_item(
            resource,
            item_id,
            method="DELETE",
            expected_version=version,
            headers=_forward_headers(),
        )
        return Response(status=204)

    return app


def _provider_projection(feature1: Feature1Client, *, store_ready: bool) -> dict[str, Any]:
    try:
        catalogue = feature1.catalogue()
        feature_state = {
            "ready": True,
            "state": "complete",
            "detail": "Feature 1 public catalogue is reachable.",
        }
    except (Feature1HttpError, Feature1ContractError) as exc:
        catalogue = {"items": [], "count": 0, "next_cursor": None}
        feature_state = {
            "ready": False,
            "state": "unavailable",
            "detail": str(exc),
        }
    return {
        "schema_version": "propertyscope.integration-poc-readiness.v1",
        "poc": {
            "claim": "local-only integration experiment",
            "feature_registry_changed": False,
            "deterministic_crud_available": store_ready,
        },
        "feature_1": feature_state,
        "store": {"ready": store_ready, "state": "complete" if store_ready else "unavailable"},
        "catalogue": catalogue,
        "friction": list(contract_friction_notes()),
    }


def _compose_research(
    property_ref: uuid.UUID,
    feature1: Feature1Client,
    store: StoreHttpClient,
    headers: Mapping[str, str],
) -> dict[str, Any]:
    sections: dict[str, dict[str, Any]] = {}
    identity: Mapping[str, Any] = {"property_ref": str(property_ref)}
    try:
        report = feature1.report_section(property_ref, headers=headers)
        identity = {
            "property_ref": str(property_ref),
            "address_display": report.get("address_display"),
            **dict(report.get("identity", {})),
        }
        sections["property_identity"] = {
            "state": "complete",
            "summary": "Canonical Feature 1 identity and accepted-release coverage.",
            "evidence": report,
        }
    except (Feature1HttpError, Feature1ContractError) as exc:
        sections["property_identity"] = {
            "state": "unavailable",
            "summary": "Feature 1 property identity is unavailable.",
            "detail": str(exc),
        }

    sections["market"] = _market_section(store, property_ref, headers)
    sections["place"] = _place_section(store, identity, headers)
    sections["site_due_diligence"] = _site_section(store, property_ref, headers)
    states = {section["state"] for section in sections.values()}
    overall = (
        "needs_verification"
        if "needs_verification" in states
        else "partial"
        if "partial" in states or "unavailable" in states
        else "complete"
    )
    return {
        "schema_version": "propertyscope.integration-poc-research.v1",
        "property_ref": str(property_ref),
        "state": overall,
        "identity": identity,
        "sections": sections,
        "limitations": [
            "This POC composes evidence; it does not estimate value or recommend whether to buy.",
            "Unavailable provider evidence is preserved rather than inferred.",
        ],
    }


def _market_section(
    store: StoreHttpClient, property_ref: uuid.UUID, headers: Mapping[str, str]
) -> dict[str, Any]:
    try:
        cases = _items(store.collection("market-cases", headers=headers))
        relevant = [item for item in cases if item.get("property_ref") == str(property_ref)]
        summaries = [
            store.market_summary(uuid.UUID(str(item["id"])), headers=headers) for item in relevant
        ]
        has_sales = any(int(item.get("selected_transaction_count", 0)) > 0 for item in summaries)
        return {
            "state": "complete" if has_sales else "partial",
            "summary": (
                "Imported sales evidence is available for a saved market case."
                if has_sales
                else "No saved market case has matching imported sales evidence."
            ),
            "cases": relevant,
            "summaries": summaries,
        }
    except StoreHttpError as exc:
        return {
            "state": "unavailable",
            "summary": "Sales evidence is unavailable.",
            "detail": str(exc),
        }


def _place_section(
    store: StoreHttpClient, identity: Mapping[str, Any], headers: Mapping[str, str]
) -> dict[str, Any]:
    postcode = identity.get("postcode")
    if not isinstance(postcode, str):
        return {
            "state": "unavailable",
            "summary": "A verified postcode is required for place evidence.",
        }
    latitude = identity.get("latitude")
    longitude = identity.get("longitude")
    try:
        summary = store.place_summary(
            postcode,
            latitude=float(latitude) if isinstance(latitude, int | float) else None,
            longitude=float(longitude) if isinstance(longitude, int | float) else None,
            headers=headers,
        )
        has_evidence = bool(summary.get("crime_series") or summary.get("nearby_schools"))
        return {
            "state": "complete" if has_evidence else "partial",
            "summary": (
                "Imported postcode crime and/or school evidence is available."
                if has_evidence
                else "No accepted crime or school product has supplied evidence for this place."
            ),
            "evidence": summary,
        }
    except StoreHttpError as exc:
        return {
            "state": "unavailable",
            "summary": "Place evidence is unavailable.",
            "detail": str(exc),
        }


def _site_section(
    store: StoreHttpClient, property_ref: uuid.UUID, headers: Mapping[str, str]
) -> dict[str, Any]:
    try:
        reviews = _items(store.collection("site-reviews", headers=headers))
        relevant = [item for item in reviews if item.get("property_ref") == str(property_ref)]
        evidence = [
            store.site_evidence(uuid.UUID(str(item["id"])), headers=headers) for item in relevant
        ]
        return {
            "state": "needs_verification",
            "summary": "Planning, hazard, strata and building products are not registered.",
            "reviews": relevant,
            "evidence": evidence,
        }
    except StoreHttpError as exc:
        return {
            "state": "unavailable",
            "summary": "Site review workspace is unavailable.",
            "detail": str(exc),
        }


def _load_schemas(root: Path) -> dict[str, Mapping[str, Any]]:
    schemas: dict[str, Mapping[str, Any]] = {}
    for version, filename in SCHEMA_FILES.items():
        try:
            value = json.loads((root / filename).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"provider contract is unavailable or invalid: {filename}") from exc
        if not isinstance(value, Mapping):
            raise ValueError(f"provider contract must be an object: {filename}")
        schemas[version] = value
    return schemas


def _selected_products(body: Mapping[str, Any]) -> tuple[tuple[str, str], ...]:
    if not body:
        return PRODUCTS
    if set(body) != {"dataset_ids"} or not isinstance(body["dataset_ids"], list):
        raise ValueError("reconciliation accepts only a dataset_ids array")
    requested = set(body["dataset_ids"])
    if not all(isinstance(value, str) for value in requested):
        raise ValueError("dataset_ids must contain strings")
    selected = tuple(item for item in PRODUCTS if item[0] in requested)
    if len(selected) != len(requested):
        raise ValueError("reconciliation contains an unsupported dataset")
    return selected


def _normalise_create(resource: str, body: Mapping[str, Any]) -> dict[str, Any]:
    values = dict(body)
    title = str(values.pop("title", "")).strip()
    context = str(values.pop("context", "")).strip()
    if resource == "market-cases":
        if title:
            values.setdefault("name", title)
    elif resource == "saved-places":
        values.setdefault("actor_ref", "local-poc-user")
        if title:
            values.setdefault("locality", title)
        if context:
            values.setdefault("postcode", context)
    elif resource == "site-reviews":
        if title:
            values.setdefault("name", title)
    elif resource == "buyer-cases":
        values.setdefault("actor_ref", "local-poc-user")
        if title:
            values.setdefault("name", title)
        if context:
            values.setdefault("target_suburbs", [context])
    return values


def _find_resource(
    store: StoreHttpClient,
    resource: str,
    item_id: uuid.UUID,
    headers: Mapping[str, str],
) -> Mapping[str, Any]:
    item = next(
        (
            item
            for item in _items(store.collection(resource, headers=headers))
            if item.get("id") == str(item_id)
        ),
        None,
    )
    if item is None:
        raise StoreHttpError(404, f"{resource} record was not found")
    return item


def _delete_version(
    store: StoreHttpClient,
    resource: str,
    item_id: uuid.UUID,
    headers: Mapping[str, str],
) -> int:
    supplied = request.args.get("expected_version")
    if supplied is not None:
        try:
            version = int(supplied)
        except ValueError as exc:
            raise ValueError("expected_version must be an integer") from exc
        if version < 1:
            raise ValueError("expected_version must be positive")
        return version
    item = _find_resource(store, resource, item_id, headers)
    retained_version = item.get("version")
    if not isinstance(retained_version, int) or retained_version < 1:
        raise StoreHttpError(502, "store record has no valid version")
    return retained_version


def _items(payload: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    value = payload.get("items")
    if not isinstance(value, list) or not all(isinstance(item, Mapping) for item in value):
        raise StoreHttpError(502, "store collection response is malformed")
    return value


def _public_resource(resource: str) -> None:
    if resource not in RESOURCES:
        raise StoreHttpError(404, "POC resource route was not found")


def _body() -> Mapping[str, Any]:
    value = request.get_json(silent=True)
    if not isinstance(value, Mapping):
        raise ValueError("request body must be a JSON object")
    return value


def _forward_headers() -> dict[str, str]:
    return dict(request.headers.items())


def _optional_body() -> Mapping[str, Any]:
    if not request.data:
        return {}
    return _body()


def _problem(status: int, title: str, detail: str) -> Response:
    response = jsonify(
        {
            "type": "about:blank",
            "title": title,
            "status": status,
            "detail": detail,
            "instance": request.path,
            "request_id": g.request_id,
        }
    )
    response.status_code = status
    response.content_type = "application/problem+json"
    return response
