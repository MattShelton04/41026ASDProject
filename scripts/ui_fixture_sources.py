"""Ephemeral Source-definition persistence for deterministic HTMX browser fixtures."""

from __future__ import annotations

import threading
from collections.abc import Mapping
from typing import Any
from uuid import NAMESPACE_URL, uuid5

import httpx
from werkzeug.datastructures import Headers

from propertyscope_data_platform.clients import DataStoreClient, DependencyUnavailableError
from scripts.ui_fixtures import REQUEST_ID, TIMESTAMP, fixture_source_records

INTERNAL_SOURCES = "/internal/data-platform/v1/sources"


class FixtureSourceStoreClient(DataStoreClient):
    """A bounded in-memory stand-in for the private Feature 1 database API."""

    def __init__(self, *, session_key: str, scenario: str) -> None:
        self._session_key = session_key
        self._scenario = scenario
        self._items = {item["id"]: item for item in fixture_source_records(scenario)}
        self._counter = 0
        self._lock = threading.RLock()

    def ready(self) -> bool:
        return self._scenario != "error"

    def request(
        self,
        method: str,
        path: str,
        *,
        headers: Mapping[str, str] | Headers | None = None,
        params: Mapping[str, Any] | None = None,
        json: Mapping[str, Any] | None = None,
        timeout: float | None = None,
    ) -> httpx.Response:
        del timeout
        if self._scenario == "error":
            raise DependencyUnavailableError("Property data store is unavailable")
        request_id = str((headers or {}).get("X-Request-ID") or REQUEST_ID)
        response_headers = {"X-Request-ID": request_id}
        with self._lock:
            if path == INTERNAL_SOURCES:
                if method == "GET":
                    return httpx.Response(
                        200,
                        json=self._collection(params or {}),
                        headers=response_headers,
                    )
                if method == "POST":
                    if self._scenario == "validation-error":
                        return self._problem(
                            422,
                            "fixture_validation_error",
                            "The submitted value conflicts with the deterministic "
                            "validation fixture.",
                            response_headers,
                        )
                    return self._create(dict(json or {}), response_headers)
            if path.startswith(f"{INTERNAL_SOURCES}/"):
                source_id = path.removeprefix(f"{INTERNAL_SOURCES}/").split("/", 1)[0]
                item = self._items.get(source_id)
                if item is None:
                    return self._problem(
                        404,
                        "source_not_found",
                        "Source definition does not exist.",
                        response_headers,
                    )
                if method == "GET":
                    return httpx.Response(
                        200, json={"source": dict(item)}, headers=response_headers
                    )
                if method == "PUT":
                    if self._scenario == "validation-error":
                        return self._problem(
                            422,
                            "fixture_validation_error",
                            "The submitted value conflicts with the deterministic "
                            "validation fixture.",
                            response_headers,
                        )
                    return self._update(source_id, dict(json or {}), response_headers)
                if method == "DELETE":
                    return self._delete(source_id, response_headers)
        return self._problem(
            404,
            "fixture_route_not_found",
            "Fixture database route does not exist.",
            response_headers,
        )

    def _collection(self, params: Mapping[str, Any]) -> dict[str, Any]:
        query = str(params.get("q", "")).strip().casefold()
        status = str(params.get("status", "")).strip()
        items = list(self._items.values())
        if query:
            items = [
                item
                for item in items
                if query in str(item.get("name", "")).casefold()
                or query in str(item.get("publisher", "")).casefold()
            ]
        if status:
            items = [item for item in items if item.get("status") == status]
        items.sort(key=lambda item: (str(item.get("name", "")).casefold(), str(item["id"])))
        return {
            "items": [dict(item) for item in items[:100]],
            "count": min(len(items), 100),
            "total": len(items),
            "limit": 100,
            "offset": 0,
            "next_offset": None,
        }

    def _create(self, values: dict[str, Any], headers: Mapping[str, str]) -> httpx.Response:
        if self._name_exists(str(values.get("name", ""))):
            return self._problem(
                409,
                "source_name_conflict",
                "A source definition with this name already exists.",
                headers,
            )
        self._counter += 1
        source_id = str(
            uuid5(
                NAMESPACE_URL,
                "propertyscope-ui-source:"
                f"{self._session_key}:{self._counter}:{values.get('name', '')}",
            )
        )
        item = {
            **values,
            "id": source_id,
            "version": 1,
            "target_features_json": list(values.get("target_features", [])),
            "created_at": TIMESTAMP,
            "updated_at": TIMESTAMP,
        }
        self._items[source_id] = item
        return httpx.Response(201, json={"source": dict(item)}, headers=headers)

    def _update(
        self, source_id: str, values: dict[str, Any], headers: Mapping[str, str]
    ) -> httpx.Response:
        current = self._items[source_id]
        if values.get("version") != current.get("version"):
            return self._problem(
                409,
                "version_conflict",
                "The source changed after this form was opened. Reload the latest "
                "version before saving.",
                headers,
            )
        if self._name_exists(str(values.get("name", "")), excluding=source_id):
            return self._problem(
                409,
                "source_name_conflict",
                "A source definition with this name already exists.",
                headers,
            )
        item = {
            **current,
            **values,
            "id": source_id,
            "version": int(current["version"]) + 1,
            "target_features_json": list(values.get("target_features", [])),
            "updated_at": TIMESTAMP,
        }
        self._items[source_id] = item
        return httpx.Response(200, json={"source": dict(item)}, headers=headers)

    def _delete(self, source_id: str, headers: Mapping[str, str]) -> httpx.Response:
        item = self._items[source_id]
        if item.get("status") != "draft":
            return self._problem(
                409,
                "source_delete_conflict",
                "Only unused draft source definitions can be deleted.",
                headers,
            )
        del self._items[source_id]
        return httpx.Response(204, headers=headers)

    def _name_exists(self, name: str, *, excluding: str | None = None) -> bool:
        candidate = name.strip().casefold()
        return any(
            source_id != excluding and str(item.get("name", "")).strip().casefold() == candidate
            for source_id, item in self._items.items()
        )

    @staticmethod
    def _problem(
        status: int,
        code: str,
        detail: str,
        headers: Mapping[str, str],
    ) -> httpx.Response:
        return httpx.Response(
            status,
            json={
                "type": f"https://propertyscope.local/problems/{code}",
                "title": code.replace("_", " ").title(),
                "status": status,
                "detail": detail,
                "code": code,
                "request_id": headers.get("X-Request-ID", REQUEST_ID),
            },
            headers=headers,
        )
