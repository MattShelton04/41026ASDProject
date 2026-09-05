"""Durable, leased imports and isolated release records owned only by this database."""

from __future__ import annotations

import json
import time
from typing import Any
from uuid import uuid4

from shared_consumer_protocol import ImportReceipt

from .repository import Repository

SCHEMA = """
CREATE TABLE IF NOT EXISTS source_imports (
 id TEXT PRIMARY KEY, release_id TEXT NOT NULL, delivery_key TEXT UNIQUE NOT NULL,
 request_json TEXT NOT NULL, correlation_json TEXT NOT NULL, status TEXT NOT NULL,
 token TEXT, lease_until REAL NOT NULL DEFAULT 0, receipt_json TEXT,
 attempt_number INTEGER NOT NULL DEFAULT 0, next_attempt_at REAL NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS source_records (
 operation_id TEXT NOT NULL, ordinal INTEGER NOT NULL, record_key TEXT NOT NULL,
 locality TEXT, record_json TEXT NOT NULL,
 PRIMARY KEY(operation_id, ordinal), UNIQUE(operation_id, record_key)
);
CREATE INDEX IF NOT EXISTS source_locality ON source_records(operation_id, locality);
CREATE TABLE IF NOT EXISTS source_current (dataset_id TEXT PRIMARY KEY, operation_id TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS source_deliveries (
 delivery_key TEXT PRIMARY KEY, operation_id TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS source_attempt_receipts (
 operation_id TEXT NOT NULL, receipt_json TEXT NOT NULL, retained_at REAL NOT NULL);
"""


def normalise(value: str) -> str:
    return " ".join(value.upper().split())


