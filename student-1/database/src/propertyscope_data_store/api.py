"""Internal HTTP API for Feature 1 persistence and leases."""

from __future__ import annotations

import uuid
from typing import Any

from flask import Blueprint, Response, current_app, jsonify, request

from propertyscope_data_store.errors import (
    ConflictError,
    NotFoundError,
    StoreError,
    ValidationError,
)
from propertyscope_data_store.repository import PropertyScopeStore


def create_blueprint(store: PropertyScopeStore, *, internal_token: str) -> Blueprint:
    """Build the private database API around its injected store."""
    api = Blueprint("propertyscope-data-store", __name__)

    @api.before_request
    def authenticate() -> Response | None:
        if request.path.startswith("/health/"):
            return None
        if request.headers.get("X-PropertyScope-Internal-Token") != internal_token:
            return problem(401, "unauthorised", "A valid internal service credential is required")
        return None

    @api.get("/health/live")
    def live() -> tuple[Response, int]:
        return jsonify({"status": "healthy", "service": "feature-1-database-api"}), 200

    @api.get("/health/ready")
    def ready() -> tuple[Response, int]:
        healthy = store.ready()
        return jsonify({"status": "healthy" if healthy else "unhealthy"}), 200 if healthy else 503

    @api.get("/internal/data-platform/v1/overview")
    def overview() -> Response:
        return jsonify(store.overview())

    @api.get("/internal/data-platform/v1/schema/counts")
    def counts() -> Response:
        return jsonify({"tables": store.counts()})

    @api.get("/internal/data-platform/v1/schema/fingerprint")
    def fingerprint() -> Response:
        return jsonify({"algorithm": "sha256", "fingerprint": store.fingerprint()})

    @api.get("/internal/data-platform/v1/sources")
    def sources_list() -> Response:
        limit, offset = pagination()
        items = store.list_sources(
            status=request.args.get("status"),
            query_text=optional_query_text(),
            limit=limit,
            offset=offset,
        )
        return jsonify(envelope(items, limit=limit, offset=offset))

    @api.post("/internal/data-platform/v1/sources")
    def sources_create() -> tuple[Response, int]:
        return jsonify({"source": store.create_source(payload())}), 201

    @api.get("/internal/data-platform/v1/sources/<uuid:source_id>")
    def sources_get(source_id: uuid.UUID) -> Response:
        return jsonify({"source": store.get_source(source_id)})

    @api.put("/internal/data-platform/v1/sources/<uuid:source_id>")
    def sources_update(source_id: uuid.UUID) -> Response:
        return jsonify({"source": store.update_source(source_id, payload())})

    @api.delete("/internal/data-platform/v1/sources/<uuid:source_id>")
    def sources_delete(source_id: uuid.UUID) -> tuple[str, int]:
        store.delete_source(source_id)
        return "", 204

    @api.get("/internal/data-platform/v1/jobs")
    def jobs_list() -> Response:
        limit, offset = pagination()
        items = store.list_jobs(
            status=request.args.get("status"),
            query_text=optional_query_text(),
            limit=limit,
            offset=offset,
        )
        return jsonify(envelope(items, limit=limit, offset=offset))

    @api.post("/internal/data-platform/v1/jobs")
    def jobs_create() -> tuple[Response, int]:
        return jsonify({"job": store.create_job(payload())}), 201

    @api.get("/internal/data-platform/v1/jobs/<uuid:job_id>")
    def jobs_get(job_id: uuid.UUID) -> Response:
        return jsonify({"job": store.get_job(job_id)})

    @api.put("/internal/data-platform/v1/jobs/<uuid:job_id>")
    def jobs_update(job_id: uuid.UUID) -> Response:
        return jsonify({"job": store.update_job(job_id, payload())})

    @api.delete("/internal/data-platform/v1/jobs/<uuid:job_id>")
    def jobs_delete(job_id: uuid.UUID) -> tuple[str, int]:
        store.delete_job(job_id)
        return "", 204

    @api.get("/internal/data-platform/v1/runs")
    def runs_list() -> Response:
        limit, offset = pagination()
        items = store.list_runs(
            status=request.args.get("status"),
            query_text=optional_query_text(),
            limit=limit,
            offset=offset,
        )
        return jsonify(envelope(items, limit=limit, offset=offset))

    @api.post("/internal/data-platform/v1/jobs/<uuid:job_id>/runs")
    def runs_create(job_id: uuid.UUID) -> tuple[Response, int]:
        body = payload()
        run, created = store.create_run(
            job_id,
            mode=str(body.get("run_mode", "full_refresh")),
            scope=object_value(body.get("scope", {})),
            idempotency_key=required_text(body, "idempotency_key"),
            request_id=required_text(body, "request_id"),
            parent_run_id=uuid.UUID(str(body["parent_run_id"]))
            if body.get("parent_run_id")
            else None,
        )
        return jsonify({"run": run, "created": created}), 201 if created else 200

    @api.get("/internal/data-platform/v1/runs/<uuid:run_id>")
    def runs_get(run_id: uuid.UUID) -> Response:
        return jsonify({"run": store.get_run(run_id)})

    @api.get("/internal/data-platform/v1/runs/<uuid:run_id>/tasks")
    def run_tasks(run_id: uuid.UUID) -> Response:
        limit, offset = pagination()
        return jsonify(
            envelope(
                store.run_tasks(run_id, limit=limit, offset=offset), limit=limit, offset=offset
            )
        )

    @api.get("/internal/data-platform/v1/runs/<uuid:run_id>/artifacts")
    def run_artifacts(run_id: uuid.UUID) -> Response:
        limit, offset = pagination()
        return jsonify(
            envelope(
                store.run_artifacts(run_id, limit=limit, offset=offset), limit=limit, offset=offset
            )
        )

    @api.get("/internal/data-platform/v1/runs/<uuid:run_id>/quality-results")
    def run_quality(run_id: uuid.UUID) -> Response:
        limit, offset = pagination()
        return jsonify(
            envelope(
                store.run_quality(run_id, limit=limit, offset=offset), limit=limit, offset=offset
            )
        )

    @api.post("/internal/data-platform/v1/runs/<uuid:run_id>/cancel")
    def runs_cancel(run_id: uuid.UUID) -> Response:
        return jsonify({"run": store.request_cancel(run_id)})

    @api.post("/internal/data-platform/v1/runs/<uuid:run_id>/resume")
    def runs_resume(run_id: uuid.UUID) -> Response:
        return jsonify({"run": store.resume_run(run_id)})

    @api.post("/internal/data-platform/v1/worker/tasks/claim")
    def tasks_claim() -> Response:
        body = payload()
        task = store.claim_task(
            worker_id=required_text(body, "worker_id"),
            lease_seconds=bounded_integer(
                body, "lease_seconds", minimum=5, maximum=300, default=30
            ),
        )
        return jsonify({"task": task})

    @api.post("/internal/data-platform/v1/worker/tasks/<uuid:task_id>/heartbeat")
    def tasks_heartbeat(task_id: uuid.UUID) -> Response:
        body = payload()
        task = store.heartbeat_task(
            task_id,
            worker_id=required_text(body, "worker_id"),
            lease_token=required_text(body, "lease_token"),
            lease_seconds=bounded_integer(
                body, "lease_seconds", minimum=5, maximum=300, default=30
            ),
        )
        return jsonify({"task": task})

    @api.post("/internal/data-platform/v1/worker/tasks/<uuid:task_id>/complete")
    def tasks_complete(task_id: uuid.UUID) -> Response:
        body = payload()
        task = store.complete_task(
            task_id,
            worker_id=required_text(body, "worker_id"),
            lease_token=required_text(body, "lease_token"),
            rows_in=bounded_integer(body, "rows_in", minimum=0, maximum=100000000, default=0),
            rows_out=bounded_integer(body, "rows_out", minimum=0, maximum=100000000, default=0),
        )
        return jsonify({"task": task})

    @api.post("/internal/data-platform/v1/worker/tasks/<uuid:task_id>/fail")
    def tasks_fail(task_id: uuid.UUID) -> Response:
        body = payload()
        task = store.fail_task(
            task_id,
            worker_id=required_text(body, "worker_id"),
            lease_token=required_text(body, "lease_token"),
            error=object_value(body.get("error", {})),
            retryable=bool(body.get("retryable", False)),
        )
        return jsonify({"task": task})

    @api.post("/internal/data-platform/v1/worker/tasks/<uuid:task_id>/artifacts")
    def artifacts_register(task_id: uuid.UUID) -> tuple[Response, int]:
        body = payload()
        body["run_task_id"] = str(task_id)
        artifact, created = store.register_artifact(body)
        return jsonify({"artifact": artifact, "created": created}), 201 if created else 200

    @api.get("/internal/data-platform/v1/releases")
    def releases_list() -> Response:
        limit, offset = pagination()
        allowed = {
            "status",
            "dataset_id",
            "target_feature",
            "schema_version",
            "ingestion_run_id",
            "limit",
            "offset",
        }
        unknown = set(request.args) - allowed
        if unknown:
            raise ValidationError("unknown release query parameter")
        items = store.list_releases(
            status=request.args.get("status"),
            dataset_id=request.args.get("dataset_id"),
            target_feature=request.args.get("target_feature"),
            schema_version=request.args.get("schema_version"),
            ingestion_run_id=request.args.get("ingestion_run_id"),
            limit=limit,
            offset=offset,
        )
        return jsonify(envelope(items, limit=limit, offset=offset))

    @api.post("/internal/data-platform/v1/releases")
    def releases_create() -> tuple[Response, int]:
        return jsonify({"release": store.create_release(payload())}), 201

    @api.get("/internal/data-platform/v1/releases/<uuid:release_id>")
    def releases_get(release_id: uuid.UUID) -> Response:
        return jsonify(
            {
                "release": store.get_release(release_id),
                "receipts": store.release_receipts(release_id),
            }
        )

    @api.get("/internal/data-platform/v1/releases/<uuid:release_id>/artifact")
    def releases_artifact(release_id: uuid.UUID) -> Response:
        return jsonify({"artifact": store.release_artifact(release_id)})

    @api.get("/internal/data-platform/v1/releases/<uuid:release_id>/records")
    def releases_records(release_id: uuid.UUID) -> Response:
        limit, offset = pagination()
        return jsonify(store.preview_release_records(release_id, limit=limit, offset=offset))

    @api.get("/internal/data-platform/v1/runs/<uuid:run_id>/release-build-context")
    def releases_build_context(run_id: uuid.UUID) -> Response:
        return jsonify({"context": store.release_build_context(run_id)})

    @api.get("/internal/data-platform/v1/releases/<uuid:release_id>/product-records")
    def releases_product_records(release_id: uuid.UUID) -> Response:
        limit, offset = pagination()
        return jsonify(store.release_product_records(release_id, limit=limit, offset=offset))

    @api.post("/internal/data-platform/v1/releases/<uuid:release_id>/bind-export")
    def releases_bind_export(release_id: uuid.UUID) -> Response:
        return jsonify({"release": store.bind_release_export(release_id, payload())})

    @api.put("/internal/data-platform/v1/releases/<uuid:release_id>")
    def releases_update(release_id: uuid.UUID) -> Response:
        return jsonify({"release": store.update_release(release_id, payload())})

    @api.delete("/internal/data-platform/v1/releases/<uuid:release_id>")
    def releases_delete(release_id: uuid.UUID) -> tuple[str, int]:
        store.delete_release(release_id)
        return "", 204

    @api.post("/internal/data-platform/v1/releases/<uuid:release_id>/transition")
    def releases_transition(release_id: uuid.UUID) -> Response:
        body = payload()
        release = store.transition_release(
            release_id,
            expected_version=bounded_integer(body, "version", minimum=1, maximum=1000000),
            target=required_text(body, "target"),
            comment=required_text(body, "comment"),
        )
        return jsonify({"release": release})

    @api.post("/internal/data-platform/v1/releases/<uuid:release_id>/receipts")
    def releases_receipt(release_id: uuid.UUID) -> tuple[Response, int]:
        receipt, created = store.record_publication_receipt(release_id, payload())
        return jsonify({"receipt": receipt, "created": created}), 201 if created else 200

    @api.get("/internal/data-platform/v1/properties/search")
    def property_search() -> Response:
        query = request.args.get("q", "").strip()
        if not 2 <= len(query) <= 200:
            raise ValidationError("q must contain 2 to 200 characters")
        state = request.args.get("state", "NSW").upper()
        if state != "NSW":
            return jsonify(
                {
                    "items": [],
                    "count": 0,
                    "query": query,
                    "supported": False,
                    "reason": "Only NSW is supported",
                }
            )
        limit = query_integer("limit", minimum=1, maximum=100, default=25)
        items = store.search_properties(query, state=state, limit=limit)
        return jsonify({"items": items, "count": len(items), "query": query, "supported": True})

    @api.get("/internal/data-platform/v1/properties/<uuid:property_ref>")
    def property_get(property_ref: uuid.UUID) -> Response:
        return jsonify(store.property_snapshot(property_ref))

    @api.get("/internal/data-platform/v1/properties/<uuid:property_ref>/coverage")
    def property_coverage(property_ref: uuid.UUID) -> Response:
        items = store.property_coverage(property_ref)
        return jsonify({"items": items, "count": len(items)})

    @api.post("/internal/data-platform/v1/imports")
    def imports_create() -> tuple[Response, int]:
        operation, created = store.create_import(payload())
        return jsonify({"operation": operation, "created": created}), 201 if created else 200

    @api.get("/internal/data-platform/v1/imports/<uuid:operation_id>")
    def imports_get(operation_id: uuid.UUID) -> Response:
        return jsonify({"operation": store.get_import(operation_id)})

    @api.post("/internal/data-platform/v1/imports/<uuid:operation_id>/execute")
    def imports_execute(operation_id: uuid.UUID) -> tuple[Response, int]:
        return jsonify({"operation": store.enqueue_import(operation_id)}), 202

    @api.post("/internal/data-platform/v1/imports/<uuid:operation_id>/cancel")
    def imports_cancel(operation_id: uuid.UUID) -> Response:
        return jsonify({"operation": store.cancel_import(operation_id)})

    @api.post("/internal/data-platform/v1/loader/imports/claim")
    def imports_claim() -> Response:
        body = payload()
        operation = store.claim_import(
            worker_id=required_text(body, "worker_id"),
            lease_seconds=bounded_integer(
                body, "lease_seconds", minimum=5, maximum=600, default=60
            ),
        )
        return jsonify({"operation": operation})

    @api.post("/internal/data-platform/v1/loader/imports/<uuid:operation_id>/heartbeat")
    def imports_heartbeat(operation_id: uuid.UUID) -> Response:
        body = payload()
        operation = store.heartbeat_import(
            operation_id,
            worker_id=required_text(body, "worker_id"),
            lease_token=required_text(body, "lease_token"),
            lease_seconds=bounded_integer(
                body, "lease_seconds", minimum=5, maximum=600, default=60
            ),
        )
        return jsonify({"operation": operation})

    @api.post("/internal/data-platform/v1/loader/imports/<uuid:operation_id>/finish")
    def imports_finish(operation_id: uuid.UUID) -> Response:
        body = payload()
        operation = store.finish_import(
            operation_id,
            worker_id=required_text(body, "worker_id"),
            lease_token=required_text(body, "lease_token"),
            status=required_text(body, "status"),
            counts={
                key: int(body.get(key, 0))
                for key in ("rows_in", "rows_staged", "rows_accepted", "rows_rejected")
            },
            result=object_value(body["result"]) if body.get("result") else None,
            error=object_value(body["error"]) if body.get("error") else None,
        )
        return jsonify({"operation": operation})

    return api


