"""Private Flask API for the Feature 6 POC's single-owner database service."""

from __future__ import annotations

import json
import os
import re
import uuid
from collections.abc import Iterator, Mapping
from typing import Any

from flask import Flask, Response, g, jsonify, request

from .errors import ConflictError, NotFoundError, StoreError, ValidationError
from .repository import IntegrationStore

REQUEST_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


def create_app(
    config: Mapping[str, Any] | None = None, *, store: IntegrationStore | None = None
) -> Flask:
    """Create an injected private database API without hidden external access."""
    app = Flask(__name__)
    app.config.from_mapping(
        DATABASE_PATH=os.environ.get(
            "PROPERTYSCOPE_F6_DATABASE_PATH", "instance/feature-6-poc.sqlite3"
        ),
        INTERNAL_TOKEN=os.environ.get(
            "PROPERTYSCOPE_F6_INTERNAL_TOKEN", "propertyscope-f6-local-only"
        ),
    )
    if config:
        app.config.update(config)
    repository = store or IntegrationStore(str(app.config["DATABASE_PATH"]))
    repository.initialise()
    app.extensions["integration_store"] = repository

    @app.before_request
    def establish_request() -> Response | None:
        supplied = request.headers.get("X-Request-ID", "")
        g.request_id = supplied if REQUEST_ID.fullmatch(supplied) else str(uuid.uuid4())
        if request.path.startswith("/internal/v1"):
            expected = str(app.config["INTERNAL_TOKEN"])
            if request.headers.get("Authorization") != f"Bearer {expected}":
                return _problem(401, "Unauthorized", "A valid internal service token is required.")
        return None

    @app.after_request
    def attach_request_id(response: Response) -> Response:
        response.headers["X-Request-ID"] = g.request_id
        return response

    @app.errorhandler(ValidationError)
    def validation_problem(error: ValidationError) -> tuple[Response, int]:
        return _problem(422, "Unprocessable Content", str(error)), 422

    @app.errorhandler(NotFoundError)
    def missing_problem(error: NotFoundError) -> tuple[Response, int]:
        return _problem(404, "Not Found", str(error)), 404

    @app.errorhandler(ConflictError)
    def conflict_problem(error: ConflictError) -> tuple[Response, int]:
        return _problem(409, "Conflict", str(error)), 409

    @app.errorhandler(StoreError)
    def store_problem(error: StoreError) -> tuple[Response, int]:
        return _problem(500, "Store Error", str(error)), 500

    @app.errorhandler(404)
    def route_missing(_error: Exception) -> tuple[Response, int]:
        return _problem(404, "Not Found", "The requested private API route was not found."), 404

    @app.errorhandler(405)
    def method_not_allowed(_error: Exception) -> tuple[Response, int]:
        return _problem(405, "Method Not Allowed", "This route does not support the method."), 405

    @app.get("/health/live")
    def live() -> Response:
        return jsonify({"status": "ok", "service": "feature-6-poc-database"})

    @app.get("/health/ready")
    def ready() -> tuple[Response, int] | Response:
        if repository.ready():
            return jsonify({"status": "ready", "service": "feature-6-poc-database"})
        return _problem(503, "Not Ready", "The owned database schema is unavailable."), 503

    @app.get("/internal/v1/imports")
    def list_imports() -> Response:
        items = repository.list_imports()
        return jsonify({"items": items, "count": len(items)})

    @app.post("/internal/v1/imports")
    def import_release() -> tuple[Response, int]:
        if request.mimetype == "application/x-ndjson":
            body, records = _streamed_import()
        else:
            body = _body()
            array = body.get("records")
            if not isinstance(array, list) or not all(isinstance(item, Mapping) for item in array):
                raise ValidationError("records must be an array of objects")
            if len(array) > 1_000:
                raise ValidationError(
                    "JSON-array imports are capped at 1000 records; use application/x-ndjson"
                )
            records = iter(array)
        release_id = body.get("release_id", body.get("provider_release_id"))
        request_evidence = {
            key: value
            for key, value in body.items()
            if key not in {"records", "provider_release_id"}
        }
        request_evidence["release_id"] = release_id
        receipt = repository.import_release(
            target_feature=str(body.get("target_feature") or ""),
            idempotency_key=str(body.get("idempotency_key") or ""),
            provider_release_id=str(release_id or ""),
            dataset_id=str(body.get("dataset_id") or ""),
            schema_version=str(body.get("schema_version") or ""),
            content_sha256=str(body.get("content_sha256") or ""),
            record_count=_required_nonnegative_int(body.get("record_count"), "record_count"),
            records=records,
            request_evidence=request_evidence,
        )
        return jsonify(receipt), 200 if receipt["replayed"] else 201

    @app.get("/internal/v1/imports/<target_feature>/<idempotency_key>")
    def find_import(target_feature: str, idempotency_key: str) -> Response:
        return jsonify(repository.find_import(target_feature, idempotency_key))

    @app.get("/internal/v1/market-cases")
    def market_cases() -> Response:
        items = repository.list_market_cases()
        return jsonify({"items": items, "count": len(items)})

    @app.post("/internal/v1/market-cases")
    def create_market_case() -> tuple[Response, int]:
        return jsonify(repository.create_market_case(_body())), 201

    @app.get("/internal/v1/market-cases/<case_id>")
    def get_market_case(case_id: str) -> Response:
        return jsonify(repository.get_market_case(case_id))

    @app.patch("/internal/v1/market-cases/<case_id>")
    def update_market_case(case_id: str) -> Response:
        body = _body()
        version = _version(body)
        return jsonify(repository.update_market_case(case_id, version, _without_version(body)))

    @app.delete("/internal/v1/market-cases/<case_id>")
    def delete_market_case(case_id: str) -> tuple[str, int]:
        repository.delete_market_case(case_id, _query_version())
        return "", 204

    @app.get("/internal/v1/market-cases/<case_id>/summary")
    def market_summary(case_id: str) -> Response:
        return jsonify(repository.sales_summary(case_id))

    @app.get("/internal/v1/saved-places")
    def saved_places() -> Response:
        items = repository.list_saved_places()
        return jsonify({"items": items, "count": len(items)})

    @app.post("/internal/v1/saved-places")
    def create_saved_place() -> tuple[Response, int]:
        return jsonify(repository.create_saved_place(_body())), 201

    @app.get("/internal/v1/saved-places/<place_id>")
    def get_saved_place(place_id: str) -> Response:
        return jsonify(repository.get_saved_place(place_id))

    @app.patch("/internal/v1/saved-places/<place_id>")
    def update_saved_place(place_id: str) -> Response:
        body = _body()
        return jsonify(
            repository.update_saved_place(place_id, _version(body), _without_version(body))
        )

    @app.delete("/internal/v1/saved-places/<place_id>")
    def delete_saved_place(place_id: str) -> tuple[str, int]:
        repository.delete_saved_place(place_id, _query_version())
        return "", 204

    @app.get("/internal/v1/places/<postcode>/summary")
    def place_summary(postcode: str) -> Response:
        latitude = _optional_float(request.args.get("latitude"), "latitude")
        longitude = _optional_float(request.args.get("longitude"), "longitude")
        if (latitude is None) != (longitude is None):
            raise ValidationError("latitude and longitude must be supplied together")
        if latitude is not None and not -90 <= latitude <= 90:
            raise ValidationError("latitude is outside WGS84 bounds")
        return jsonify(repository.place_summary(postcode, latitude=latitude, longitude=longitude))

    @app.get("/internal/v1/site-reviews")
    def site_reviews() -> Response:
        items = repository.list_site_reviews()
        return jsonify({"items": items, "count": len(items)})

    @app.post("/internal/v1/site-reviews")
    def create_site_review() -> tuple[Response, int]:
        return jsonify(repository.create_site_review(_body())), 201

    @app.get("/internal/v1/site-reviews/<review_id>")
    def get_site_review(review_id: str) -> Response:
        return jsonify(repository.get_site_review(review_id))

    @app.patch("/internal/v1/site-reviews/<review_id>")
    def update_site_review(review_id: str) -> Response:
        body = _body()
        return jsonify(
            repository.update_site_review(review_id, _version(body), _without_version(body))
        )

    @app.delete("/internal/v1/site-reviews/<review_id>")
    def delete_site_review(review_id: str) -> tuple[str, int]:
        repository.delete_site_review(review_id, _query_version())
        return "", 204

    @app.get("/internal/v1/site-reviews/<review_id>/items")
    def site_items(review_id: str) -> Response:
        items = repository.list_site_items(review_id)
        return jsonify({"items": items, "count": len(items)})

    @app.post("/internal/v1/site-reviews/<review_id>/items")
    def create_site_item(review_id: str) -> tuple[Response, int]:
        return jsonify(repository.add_site_item(review_id, _body())), 201

    @app.patch("/internal/v1/site-review-items/<item_id>")
    def update_site_item(item_id: str) -> Response:
        body = _body()
        return jsonify(repository.update_site_item(item_id, _version(body), _without_version(body)))

    @app.delete("/internal/v1/site-review-items/<item_id>")
    def delete_site_item(item_id: str) -> tuple[str, int]:
        repository.delete_site_item(item_id, _query_version())
        return "", 204

    @app.get("/internal/v1/site-reviews/<review_id>/evidence")
    def site_evidence(review_id: str) -> Response:
        return jsonify(repository.site_evidence(review_id))

    @app.get("/internal/v1/buyer-cases")
    def buyer_cases() -> Response:
        items = repository.list_buyer_cases()
        return jsonify({"items": items, "count": len(items)})

    @app.post("/internal/v1/buyer-cases")
    def create_buyer_case() -> tuple[Response, int]:
        return jsonify(repository.create_buyer_case(_body())), 201

    @app.get("/internal/v1/buyer-cases/<case_id>")
    def get_buyer_case(case_id: str) -> Response:
        return jsonify(repository.get_buyer_case(case_id))

    @app.patch("/internal/v1/buyer-cases/<case_id>")
    def update_buyer_case(case_id: str) -> Response:
        body = _body()
        return jsonify(
            repository.update_buyer_case(case_id, _version(body), _without_version(body))
        )

    @app.delete("/internal/v1/buyer-cases/<case_id>")
    def delete_buyer_case(case_id: str) -> tuple[str, int]:
        repository.delete_buyer_case(case_id, _query_version())
        return "", 204

    @app.get("/internal/v1/buyer-cases/<case_id>/<kind>")
    def buyer_children(case_id: str, kind: str) -> Response:
        items = repository.list_case_children(case_id, kind)
        return jsonify({"items": items, "count": len(items)})

    @app.post("/internal/v1/buyer-cases/<case_id>/<kind>")
    def create_buyer_child(case_id: str, kind: str) -> tuple[Response, int]:
        functions = {
            "properties": repository.add_case_property,
            "notes": repository.add_case_note,
            "tasks": repository.add_case_task,
        }
        operation = functions.get(kind)
        if operation is None:
            raise NotFoundError("buyer case child route was not found")
        return jsonify(operation(case_id, _body())), 201

    @app.patch("/internal/v1/buyer-case-children/<kind>/<child_id>")
    def update_buyer_child(kind: str, child_id: str) -> Response:
        body = _body()
        return jsonify(
            repository.update_case_child(kind, child_id, _version(body), _without_version(body))
        )

    @app.delete("/internal/v1/buyer-case-children/<kind>/<child_id>")
    def delete_buyer_child(kind: str, child_id: str) -> tuple[str, int]:
        repository.delete_case_child(kind, child_id, _query_version())
        return "", 204

    @app.get("/internal/v1/buyer-cases/<case_id>/evidence-summary")
    def buyer_summary(case_id: str) -> Response:
        return jsonify(repository.buyer_summary(case_id))

    return app


