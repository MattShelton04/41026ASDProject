"""Internal HTTP API for Feature 1 persistence and leases."""

from __future__ import annotations

import hmac
import uuid
from typing import Any

import orjson
from flask import Blueprint, Response, current_app, jsonify, request

from propertyscope_data_store.errors import (
    ConflictError,
    NotFoundError,
    ReadBudgetExceededError,
    StoreError,
    ValidationError,
)
from propertyscope_data_store.export_pages import columnar_export_page
from propertyscope_data_store.migrations import SCHEMA_FINGERPRINT_POLICY_VERSION
from propertyscope_data_store.repository import PropertyScopeStore


def create_blueprint(store: PropertyScopeStore, *, internal_token: str) -> Blueprint:
    """Build the private database API around its injected store."""
    api = Blueprint("propertyscope-data-store", __name__)
    expected_token = internal_token.encode()

    @api.before_request
    def authenticate() -> Response | None:
        if request.path.startswith("/health/"):
            return None
        supplied = request.headers.get("X-PropertyScope-Internal-Token", "").encode()
        # Constant-time comparison keeps the credential from leaking through response timing.
        if not hmac.compare_digest(supplied, expected_token):
            return problem(401, "unauthorised", "A valid internal service credential is required")
        return None

    @api.get("/health/live")
    def live() -> tuple[Response, int]:
        return jsonify({"status": "healthy", "service": "f1-db-api"}), 200

    @api.get("/health/ready")
    def ready() -> tuple[Response, int]:
        healthy = store.ready()
        return jsonify({"status": "healthy" if healthy else "unhealthy"}), 200 if healthy else 503

    @api.get("/internal/data-platform/v1/overview")
    def overview() -> Response:
        return jsonify(store.overview())

    @api.get("/internal/data-platform/v1/notifications")
    def operator_notifications() -> Response:
        return jsonify({"items": store.operator_notifications()})

    @api.get("/internal/data-platform/v1/artifact-retention")
    def artifact_retention() -> Response:
        items = store.artifact_retention_inventory()
        return jsonify(
            {
                "items": items,
                "referenced_bytes": sum(int(item["bytes"]) for item in items),
                "physical_objects": len(items),
            }
        )

    @api.get("/internal/data-platform/v1/schema/counts")
    def counts() -> Response:
        return jsonify({"tables": store.counts()})

    @api.get("/internal/data-platform/v1/schema/fingerprint")
    def fingerprint() -> Response:
        return jsonify(
            {
                "algorithm": "sha256",
                "fingerprint": store.fingerprint(),
                "policy_version": SCHEMA_FINGERPRINT_POLICY_VERSION,
            }
        )

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
            job_definition_id=optional_uuid_query("job_definition_id"),
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

    @api.get("/internal/data-platform/v1/runs/<uuid:run_id>/activity")
    def run_activity(run_id: uuid.UUID) -> Response:
        limit, offset = pagination(maximum_limit=1000, default_limit=100)
        return jsonify(
            envelope(
                store.run_activity(run_id, limit=limit, offset=offset), limit=limit, offset=offset
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
            progress=object_value(body["progress"]) if body.get("progress") is not None else None,
        )
        return jsonify({"task": task})

    @api.post("/internal/data-platform/v1/worker/tasks/<uuid:task_id>/complete")
    def tasks_complete(task_id: uuid.UUID) -> Response:
        body = payload()
        task = store.complete_task(
            task_id,
            worker_id=required_text(body, "worker_id"),
            lease_token=required_text(body, "lease_token"),
            rows_in=nonnegative_integer(body, "rows_in", default=0),
            rows_out=nonnegative_integer(body, "rows_out", default=0),
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
            retryable=boolean_value(body, "retryable", default=False),
        )
        return jsonify({"task": task})

    @api.post("/internal/data-platform/v1/worker/tasks/<uuid:task_id>/artifacts")
    def artifacts_register(task_id: uuid.UUID) -> tuple[Response, int]:
        request.max_content_length = 2 * 1024 * 1024
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
            "q",
            "lifecycle",
            "view",
            "limit",
            "offset",
        }
        unknown = set(request.args) - allowed
        if unknown:
            raise ValidationError("unknown release query parameter")
        if request.args.get("view", "full") not in {"full", "summary"}:
            raise ValidationError("view must be full or summary")
        items = store.list_releases(
            status=request.args.get("status"),
            dataset_id=request.args.get("dataset_id"),
            target_feature=request.args.get("target_feature"),
            schema_version=request.args.get("schema_version"),
            ingestion_run_id=request.args.get("ingestion_run_id"),
            query_text=optional_query_text(),
            lifecycle=request.args.get("lifecycle"),
            summary=request.args.get("view") == "summary",
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
                "activations": store.release_activations(release_id),
                "consumer_imports": store.release_consumer_imports(release_id),
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
        limit = query_integer("limit", minimum=1, maximum=20_000, default=20_000)
        layout = request.args.get("layout", "records")
        if layout not in {"records", "columns"}:
            raise ValidationError("export layout must be records or columns")
        page = store.release_product_records(
            release_id, limit=limit, cursor=request.args.get("cursor") or None
        )
        payload = columnar_export_page(page) if layout == "columns" else page
        # The fixed projections normalize UUIDs, decimals and dates before this
        # boundary. Encode the large private page once without Flask's Python walk.
        return Response(
            orjson.dumps(payload, option=orjson.OPT_SORT_KEYS), mimetype="application/json"
        )

    @api.get("/internal/data-platform/v1/releases/<uuid:release_id>/sales-source-records")
    def releases_sales_source_records(release_id: uuid.UUID) -> Response:
        year = query_integer("year", minimum=1990, maximum=9999, default=0)
        limit, offset = pagination(maximum_limit=5_000, default_limit=1_000)
        return jsonify(
            store.release_sales_source_records(release_id, year=year, limit=limit, offset=offset)
        )

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

    @api.post("/internal/data-platform/v1/releases/<uuid:release_id>/consumer-imports")
    def consumer_import_create(release_id: uuid.UUID) -> tuple[Response, int]:
        body = payload()
        operation, created = store.create_consumer_import(
            release_id,
            {
                "dataset_id": required_text(body, "dataset_id"),
                "target_feature": required_text(body, "target_feature"),
                "schema_version": required_text(body, "schema_version"),
                "content_sha256": required_text(body, "content_sha256"),
                "record_count": bounded_integer(
                    body, "record_count", minimum=0, maximum=10_000_000_000
                ),
                "artifact_path": required_text(body, "artifact_path"),
                "expected_release_version": bounded_integer(
                    body, "expected_release_version", minimum=1, maximum=1_000_000
                ),
                "comment": required_text(body, "comment"),
                "idempotency_key": required_text(body, "idempotency_key"),
                "request_id": required_text(body, "request_id"),
            },
        )
        return jsonify({"operation": operation, "created": created}), 202 if created else 200

    @api.get("/internal/data-platform/v1/consumer-imports/<uuid:operation_id>")
    def consumer_import_get(operation_id: uuid.UUID) -> Response:
        return jsonify({"operation": store.get_consumer_import(operation_id)})

    @api.post("/internal/data-platform/v1/consumer-imports/claim")
    def consumer_import_claim() -> Response:
        body = payload()
        operation = store.claim_consumer_import(
            worker_id=required_text(body, "worker_id"),
            lease_seconds=bounded_integer(body, "lease_seconds", minimum=10, maximum=300),
        )
        return jsonify({"operation": operation})

    @api.post("/internal/data-platform/v1/consumer-imports/<uuid:operation_id>/acknowledge")
    def consumer_import_acknowledge(operation_id: uuid.UUID) -> Response:
        body = payload()
        result = body.get("result")
        if result is not None and not isinstance(result, dict):
            raise ValidationError("result must be an object")
        operation = store.acknowledge_consumer_import(
            operation_id,
            worker_id=required_text(body, "worker_id"),
            lease_token=required_text(body, "lease_token"),
            consumer_operation_id=required_text(body, "consumer_operation_id"),
            remote_status=required_text(body, "remote_status"),
            result=result,
            poll_seconds=bounded_integer(body, "poll_seconds", minimum=1, maximum=300),
        )
        return jsonify({"operation": operation})

    @api.post("/internal/data-platform/v1/consumer-imports/<uuid:operation_id>/retry")
    def consumer_import_retry(operation_id: uuid.UUID) -> Response:
        body = payload()
        error = body.get("error")
        if not isinstance(error, dict):
            raise ValidationError("error must be an object")
        operation = store.retry_consumer_import(
            operation_id,
            worker_id=required_text(body, "worker_id"),
            lease_token=required_text(body, "lease_token"),
            error=error,
            retry_seconds=bounded_integer(body, "retry_seconds", minimum=1, maximum=300),
        )
        return jsonify({"operation": operation})

    @api.post("/internal/data-platform/v1/consumer-imports/<uuid:operation_id>/receipt")
    def consumer_import_receipt(operation_id: uuid.UUID) -> Response:
        body = payload()
        operation = store.attach_consumer_import_receipt(
            operation_id,
            worker_id=required_text(body, "worker_id"),
            lease_token=required_text(body, "lease_token"),
            receipt_id=uuid.UUID(required_text(body, "publication_receipt_id")),
            receipt_status=required_text(body, "receipt_status"),
        )
        return jsonify({"operation": operation})

    @api.post("/internal/data-platform/v1/consumer-imports/<uuid:operation_id>/activation")
    def consumer_import_activation(operation_id: uuid.UUID) -> Response:
        body = payload()
        operation = store.attach_consumer_import_activation(
            operation_id,
            worker_id=required_text(body, "worker_id"),
            lease_token=required_text(body, "lease_token"),
            activation_id=uuid.UUID(required_text(body, "release_activation_id")),
        )
        return jsonify({"operation": operation})

    @api.post("/internal/data-platform/v1/consumer-imports/<uuid:operation_id>/activation-status")
    def consumer_import_activation_status(operation_id: uuid.UUID) -> Response:
        body = payload()
        error = body.get("error")
        if error is not None and not isinstance(error, dict):
            raise ValidationError("error must be an object")
        operation = store.record_consumer_import_activation_outcome(
            operation_id,
            worker_id=required_text(body, "worker_id"),
            lease_token=required_text(body, "lease_token"),
            activation_status=required_text(body, "activation_status"),
            error=error,
            poll_seconds=bounded_integer(body, "poll_seconds", minimum=1, maximum=300),
        )
        return jsonify({"operation": operation})

    @api.post("/internal/data-platform/v1/releases/<uuid:release_id>/activations")
    def releases_activation(release_id: uuid.UUID) -> tuple[Response, int]:
        body = payload()
        operation, created = store.create_release_activation(
            release_id,
            {
                "publication_receipt_id": required_text(body, "publication_receipt_id"),
                "expected_release_version": bounded_integer(
                    body, "expected_release_version", minimum=1, maximum=1_000_000
                ),
                "comment": required_text(body, "comment"),
                "idempotency_key": required_text(body, "idempotency_key"),
            },
        )
        status = str(operation["status"])
        if status == "failed":
            return (
                problem(
                    409,
                    "release_activation_failed",
                    "The publication activation failed before the live version changed; "
                    "a fresh request can retry it",
                ),
                409,
            )
        outcome = "completed" if status == "succeeded" else "pending"
        response_status = 200 if outcome == "completed" else 202
        return jsonify(
            {"activation": operation, "created": created, "outcome": outcome}
        ), response_status

    @api.get("/internal/data-platform/v1/activations/<uuid:operation_id>")
    def activation_get(operation_id: uuid.UUID) -> Response:
        return jsonify({"activation": store.get_release_activation(operation_id)})

    @api.get("/internal/data-platform/v1/properties/search")
    def property_search() -> Response:
        query = request.args.get("q", "").strip()
        if not 2 <= len(query) <= 200:
            raise ValidationError("q must contain 2 to 200 characters")
        limit = query_integer("limit", minimum=1, maximum=100, default=25)
        offset = query_integer("offset", minimum=0, maximum=1_000_000, default=0)
        state = request.args.get("state", "NSW").upper()
        if state != "NSW":
            return jsonify(
                {
                    "items": [],
                    "count": 0,
                    "total": 0,
                    "total_is_lower_bound": False,
                    "limit": limit,
                    "offset": offset,
                    "next_offset": None,
                    "query": query,
                    "supported": False,
                    "reason": "Only NSW is supported",
                }
            )
        results = store.search_properties(query, state=state, limit=limit, offset=offset)
        return jsonify(
            {
                "items": results.items,
                "count": len(results.items),
                "total": results.total,
                "total_is_lower_bound": results.total_is_lower_bound,
                "limit": limit,
                "offset": offset,
                "next_offset": offset + len(results.items)
                if offset + len(results.items) < results.total
                else None,
                "query": query,
                "supported": True,
            }
        )

    @api.get("/internal/data-platform/v1/properties/locality-summary")
    def property_locality_summary() -> Response:
        unknown = set(request.args) - {"locality", "postcode", "include_streets"}
        if unknown:
            raise ValidationError("unsupported locality-summary query field")
        locality = request.args.get("locality", "").strip() or None
        postcode = request.args.get("postcode", "").strip() or None
        include_streets = request.args.get("include_streets", "false").lower() == "true"
        return jsonify(
            store.locality_summary(
                locality=locality,
                postcode=postcode,
                include_streets=include_streets,
            )
        )

    @api.get("/internal/data-platform/v1/properties/<uuid:property_ref>")
    def property_get(property_ref: uuid.UUID) -> Response:
        return jsonify(store.property_snapshot(property_ref))

    @api.get("/internal/data-platform/v1/properties/<uuid:property_ref>/coverage")
    def property_coverage(property_ref: uuid.UUID) -> Response:
        items = store.property_coverage(property_ref)
        return jsonify({"items": items, "count": len(items)})

    @api.get("/internal/data-platform/v1/properties/<uuid:property_ref>/map-context")
    def property_map_context(property_ref: uuid.UUID) -> Response:
        return jsonify(store.property_map_context(property_ref))

    @api.get("/internal/data-platform/v1/properties/<uuid:property_ref>/sale-history")
    def property_sale_history(property_ref: uuid.UUID) -> Response:
        limit = query_integer("limit", minimum=1, maximum=100, default=50)
        return jsonify(store.property_sale_history(property_ref, limit=limit))

    @api.get("/internal/data-platform/v1/properties/<uuid:property_ref>/seifa")
    def property_seifa(property_ref: uuid.UUID) -> Response:
        return jsonify(store.property_seifa(property_ref))

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

    @api.post("/internal/data-platform/v1/imports/<uuid:operation_id>/space-recovery")
    def imports_space_recovery(operation_id: uuid.UUID) -> Response:
        return jsonify({"operation": store.recover_import_space(operation_id)})

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
                key: nonnegative_integer(body, key, default=0)
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
        (ReadBudgetExceededError, 503, "read_budget_exceeded"),
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


def pagination(*, maximum_limit: int = 100, default_limit: int = 25) -> tuple[int, int]:
    return query_integer(
        "limit", minimum=1, maximum=maximum_limit, default=default_limit
    ), query_integer("offset", minimum=0, maximum=1000000, default=0)


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


def optional_uuid_query(name: str) -> uuid.UUID | None:
    value = request.args.get(name, "").strip()
    if not value:
        return None
    try:
        return uuid.UUID(value)
    except ValueError as exc:
        raise ValidationError(f"{name} must be a UUID") from exc


def bounded_integer(
    body: dict[str, Any], name: str, *, minimum: int, maximum: int, default: int | None = None
) -> int:
    raw = body.get(name, default)
    if isinstance(raw, bool) or not isinstance(raw, int) or not minimum <= raw <= maximum:
        raise ValidationError(f"{name} must be between {minimum} and {maximum}")
    return int(raw)


def nonnegative_integer(body: dict[str, Any], name: str, *, default: int = 0) -> int:
    raw = body.get(name, default)
    if isinstance(raw, bool) or not isinstance(raw, int) or raw < 0:
        raise ValidationError(f"{name} must be a non-negative integer")
    return int(raw)


def boolean_value(body: dict[str, Any], name: str, *, default: bool) -> bool:
    raw = body.get(name, default)
    if not isinstance(raw, bool):
        raise ValidationError(f"{name} must be a boolean")
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
