"""HTML fragment adapter for the Feature 1 source-definition workflow."""

from __future__ import annotations

import json
import uuid
from collections.abc import Mapping
from typing import Any

import httpx
from flask import Blueprint, Response, g, make_response, render_template, request
from pydantic import ValidationError

from propertyscope_data_platform.clients import DataStoreClient, DependencyUnavailableError
from propertyscope_data_platform.domain import SourceDefinitionCreate, SourceDefinitionUpdate

FRAGMENT_BASE = "/fragments/data-platform/v1/sources"
INTERNAL_BASE = "/internal/data-platform/v1/sources"
_STATUSES = {"active", "draft", "disabled", "retired", "all"}
_SOURCE_FIELDS = (
    "name",
    "publisher",
    "source_url",
    "adapter_key",
    "cadence",
    "licence_id",
    "licence_url",
    "redistribution_policy",
    "target_features",
    "status",
    "notes",
)


def create_source_fragment_blueprint(store: DataStoreClient) -> Blueprint:
    """Create presentation-only routes over the existing database-service client."""
    fragments = Blueprint("propertyscope-source-fragments", __name__, template_folder="templates")

    @fragments.get(FRAGMENT_BASE)
    def source_list() -> Response:
        query, status, error = _filters()
        if error is not None:
            return _region_error(error, status_code=422, query=query, status=status)
        return _render_list(store, query=query, status=status)

    @fragments.post(FRAGMENT_BASE)
    def source_create() -> Response:
        values, errors = _validated_form(SourceDefinitionCreate)
        if errors:
            return _form_response(values, errors=errors, status_code=422, mode="create")
        try:
            upstream = store.request(
                "POST",
                INTERNAL_BASE,
                headers=request.headers,
                json=SourceDefinitionCreate.model_validate(values).model_dump(mode="json"),
            )
        except DependencyUnavailableError:
            return _form_response(
                values,
                summary=(
                    "The source service is temporarily unavailable. Your entered values are "
                    "still here; retry when the service is available."
                ),
                status_code=503,
                mode="create",
            )
        if upstream.status_code >= 400:
            return _upstream_form_error(upstream, values, mode="create")
        created = upstream.json().get("source", {})
        return _render_list(
            store,
            query="",
            status="all",
            success=f"{created.get('name', values.get('name', 'Source'))} was created.",
            success_status=201,
        )

    @fragments.get(f"{FRAGMENT_BASE}/new")
    def source_new() -> Response:
        return _form_response(_blank_values(), mode="create")

    @fragments.get(f"{FRAGMENT_BASE}/<uuid:source_id>")
    def source_detail(source_id: uuid.UUID) -> Response:
        upstream = _store_request(store, "GET", f"{INTERNAL_BASE}/{source_id}")
        if isinstance(upstream, Response):
            return upstream
        if upstream.status_code >= 400:
            return _region_upstream_error(upstream)
        source = _source_values(upstream.json().get("source", {}))
        return _html(
            "fragments/sources/detail.html",
            source=source,
            fragment_base=FRAGMENT_BASE,
        )

    @fragments.get(f"{FRAGMENT_BASE}/<uuid:source_id>/edit")
    def source_edit(source_id: uuid.UUID) -> Response:
        upstream = _store_request(store, "GET", f"{INTERNAL_BASE}/{source_id}", form=True)
        if isinstance(upstream, Response):
            return upstream
        if upstream.status_code >= 400:
            return _upstream_form_error(upstream, _blank_values(), mode="edit", source_id=source_id)
        return _form_response(
            _source_values(upstream.json().get("source", {})),
            mode="edit",
            source_id=source_id,
        )

    @fragments.put(f"{FRAGMENT_BASE}/<uuid:source_id>")
    def source_update(source_id: uuid.UUID) -> Response:
        values, errors = _validated_form(SourceDefinitionUpdate)
        if errors:
            return _form_response(
                values, errors=errors, status_code=422, mode="edit", source_id=source_id
            )
        try:
            upstream = store.request(
                "PUT",
                f"{INTERNAL_BASE}/{source_id}",
                headers=request.headers,
                json=SourceDefinitionUpdate.model_validate(values).model_dump(mode="json"),
            )
        except DependencyUnavailableError:
            return _form_response(
                values,
                summary=(
                    "The source service is temporarily unavailable. Your entered values are "
                    "still here; retry when the service is available."
                ),
                status_code=503,
                mode="edit",
                source_id=source_id,
            )
        if upstream.status_code >= 400:
            return _upstream_form_error(upstream, values, mode="edit", source_id=source_id)
        updated = upstream.json().get("source", {})
        return _render_list(
            store,
            query="",
            status="all",
            success=f"{updated.get('name', values.get('name', 'Source'))} was updated.",
        )

    @fragments.get(f"{FRAGMENT_BASE}/<uuid:source_id>/delete-confirmation")
    def source_delete_confirmation(source_id: uuid.UUID) -> Response:
        upstream = _store_request(store, "GET", f"{INTERNAL_BASE}/{source_id}", action=True)
        if isinstance(upstream, Response):
            return upstream
        if upstream.status_code >= 400:
            return _delete_response(
                {"id": str(source_id), "name": "this source"},
                summary=_safe_detail(upstream),
                status_code=upstream.status_code,
            )
        return _delete_response(_source_values(upstream.json().get("source", {})))

    @fragments.delete(f"{FRAGMENT_BASE}/<uuid:source_id>")
    def source_delete(source_id: uuid.UUID) -> Response:
        try:
            upstream = store.request(
                "DELETE", f"{INTERNAL_BASE}/{source_id}", headers=request.headers
            )
        except DependencyUnavailableError:
            return _delete_response(
                {"id": str(source_id), "name": "this source"},
                summary=(
                    "The source service is temporarily unavailable. Nothing was deleted; "
                    "retry when the service is available."
                ),
                status_code=503,
            )
        if upstream.status_code >= 400:
            return _delete_response(
                {"id": str(source_id), "name": "this source"},
                summary=_safe_detail(upstream),
                status_code=upstream.status_code,
            )
        return _render_list(
            store,
            query="",
            status="all",
            success="The source definition was deleted.",
        )

    return fragments


