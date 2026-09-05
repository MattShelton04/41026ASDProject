"""SQLite persistence for market cases and attributed sales."""

from __future__ import annotations

import json
import sqlite3
import uuid
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from typing import Any

from propertyscope_market_store.import_operations import SalesImportOperations
from propertyscope_market_store.migrations import migrate


class VersionConflictError(RuntimeError):
    """Raised when an optimistic update uses a stale case version."""


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _case(row: sqlite3.Row) -> dict[str, Any]:
    value = dict(row)
    value["filters"] = json.loads(value.pop("filters_json"))
    return value


class MarketStore:
    """The only component permitted to open Feature 2's SQLite file."""

    def __init__(self, database_path: Path) -> None:
        self._path = database_path
        self._migration_lock = Lock()
        self.imports = SalesImportOperations(self._connect)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 10000")
        return connection

    def initialize(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._migration_lock, self._connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            migrate(connection)

    def ready(self) -> bool:
        try:
            with self._connect() as connection:
                count = connection.execute(
                    "SELECT COUNT(*) FROM sqlite_master WHERE type='table' "
                    "AND name IN ('market_case', 'sale_observation')"
                ).fetchone()[0]
            return int(count) == 2
        except sqlite3.Error:
            return False

    def table_counts(self) -> dict[str, int]:
        with self._connect() as connection:
            return {
                table: int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
                for table in ("market_case", "sale_observation")
            }

    def list_cases(self, *, limit: int = 100) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM market_case ORDER BY updated_at DESC, id LIMIT ?", (limit,)
            ).fetchall()
        return [_case(row) for row in rows]

    def get_case(self, case_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM market_case WHERE id = ?", (case_id,)
            ).fetchone()
        return _case(row) if row is not None else None

    def create_case(self, values: Mapping[str, Any]) -> dict[str, Any]:
        case_id = str(uuid.uuid4())
        timestamp = _now()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO market_case (
                    id, name, property_ref, address_display, date_from, date_to,
                    status, notes, filters_json, ai_run_ref,
                    property_validation_state, created_at, updated_at, version
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
                """,
                (
                    case_id,
                    values["name"],
                    values["property_ref"],
                    values["address_display"],
                    values["date_from"],
                    values["date_to"],
                    values["status"],
                    values["notes"],
                    json.dumps(values["filters"], sort_keys=True, separators=(",", ":")),
                    values.get("ai_run_ref"),
                    values["property_validation_state"],
                    timestamp,
                    timestamp,
                ),
            )
            connection.commit()
        created = self.get_case(case_id)
        assert created is not None
        return created

    def update_case(
        self, case_id: str, changes: Mapping[str, Any], *, expected_version: int
    ) -> dict[str, Any] | None:
        allowed = {
            "name",
            "address_display",
            "date_from",
            "date_to",
            "status",
            "notes",
            "filters_json",
            "ai_run_ref",
        }
        values = dict(changes)
        if "filters" in values:
            values["filters_json"] = json.dumps(
                values.pop("filters"), sort_keys=True, separators=(",", ":")
            )
        values = {key: value for key, value in values.items() if key in allowed}
        if not values:
            return self.get_case(case_id)
        assignments = ", ".join(f"{key} = ?" for key in values)
        parameters = [*values.values(), _now(), case_id, expected_version]
        with self._connect() as connection:
            cursor = connection.execute(
                f"UPDATE market_case SET {assignments}, updated_at = ?, "
                "version = version + 1 WHERE id = ? AND version = ?",
                parameters,
            )
            if cursor.rowcount == 0:
                exists = connection.execute(
                    "SELECT 1 FROM market_case WHERE id = ?", (case_id,)
                ).fetchone()
                if exists is not None:
                    raise VersionConflictError("market case was changed by another request")
                return None
            connection.commit()
        return self.get_case(case_id)

    def delete_case(self, case_id: str) -> bool:
        with self._connect() as connection:
            deleted = connection.execute(
                "DELETE FROM market_case WHERE id = ?", (case_id,)
            ).rowcount
            connection.commit()
        return bool(deleted)

    def list_sales(self, property_ref: str, *, limit: int = 5000) -> list[dict[str, Any]]:
        with self._connect() as connection:
            current = connection.execute(
                "SELECT release_id FROM sales_current_generation WHERE dataset_id='nsw-psi-sales'"
            ).fetchone()
            if current:
                rows = connection.execute(
                    "SELECT record_json FROM sale_generation_record WHERE release_id=? "
                    "AND property_ref=? ORDER BY contract_date DESC,source_business_key LIMIT ?",
                    (current["release_id"], property_ref, limit),
                ).fetchall()
                return [json.loads(row["record_json"]) for row in rows]
            rows = connection.execute(
                """
                SELECT * FROM sale_observation
                WHERE property_ref = ?
                ORDER BY contract_date DESC, source_business_key
                LIMIT ?
                """,
                (property_ref, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def import_sales(self, records: Sequence[Mapping[str, Any]]) -> dict[str, int]:
        inserted = 0
        with self._connect() as connection:
            for record in records:
                cursor = connection.execute(
                    """
                    INSERT OR IGNORE INTO sale_observation (
                        id, source_business_key, source_revision, source_era,
                        property_ref, address_display, contract_date, settlement_date,
                        price_aud, area_square_metres, locality, postcode, sale_code,
                        interest_of_sale, match_tier, match_confidence,
                        geographic_precision, release_id, release_version,
                        source_record_sha256, normalisation_version, synthetic, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(uuid.uuid4()),
                        record["source_business_key"],
                        record["source_revision"],
                        record["source_era"],
                        record.get("property_ref"),
                        record["address_display"],
                        record.get("contract_date"),
                        record.get("settlement_date"),
                        record.get("price_aud"),
                        record.get("area_square_metres"),
                        record.get("locality"),
                        record.get("postcode"),
                        record.get("sale_code"),
                        record.get("interest_of_sale"),
                        record["match_tier"],
                        record["match_confidence"],
                        record["geographic_precision"],
                        record["release_id"],
                        record["release_version"],
                        record["source_record_sha256"],
                        record["normalisation_version"],
                        int(bool(record.get("synthetic", False))),
                        _now(),
                    ),
                )
                inserted += cursor.rowcount
            connection.commit()
        return {"received": len(records), "inserted": inserted, "replayed": len(records) - inserted}