def _body() -> Mapping[str, Any]:
    value = request.get_json(silent=True)
    if not isinstance(value, Mapping):
        raise ValidationError("request body must be a JSON object")
    return value


def _streamed_import() -> tuple[Mapping[str, Any], Iterator[Mapping[str, Any]]]:
    """Read one metadata line and lazily yield bounded NDJSON record lines."""
    lines = _nonblank_ndjson_lines()
    try:
        first = next(lines)
    except StopIteration as exc:
        raise ValidationError("NDJSON import stream is empty") from exc
    if (
        not isinstance(first, Mapping)
        or set(first) != {"publication"}
        or not isinstance(first["publication"], Mapping)
    ):
        raise ValidationError("first NDJSON line must contain exactly one publication object")
    publication = first["publication"]

    def records() -> Iterator[Mapping[str, Any]]:
        for line in lines:
            if not isinstance(line, Mapping):
                raise ValidationError("each NDJSON record line must be an object")
            yield line

    return publication, records()


def _nonblank_ndjson_lines() -> Iterator[Any]:
    for raw_line in request.stream:
        if not raw_line.strip():
            continue
        if len(raw_line) > 1_048_576:
            raise ValidationError("NDJSON line exceeds the 1 MiB POC bound")
        try:
            yield json.loads(raw_line)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValidationError("NDJSON import contains malformed JSON") from exc


def _version(body: Mapping[str, Any]) -> int:
    value = body.get("expected_version")
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValidationError("expected_version must be a positive integer")
    return value


def _query_version() -> int:
    try:
        version = int(request.args.get("expected_version", ""))
    except ValueError as exc:
        raise ValidationError("expected_version must be a positive integer") from exc
    if version < 1:
        raise ValidationError("expected_version must be a positive integer")
    return version


def _without_version(body: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in body.items() if key != "expected_version"}


def _optional_float(value: str | None, field: str) -> float | None:
    if value is None:
        return None
    try:
        result = float(value)
    except ValueError as exc:
        raise ValidationError(f"{field} must be a number") from exc
    if not -180 <= result <= 180:
        raise ValidationError(f"{field} is outside supported coordinate bounds")
    return result


def _required_nonnegative_int(value: object, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValidationError(f"{field} must be a non-negative integer")
    return value


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