def _filters() -> tuple[str, str, str | None]:
    query = request.args.get("q", "").strip()
    status = request.args.get("status", "active").strip() or "active"
    if len(query) > 200:
        return query[:200], status, "Search text must be at most 200 characters."
    if status not in _STATUSES:
        return query, "active", "Lifecycle status is not recognised."
    return query, status, None


def _render_list(
    store: DataStoreClient,
    *,
    query: str,
    status: str,
    success: str = "",
    success_status: int = 200,
) -> Response:
    params: dict[str, Any] = {"limit": 100}
    if query:
        params["q"] = query
    if status != "all":
        params["status"] = status
    try:
        upstream = store.request("GET", INTERNAL_BASE, headers=request.headers, params=params)
    except DependencyUnavailableError:
        return _region_error(
            "Source definitions are temporarily unavailable. No source has been changed. "
            "Retry the request.",
            status_code=503,
            query=query,
            status=status,
        )
    if upstream.status_code >= 400:
        return _region_error(
            _safe_detail(upstream),
            status_code=upstream.status_code,
            query=query,
            status=status,
        )
    items = [_source_values(item) for item in upstream.json().get("items", [])]
    response = _html(
        "fragments/sources/region.html",
        items=items,
        query=query,
        status=status,
        success=success,
        fragment_base=FRAGMENT_BASE,
        status_code=success_status,
    )
    if success:
        response.headers["HX-Trigger-After-Swap"] = json.dumps(
            {"propertyscope:source-mutated": {"message": success, "requestId": g.request_id}}
        )
    return response


def _validated_form(model: type[SourceDefinitionCreate]) -> tuple[dict[str, Any], dict[str, str]]:
    values: dict[str, Any] = {name: request.form.get(name, "") for name in _SOURCE_FIELDS}
    if model is SourceDefinitionUpdate:
        values["version"] = request.form.get("version", "")
    try:
        target_features = json.loads(str(values["target_features"] or "[]"))
        if not isinstance(target_features, list):
            raise ValueError
        values["target_features"] = target_features
    except (TypeError, ValueError, json.JSONDecodeError):
        return values, {
            "target_features": (
                'Research area keys must be a non-empty JSON list, for example ["feature-1"].'
            )
        }
    try:
        validated = model.model_validate(values)
    except ValidationError as exc:
        errors: dict[str, str] = {}
        for issue in exc.errors(include_url=False):
            field = str(issue.get("loc", ("form",))[0])
            message = str(issue.get("msg", "Value is invalid."))
            errors.setdefault(field, message.removeprefix("Value error, "))
        return values, errors
    return validated.model_dump(mode="json"), {}