def register_error_handlers(app: Any) -> None:
    """Map known store failures without exposing SQL or exception text."""
    mappings: tuple[tuple[type[StoreError], int, str], ...] = (
        (NotFoundError, 404, "not_found"),
        (ConflictError, 409, "conflict"),
        (ValidationError, 422, "invalid_request"),
    )
    for exception_type, status, code in mappings:

        def handler(error: StoreError, status: int = status, code: str = code) -> Response:
            current_app.logger.info("store request rejected", extra={"error_code": code})
            return problem(status, code, str(error))

        app.register_error_handler(exception_type, handler)
    app.register_error_handler(
        404, lambda _: problem(404, "route_not_found", "Route does not exist")
    )
    app.register_error_handler(
        405, lambda _: problem(405, "method_not_allowed", "Method is not allowed")
    )


def payload() -> dict[str, Any]:
    body: Any = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise ValidationError("request body must be a JSON object")
    return body


def pagination() -> tuple[int, int]:
    return query_integer("limit", minimum=1, maximum=100, default=25), query_integer(
        "offset", minimum=0, maximum=1000000, default=0
    )


def query_integer(name: str, *, minimum: int, maximum: int, default: int) -> int:
    try:
        value = int(request.args.get(name, default))
    except ValueError as exc:
        raise ValidationError(f"{name} must be an integer") from exc
    if not minimum <= value <= maximum:
        raise ValidationError(f"{name} must be between {minimum} and {maximum}")
    return value


