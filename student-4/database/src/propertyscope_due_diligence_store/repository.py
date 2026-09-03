"""PostgreSQL-owning repository for the Student 4 due-diligence store.

The methods that touch PostgreSQL are marked ``# pragma: no cover`` because the
deterministic unit-test gate runs without a database; they are exercised by the
container/integration checks instead.
"""

from __future__ import annotations

import datetime as dt
import decimal
import uuid
from typing import Any

from psycopg.rows import dict_row
from psycopg.types.json import Json
from psycopg_pool import ConnectionPool

from propertyscope_due_diligence_store.migrations import migrate

_SITE_REVIEW_COLUMNS = (
    "id, property_ref, address_display, title, status, disposition, checklist, "
    "verification_questions, notes, ai_run_ref, created_at, updated_at, version"
)
_CONSTRAINT_COLUMNS = (
    "id, property_ref, constraint_type, evidence_state, source_name, source_url, "
    "summary, observed_value, match_method, confidence, dataset_release_id, created_at"
)
_BUILDING_COLUMNS = (
    "id, property_ref, record_type, evidence_state, reference_code, source_name, "
    "source_url, summary, match_method, confidence, observed_on, created_at"
)
_UPDATABLE_FIELDS = (
    "title",
    "status",
    "disposition",
    "checklist",
    "verification_questions",
    "notes",
    "ai_run_ref",
)
_JSON_FIELDS = frozenset({"checklist", "verification_questions"})


def _json_safe(value: Any) -> Any:
    """Convert PostgreSQL scalar types into JSON-serialisable values."""
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, dt.date):
        return value.isoformat()
    if isinstance(value, decimal.Decimal):
        return float(value)
    return value


def _row(record: Any) -> dict[str, Any]:
    """Return a JSON-safe copy of one database row (psycopg dict_row mapping)."""
    return {key: _json_safe(value) for key, value in record.items()}


class DueDiligenceStore:
    """Owns the only PostgreSQL credentials for the due-diligence feature."""

    def __init__(
        self, database_url: str, *, pool: ConnectionPool | None = None
    ) -> None:  # pragma: no cover - requires PostgreSQL
        self._pool = pool or ConnectionPool(
            database_url,
            min_size=1,
            max_size=4,
            open=True,
            kwargs={"row_factory": dict_row},
        )

    def initialize(self) -> None:  # pragma: no cover - requires PostgreSQL
        with self._pool.connection() as connection:
            migrate(connection)

    def ready(self) -> bool:  # pragma: no cover - requires PostgreSQL
        try:
            with self._pool.connection() as connection:
                connection.execute("SELECT 1")
            return True
        except Exception:
            return False

    def list_site_reviews(self, *, limit: int = 50) -> list[dict[str, Any]]:  # pragma: no cover
        with self._pool.connection() as connection:
            rows = connection.execute(
                f"SELECT {_SITE_REVIEW_COLUMNS} FROM due_diligence.site_review "
                "ORDER BY created_at DESC, id LIMIT %s",
                (limit,),
            ).fetchall()
        return [_row(row) for row in rows]

    def get_site_review(self, review_id: str) -> dict[str, Any] | None:  # pragma: no cover
        with self._pool.connection() as connection:
            row = connection.execute(
                f"SELECT {_SITE_REVIEW_COLUMNS} FROM due_diligence.site_review WHERE id = %s",
                (review_id,),
            ).fetchone()
        return _row(row) if row else None

    def create_site_review(self, payload: dict[str, Any]) -> dict[str, Any]:  # pragma: no cover
        review_id = str(uuid.uuid4())
        with self._pool.connection() as connection:
            row = connection.execute(
                "INSERT INTO due_diligence.site_review "
                "(id, property_ref, address_display, title, status, disposition, checklist, "
                "verification_questions, notes, ai_run_ref) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
                f"RETURNING {_SITE_REVIEW_COLUMNS}",
                (
                    review_id,
                    payload["property_ref"],
                    payload["address_display"],
                    payload["title"],
                    payload.get("status", "draft"),
                    payload.get("disposition", "undecided"),
                    Json(payload.get("checklist", [])),
                    Json(payload.get("verification_questions", [])),
                    payload.get("notes", ""),
                    payload.get("ai_run_ref"),
                ),
            ).fetchone()
        assert row is not None
        return _row(row)

    def update_site_review(
        self, review_id: str, changes: dict[str, Any]
    ) -> dict[str, Any] | None:  # pragma: no cover
        assignments: list[str] = []
        values: list[Any] = []
        for field in _UPDATABLE_FIELDS:
            if field in changes:
                assignments.append(f"{field} = %s")
                raw = changes[field]
                values.append(Json(raw) if field in _JSON_FIELDS else raw)
        if not assignments:
            return self.get_site_review(review_id)
        assignments.append("updated_at = now()")
        assignments.append("version = version + 1")
        values.append(review_id)
        with self._pool.connection() as connection:
            row = connection.execute(
                f"UPDATE due_diligence.site_review SET {', '.join(assignments)} "
                f"WHERE id = %s RETURNING {_SITE_REVIEW_COLUMNS}",
                values,
            ).fetchone()
        return _row(row) if row else None

    def delete_site_review(self, review_id: str) -> bool:  # pragma: no cover
        with self._pool.connection() as connection:
            cursor = connection.execute(
                "DELETE FROM due_diligence.site_review WHERE id = %s",
                (review_id,),
            )
            return cursor.rowcount > 0

    def list_constraint_observations(
        self, property_ref: str, *, limit: int = 100
    ) -> list[dict[str, Any]]:  # pragma: no cover
        with self._pool.connection() as connection:
            rows = connection.execute(
                f"SELECT {_CONSTRAINT_COLUMNS} FROM due_diligence.constraint_observation "
                "WHERE property_ref = %s ORDER BY constraint_type, id LIMIT %s",
                (property_ref, limit),
            ).fetchall()
        return [_row(row) for row in rows]

    def list_building_observations(
        self, property_ref: str, *, limit: int = 100
    ) -> list[dict[str, Any]]:  # pragma: no cover
        with self._pool.connection() as connection:
            rows = connection.execute(
                f"SELECT {_BUILDING_COLUMNS} FROM due_diligence.building_observation "
                "WHERE property_ref = %s ORDER BY record_type, id LIMIT %s",
                (property_ref, limit),
            ).fetchall()
        return [_row(row) for row in rows]