def _form_response(
    values: Mapping[str, Any],
    *,
    mode: str,
    source_id: uuid.UUID | None = None,
    errors: Mapping[str, str] | None = None,
    summary: str = "",
    status_code: int = 200,
) -> Response:
    normalised = _source_values(values)
    response = _html(
        "fragments/sources/form.html",
        values=normalised,
        errors=dict(errors or {}),
        summary=summary,
        mode=mode,
        source_id=source_id,
        fragment_base=FRAGMENT_BASE,
        status_code=status_code,
    )
    if status_code >= 400:
        _retarget(response, "#entity-form")
    return response


def _upstream_form_error(
    upstream: httpx.Response,
    values: Mapping[str, Any],
    *,
    mode: str,
    source_id: uuid.UUID | None = None,
) -> Response:
    return _form_response(
        values,
        summary=(
            f"The source could not be saved. {_safe_detail(upstream)} "
            "Your entered values are still here."
        ),
        status_code=upstream.status_code,
        mode=mode,
        source_id=source_id,
    )


def _delete_response(
    source: Mapping[str, Any], *, summary: str = "", status_code: int = 200
) -> Response:
    response = _html(
        "fragments/sources/delete_confirmation.html",
        source=_source_values(source),
        summary=summary,
        fragment_base=FRAGMENT_BASE,
        status_code=status_code,
    )
    if status_code >= 400:
        _retarget(response, "#action-form")
    return response


def _store_request(
    store: DataStoreClient, method: str, path: str, *, form: bool = False, action: bool = False
) -> httpx.Response | Response:
    try:
        return store.request(method, path, headers=request.headers)
    except DependencyUnavailableError:
        message = (
            "The source service is temporarily unavailable. Retry when the service is available."
        )
        if form:
            return _form_response(_blank_values(), summary=message, status_code=503, mode="edit")
        if action:
            return _delete_response({"name": "this source"}, summary=message, status_code=503)
        return _region_error(message, status_code=503, query="", status="active")


def _region_upstream_error(upstream: httpx.Response) -> Response:
    return _region_error(
        _safe_detail(upstream), status_code=upstream.status_code, query="", status="active"
    )


def _region_error(message: str, *, status_code: int, query: str, status: str) -> Response:
    response = _html(
        "fragments/sources/error.html",
        message=message,
        query=query,
        status=status,
        fragment_base=FRAGMENT_BASE,
        status_code=status_code,
    )
    if status_code >= 400:
        _retarget(response, "#source-crud-region", swap="outerHTML")
    return response


def _html(template: str, *, status_code: int = 200, **context: Any) -> Response:
    response = make_response(
        render_template(template, request_id=g.request_id, **context), status_code
    )
    response.content_type = "text/html; charset=utf-8"
    response.headers["Cache-Control"] = "no-store"
    return response


def _retarget(response: Response, target: str, *, swap: str = "innerHTML") -> None:
    response.headers["HX-Retarget"] = target
    response.headers["HX-Reswap"] = swap


def _safe_detail(upstream: httpx.Response) -> str:
    try:
        payload = upstream.json()
    except ValueError:
        return "The service returned an unreadable error."
    detail = payload.get("detail") if isinstance(payload, dict) else None
    return (
        str(detail) if isinstance(detail, str) and detail else "The request could not be completed."
    )


def _blank_values() -> dict[str, Any]:
    return {
        "name": "",
        "publisher": "",
        "source_url": "",
        "adapter_key": "",
        "cadence": "",
        "licence_id": "",
        "licence_url": "",
        "redistribution_policy": "",
        "target_features": '["feature-1"]',
        "status": "draft",
        "notes": "",
        "version": "",
    }


def _source_values(source: Mapping[str, Any]) -> dict[str, Any]:
    values = _blank_values() | {key: source.get(key, "") for key in _blank_values()}
    targets = source.get(
        "target_features", source.get("target_features_json", values["target_features"])
    )
    if not isinstance(targets, str):
        targets = json.dumps(targets or [], ensure_ascii=False)
    values["target_features"] = targets
    values["id"] = str(source.get("id", ""))
    values["created_at"] = source.get("created_at", "")
    values["updated_at"] = source.get("updated_at", "")
    return values