class Imports:
    def __init__(self, repository: Repository) -> None:
        self.repository = repository
        with repository.connect() as db:
            db.executescript(SCHEMA)
            db.execute("BEGIN IMMEDIATE")
            if "attempt_number" not in {
                row[1] for row in db.execute("PRAGMA table_info(source_imports)")
            }:
                # Preserve every operation and delivery alias while allowing failed attempt history.
                db.execute("ALTER TABLE source_imports RENAME TO source_imports_legacy")
                db.execute(SCHEMA.split(";", 1)[0])
                columns = (
                    "id,release_id,delivery_key,request_json,correlation_json,status,"
                    "token,lease_until,receipt_json"
                )
                db.execute(
                    f"INSERT INTO source_imports ({columns}) "
                    f"SELECT {columns} FROM source_imports_legacy"
                )
                db.execute("DROP TABLE source_imports_legacy")
            db.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS source_import_live_release "
                "ON source_imports(release_id) WHERE status <> 'failed'"
            )

    @staticmethod
    def acknowledgement(row: Any) -> dict[str, Any]:
        if row["receipt_json"]:
            return dict(json.loads(row["receipt_json"]))
        request = json.loads(row["request_json"])
        return {
            key: request[key]
            for key in (
                "release_id",
                "dataset_id",
                "schema_version",
                "content_sha256",
                "record_count",
            )
        } | {
            "consumer_operation_id": row["id"],
            "status": row["status"],
            "target": request["manifest"]["target_feature"],
        }

    def enqueue(self, payload: dict[str, Any]) -> dict[str, Any]:
        request = payload["request"]
        with self.repository.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            rows = db.execute(
                "SELECT * FROM source_imports WHERE delivery_key=? "
                "OR id IN (SELECT operation_id FROM source_deliveries WHERE delivery_key=?)",
                (request["idempotency_key"], request["idempotency_key"]),
            ).fetchall()
            if not rows:
                rows = db.execute(
                    "SELECT * FROM source_imports WHERE release_id=? ORDER BY rowid DESC LIMIT 1",
                    (request["release_id"],),
                ).fetchall()
                if rows and rows[0]["status"] == "failed":
                    old = json.loads(rows[0]["request_json"])
                    if any(old[k] != request[k] for k in request if k != "idempotency_key"):
                        raise ValueError("import_identity_conflict")
                    rows = []
            if rows:
                old = json.loads(rows[0]["request_json"])
                if len(rows) != 1 or any(
                    old[k] != request[k] for k in request if k != "idempotency_key"
                ):
                    raise ValueError("import_identity_conflict")
                db.execute(
                    "INSERT OR IGNORE INTO source_deliveries VALUES (?,?)",
                    (request["idempotency_key"], rows[0]["id"]),
                )
                return self.acknowledgement(rows[0])
            operation = str(uuid4())
            db.execute(
                "INSERT INTO source_imports(id,release_id,delivery_key,request_json,"
                "correlation_json,status) VALUES (?,?,?,?,?,'queued')",
                (
                    operation,
                    request["release_id"],
                    request["idempotency_key"],
                    json.dumps(request),
                    json.dumps(payload["correlation"]),
                ),
            )
            row = db.execute("SELECT * FROM source_imports WHERE id=?", (operation,)).fetchone()
            return self.acknowledgement(row)

    def status(self, operation: str) -> dict[str, Any]:
        with self.repository.connect() as db:
            row = db.execute("SELECT * FROM source_imports WHERE id=?", (operation,)).fetchone()
            if row is None:
                raise ValueError("import_not_found")
            return self.acknowledgement(row)

    def claim(self) -> dict[str, Any]:
        with self.repository.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT * FROM source_imports WHERE (status='queued' AND next_attempt_at<=?) OR "
                "(status='running' AND lease_until<?) ORDER BY rowid LIMIT 1",
                (time.time(), time.time()),
            ).fetchone()
            if row is None:
                return {}
            token = str(uuid4())
            db.execute(
                "UPDATE source_imports SET status='running',token=?,lease_until=?,"
                "attempt_number=attempt_number+1 WHERE id=?",
                (token, time.time() + 180, row["id"]),
            )
            return {
                "id": row["id"],
                "token": token,
                "request": json.loads(row["request_json"]),
                "correlation": json.loads(row["correlation_json"]),
            }

    def retry(self, operation: str) -> dict[str, Any]:
        with self.repository.connect() as db:
            row = db.execute("SELECT * FROM source_imports WHERE id=?", (operation,)).fetchone()
            if row is None or row["status"] != "failed":
                raise ValueError("import_retry_conflict")
            request = json.loads(row["request_json"])
            request["idempotency_key"] = f"retry-{operation}"
            correlation = json.loads(row["correlation_json"])
        return self.enqueue({"request": request, "correlation": correlation})

    def apply(self, operation: str, action: str, payload: dict[str, Any]) -> dict[str, Any]:
        with self.repository.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM source_imports WHERE id=?", (operation,)).fetchone()
            if (
                row is None
                or row["status"] != "running"
                or row["token"] != payload["token"]
                or row["lease_until"] < time.time()
            ):
                raise ValueError("import_lease_conflict")
            request = json.loads(row["request_json"])
            if action == "stage":
                for item in payload["items"]:
                    record = item["record"]
                    dataset = request["dataset_id"]
                    if dataset == "bocsar-crime":
                        key = json.dumps(
                            [
                                record["geography_kind"],
                                record["geography_value"],
                                record["source_category_key"],
                            ]
                        )
                        locality = (
                            record["geography_value"]
                            if record["geography_kind"] == "suburb"
                            else None
                        )
                    elif dataset == "abs-seifa-2021":
                        key, locality = record["sal_code"], record["locality_name"]
                    else:
                        key, locality = record["school_code"], record["locality_normalised"]
                    staged = db.execute(
                        "INSERT INTO source_records VALUES (?,?,?,?,?) "
                        "ON CONFLICT(operation_id,ordinal) DO UPDATE "
                        "SET record_json=excluded.record_json "
                        "WHERE source_records.record_key=excluded.record_key "
                        "AND source_records.record_json=excluded.record_json",
                        (
                            operation,
                            item["ordinal"],
                            key,
                            normalise(locality) if locality else None,
                            json.dumps(record),
                        ),
                    )
                    if staged.rowcount != 1:
                        raise ValueError("import_staging_evidence_conflict")
                db.execute(
                    "UPDATE source_imports SET lease_until=? WHERE id=?",
                    (time.time() + 180, operation),
                )
            elif action in {"commit", "fail"}:
                receipt = ImportReceipt.model_validate(payload["receipt"]).model_dump(mode="json")
                if receipt["target"] != request["manifest"]["target_feature"]:
                    raise ValueError("import_target_mismatch")
                if receipt["consumer_operation_id"] != operation or any(
                    receipt[k] != request[k]
                    for k in (
                        "release_id",
                        "dataset_id",
                        "schema_version",
                        "content_sha256",
                        "record_count",
                    )
                ):
                    raise ValueError("import_identity_conflict")
                if action == "commit":
                    count = db.execute(
                        "SELECT COUNT(*) FROM source_records WHERE operation_id=?", (operation,)
                    ).fetchone()[0]
                    if count != request["record_count"] or receipt["status"] != "accepted":
                        raise ValueError("import_count_mismatch")
                    db.execute(
                        "INSERT INTO source_current VALUES (?,?) ON CONFLICT(dataset_id) "
                        "DO UPDATE SET operation_id=excluded.operation_id",
                        (request["dataset_id"], operation),
                    )
                else:
                    if receipt["status"] == "accepted":
                        raise ValueError("invalid_failure_receipt")
                    error = receipt.get("error") or {}
                    if error.get("retryable") is True and row["attempt_number"] < 5:
                        db.execute(
                            "INSERT INTO source_attempt_receipts VALUES (?,?,?)",
                            (operation, json.dumps(receipt), time.time()),
                        )
                        db.execute(
                            "UPDATE source_imports SET status='queued',token=NULL,"
                            "next_attempt_at=? WHERE id=?",
                            (time.time() + min(2 ** row["attempt_number"], 30), operation),
                        )
                        return {"ok": True}
                    db.execute("DELETE FROM source_records WHERE operation_id=?", (operation,))
                db.execute(
                    "UPDATE source_imports SET status=?,receipt_json=?,token=NULL WHERE id=?",
                    (receipt["status"], json.dumps(receipt), operation),
                )
            else:
                raise ValueError("invalid_import_action")
        return {"ok": True}

    def sources(self) -> dict[str, Any]:
        with self.repository.connect() as db:
            rows = db.execute(
                "SELECT i.*,c.dataset_id AS active FROM source_imports i "
                "LEFT JOIN source_current c "
                "ON c.operation_id=i.id ORDER BY i.rowid DESC LIMIT 30"
            ).fetchall()
            return {
                "items": [
                    self.acknowledgement(row)
                    | {
                        "active": row["active"] is not None,
                        "manifest": manifest_summary(json.loads(row["request_json"])["manifest"]),
                    }
                    for row in rows
                ]
            }

    def localities(self, query: str, offset: int = 0) -> dict[str, Any]:
        with self.repository.connect() as db:
            rows = db.execute(
                "SELECT DISTINCT r.locality FROM source_records r JOIN source_current c "
                "ON c.operation_id=r.operation_id WHERE r.locality IS NOT NULL "
                "AND instr(r.locality,?)>0 ORDER BY r.locality LIMIT 51 OFFSET ?",
                (normalise(query), max(offset, 0)),
            ).fetchall()
            return {
                "items": [row[0] for row in rows[:50]],
                "next_offset": offset + 50 if len(rows) > 50 else None,
            }

    def context(self, locality: str) -> dict[str, Any]:
        result: dict[str, Any] = {
            "locality": locality,
            "population": [],
            "schools": [],
            "crime": [],
            "sources": [],
        }
        with self.repository.connect() as db:
            db.execute("BEGIN")
            sources = db.execute(
                "SELECT c.dataset_id,i.request_json,i.id FROM source_current c "
                "JOIN source_imports i ON i.id=c.operation_id"
            ).fetchall()
            for source in sources:
                manifest = json.loads(source["request_json"])["manifest"]
                result["sources"].append(manifest_summary(manifest))
                rows = db.execute(
                    "SELECT record_json FROM source_records WHERE operation_id=? AND locality=? "
                    "ORDER BY record_key LIMIT 501",
                    (source["id"], normalise(locality)),
                ).fetchall()
                if len(rows) > 500:
                    raise ValueError("context_capacity_exceeded")
                key = {
                    "bocsar-crime": "crime",
                    "abs-seifa-2021": "population",
                    "nsw-government-schools": "schools",
                }[source["dataset_id"]]
                result[key] = [json.loads(row[0]) for row in rows]
        result["limitations"] = [
            "Exact source locality names only; no boundary or postcode-to-suburb inference.",
            "Population is 2021 Census context, not a current crime-rate denominator.",
            "School locations do not establish catchment or eligibility.",
            "Absent evidence is unavailable, not zero. Multiple population matches are ambiguous.",
        ]
        return result


def manifest_summary(manifest: dict[str, Any]) -> dict[str, Any]:
    return {
        key: manifest.get(key)
        for key in (
            "release_id",
            "dataset_id",
            "source",
            "source_release",
            "publisher",
            "source_licence",
            "licence_url",
            "source_retrieved_at",
            "temporal_coverage",
            "known_limitations",
        )
    }