def optional_query_text() -> str | None:
    value = request.args.get("q", "").strip()
    if len(value) > 200:
        raise ValidationError("q must be at most 200 characters")
    return value or None


def bounded_integer(
    body: dict[str, Any], name: str, *, minimum: int, maximum: int, default: int | None = None
) -> int:
    raw = body.get(name, default)
    if isinstance(raw, bool) or not isinstance(raw, int) or not minimum <= raw <= maximum:
        raise ValidationError(f"{name} must be between {minimum} and {maximum}")
    return raw


def required_text(body: dict[str, Any], name: str) -> str:
    value = body.get(name)
    if not isinstance(value, str) or not value.strip() or len(value) > 500:
        raise ValidationError(f"{name} is required and must be at most 500 characters")
    return value.strip()


def object_value(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValidationError("value must be a JSON object")
    return value


def envelope(items: list[dict[str, Any]], *, limit: int, offset: int) -> dict[str, Any]:
    return {
        "items": items,
        "count": len(items),
        "limit": limit,
        "offset": offset,
        "next_offset": offset + len(items) if len(items) == limit else None,
    }


def problem(status: int, code: str, detail: str) -> Response:
    response = jsonify(
        {
            "type": f"https://propertyscope.local/problems/{code}",
            "title": code.replace("_", " ").title(),
            "status": status,
            "detail": detail,
            "code": code,
            "request_id": request.headers.get("X-Request-ID", "unknown"),
        }
    )
    response.status_code = status
    response.content_type = "application/problem+json"
    return response
