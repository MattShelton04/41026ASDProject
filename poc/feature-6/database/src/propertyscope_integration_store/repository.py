"""SQLite repository for the Feature 6 integration proof of concept.

The repository deliberately preserves upstream release evidence and owns only POC
interpretations. It never manufactures planning, hazard, strata, or building facts.
"""

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
import statistics
import uuid
from collections.abc import Iterable, Iterator, Mapping
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .errors import ConflictError, NotFoundError, ValidationError
from .schema import migrate

JsonObject = Mapping[str, Any]

SUPPORTED_IMPORTS = {
    "nsw-psi-sales": "propertyscope.property-sales.v2",
    "bocsar-crime": "propertyscope.crime-series.v1",
    "nsw-government-schools": "propertyscope.school-points.v1",
}
SUPPORTED_TARGETS = {
    "nsw-psi-sales": "feature-2",
    "bocsar-crime": "feature-3",
    "nsw-government-schools": "feature-3",
}


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _identifier(value: object, field: str) -> str:
    text = str(value or "").strip()
    if not text or len(text) > 200:
        raise ValidationError(f"{field} must be a non-empty string of at most 200 characters")
    return text


def _uuid(value: object, field: str) -> str:
    text = _identifier(value, field)
    try:
        return str(uuid.UUID(text))
    except ValueError as exc:
        raise ValidationError(f"{field} must be a UUID") from exc


def _optional_date(value: object, field: str) -> str | None:
    if value is None or value == "":
        return None
    text = str(value)
    try:
        datetime.strptime(text, "%Y-%m-%d")
    except ValueError as exc:
        raise ValidationError(f"{field} must be an ISO date") from exc
    return text


def _bounded_text(value: object, field: str, *, maximum: int = 4_000) -> str:
    text = str(value or "").strip()
    if not text or len(text) > maximum:
        raise ValidationError(f"{field} must contain 1 to {maximum} characters")
    return text


def _optional_int(value: object, field: str, *, minimum: int = 0) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise ValidationError(f"{field} must be an integer")
    if isinstance(value, int):
        result = value
    elif isinstance(value, str) and value.removeprefix("-").isdigit():
        result = int(value)
    else:
        raise ValidationError(f"{field} must be an integer")
    if result < minimum:
        raise ValidationError(f"{field} must be at least {minimum}")
    return result


def _coordinate(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ValidationError(f"{field} must be a number")
    try:
        return float(value)
    except ValueError as exc:
        raise ValidationError(f"{field} must be a number") from exc


def _json_object(value: str, field: str) -> dict[str, Any]:
    loaded = json.loads(value)
    if not isinstance(loaded, dict):
        raise ConflictError(f"retained {field} is not a JSON object")
    return loaded


def _new_id(value: object | None = None) -> str:
    return _uuid(value, "id") if value else str(uuid.uuid4())


class IntegrationStore:
    """Own one SQLite file and expose deterministic POC persistence operations."""

    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path)

    def initialise(self) -> None:
        """Create the database and apply idempotent migrations."""
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as connection:
            migrate(connection)

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.database_path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 10000")
        try:
            yield connection
        finally:
            connection.close()

    def ready(self) -> bool:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT max(version) AS version FROM schema_migration"
            ).fetchone()
        return row is not None and row["version"] is not None

    def import_release(
        self,
        *,
        target_feature: str,
        idempotency_key: str,
        provider_release_id: str,
        dataset_id: str,
        schema_version: str,
        content_sha256: str,
        record_count: int,
        records: Iterable[JsonObject],
        request_evidence: JsonObject | None = None,
    ) -> dict[str, Any]:
        """Atomically retain one supported release, returning an idempotent receipt."""
        target = _identifier(target_feature, "target_feature")
        key = _identifier(idempotency_key, "idempotency_key")
        if len(key) < 8:
            raise ValidationError("idempotency_key must contain at least 8 characters")
        release_id = _uuid(provider_release_id, "provider_release_id")
        expected_schema = SUPPORTED_IMPORTS.get(dataset_id)
        if expected_schema is None:
            raise ValidationError(f"unsupported POC dataset: {dataset_id}")
        if schema_version != expected_schema:
            raise ValidationError(
                f"{dataset_id} requires {expected_schema}, received {schema_version}"
            )
        if target != SUPPORTED_TARGETS[dataset_id]:
            raise ValidationError(f"{dataset_id} is registered for {SUPPORTED_TARGETS[dataset_id]}")
        if not isinstance(record_count, int) or isinstance(record_count, bool) or record_count < 0:
            raise ValidationError("record_count must be a non-negative integer")
        if len(content_sha256) != 64 or any(c not in "0123456789abcdef" for c in content_sha256):
            raise ValidationError("content_sha256 must be a lowercase SHA-256 digest")
        request_sha = hashlib.sha256(
            _json(
                {
                    "provider_release_id": release_id,
                    "target_feature": target,
                    "dataset_id": dataset_id,
                    "schema_version": schema_version,
                    "content_sha256": content_sha256,
                    "record_count": record_count,
                    "request": request_evidence or {},
                }
            ).encode("utf-8")
        ).hexdigest()
        imported_at = _now()

        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            retained = connection.execute(
                """SELECT request_sha256, receipt_json FROM release_import
                   WHERE target_feature=? AND idempotency_key=?""",
                (target, key),
            ).fetchone()
            if retained is not None:
                if retained["request_sha256"] != request_sha:
                    connection.rollback()
                    raise ConflictError("idempotency key is already bound to different evidence")
                connection.rollback()
                replay_receipt = _json_object(retained["receipt_json"], "receipt")
                replay_receipt["replayed"] = True
                return replay_receipt
            duplicate = connection.execute(
                """SELECT target_feature, schema_version, content_sha256, record_count,
                          receipt_json
                   FROM release_import
                   WHERE dataset_id=? AND provider_release_id=?""",
                (dataset_id, release_id),
            ).fetchone()
            if duplicate is not None:
                duplicate_evidence = (
                    duplicate["target_feature"],
                    duplicate["schema_version"],
                    duplicate["content_sha256"],
                    duplicate["record_count"],
                )
                requested_evidence = (target, schema_version, content_sha256, record_count)
                connection.rollback()
                if duplicate_evidence != requested_evidence:
                    raise ConflictError("provider release was imported with different evidence")
                replay_receipt = _json_object(duplicate["receipt_json"], "receipt")
                replay_receipt["replayed"] = True
                return replay_receipt
            try:
                if dataset_id == "nsw-psi-sales":
                    accepted_count = self._import_sales(connection, release_id, records)
                elif dataset_id == "bocsar-crime":
                    accepted_count = self._import_crime(connection, release_id, records)
                else:
                    accepted_count = self._import_schools(connection, release_id, records)
                if accepted_count != record_count:
                    raise ValidationError(
                        f"record_count declares {record_count}, "
                        f"stream contained {accepted_count} records"
                    )
                receipt = {
                    "consumer_operation_id": key,
                    "status": "accepted",
                    "schema_version": schema_version,
                    "content_sha256": content_sha256,
                    "rows_received": accepted_count,
                    "rows_accepted": accepted_count,
                    "rows_rejected": 0,
                    "error": None,
                    "provider_release_id": release_id,
                    "dataset_id": dataset_id,
                    "target_feature": target,
                    "replayed": False,
                }
                connection.execute(
                    """INSERT INTO release_import(
                           target_feature,idempotency_key,request_sha256,provider_release_id,dataset_id,
                           schema_version,content_sha256,record_count,request_json,rows_accepted,status,
                           receipt_json,imported_at
                       ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        target,
                        key,
                        request_sha,
                        release_id,
                        dataset_id,
                        schema_version,
                        content_sha256,
                        accepted_count,
                        _json(request_evidence or {}),
                        record_count,
                        "accepted",
                        _json(receipt),
                        imported_at,
                    ),
                )
                connection.commit()
                return receipt
            except sqlite3.IntegrityError as exc:
                connection.rollback()
                raise ConflictError("release contains conflicting record identities") from exc
            except Exception:
                connection.rollback()
                raise

    @staticmethod
    def _import_sales(
        connection: sqlite3.Connection, release_id: str, records: Iterable[JsonObject]
    ) -> int:
        rows: list[tuple[object, ...]] = []
        count = 0
        for record in records:
            business_key = _identifier(record.get("source_business_key"), "source_business_key")
            revision = _optional_int(record.get("source_revision"), "source_revision", minimum=1)
            if revision is None:
                raise ValidationError("source_revision is required")
            property_value = record.get("property_ref")
            property_ref = _uuid(property_value, "property_ref") if property_value else None
            price = _optional_int(record.get("price_aud"), "price_aud")
            provenance = record.get("provenance")
            if not isinstance(provenance, Mapping):
                raise ValidationError("sale provenance must be an object")
            if provenance.get("release_id") != release_id:
                raise ValidationError("sale provenance release_id does not match the import")
            rows.append(
                (
                    release_id,
                    business_key,
                    revision,
                    property_ref,
                    _optional_date(record.get("contract_date"), "contract_date"),
                    _optional_date(record.get("settlement_date"), "settlement_date"),
                    price,
                    str(record.get("locality") or "") or None,
                    str(record.get("postcode") or "") or None,
                    str(record.get("match_tier") or "") or None,
                    _json(provenance),
                    _json(record),
                )
            )
            count += 1
            if len(rows) == 1_000:
                connection.executemany(
                    "INSERT INTO sale_observation VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", rows
                )
                rows.clear()
        if rows:
            connection.executemany(
                "INSERT INTO sale_observation VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", rows
            )
        return count

    @staticmethod
    def _import_crime(
        connection: sqlite3.Connection, release_id: str, records: Iterable[JsonObject]
    ) -> int:
        rows: list[tuple[object, ...]] = []
        count = 0
        for record in records:
            if record.get("geography_kind") != "postcode":
                raise ValidationError("crime geography_kind must be postcode")
            postcode = _identifier(record.get("geography_value"), "geography_value")
            if len(postcode) != 4 or not postcode.isdigit():
                raise ValidationError("crime geography_value must be a four-digit postcode")
            observed = record.get("observed_months")
            observations = record.get("observations")
            provenance = record.get("provenance")
            if not isinstance(observed, list) or not isinstance(observations, list):
                raise ValidationError("crime observed_months and observations must be arrays")
            if not isinstance(provenance, Mapping):
                raise ValidationError("crime provenance must be an object")
            if provenance.get("release_id") != release_id:
                raise ValidationError("crime provenance release_id does not match the import")
            blank_zero = record.get("blank_means_observed_zero")
            if not isinstance(blank_zero, bool):
                raise ValidationError("blank_means_observed_zero must be a boolean")
            for month in observed:
                _optional_date(month, "observed_month")
            for observation in observations:
                if not isinstance(observation, Mapping):
                    raise ValidationError("each crime observation must be an object")
                _optional_date(observation.get("month"), "observation.month")
                _optional_int(observation.get("count"), "observation.count")
            first_month = _optional_date(record.get("first_month"), "first_month")
            last_month = _optional_date(record.get("last_month"), "last_month")
            if first_month is None or last_month is None:
                raise ValidationError("crime coverage bounds are required")
            rows.append(
                (
                    release_id,
                    postcode,
                    _identifier(record.get("source_category_key"), "source_category_key"),
                    _bounded_text(record.get("offence_label"), "offence_label", maximum=500),
                    str(record.get("subcategory_label") or "") or None,
                    first_month,
                    last_month,
                    _json(observed),
                    int(blank_zero),
                    _json(observations),
                    _json(provenance),
                )
            )
            count += 1
            if len(rows) == 1_000:
                connection.executemany(
                    "INSERT INTO crime_series VALUES (?,?,?,?,?,?,?,?,?,?,?)", rows
                )
                rows.clear()
        if rows:
            connection.executemany("INSERT INTO crime_series VALUES (?,?,?,?,?,?,?,?,?,?,?)", rows)
        return count

    @staticmethod
    def _import_schools(
        connection: sqlite3.Connection, release_id: str, records: Iterable[JsonObject]
    ) -> int:
        rows: list[tuple[object, ...]] = []
        count = 0
        for record in records:
            latitude = _coordinate(record.get("latitude"), "latitude")
            longitude = _coordinate(record.get("longitude"), "longitude")
            if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
                raise ValidationError("school coordinates are outside WGS84 bounds")
            provenance = record.get("provenance")
            if not isinstance(provenance, Mapping):
                raise ValidationError("school provenance must be an object")
            if provenance.get("release_id") != release_id:
                raise ValidationError("school provenance release_id does not match the import")
            rows.append(
                (
                    release_id,
                    _identifier(record.get("school_code"), "school_code"),
                    _bounded_text(record.get("school_name"), "school_name", maximum=500),
                    _identifier(record.get("school_type"), "school_type"),
                    _identifier(record.get("operational_status"), "operational_status"),
                    _identifier(
                        record.get("locality_normalised") or record.get("locality_original"),
                        "locality",
                    ),
                    str(record.get("lga") or "") or None,
                    latitude,
                    longitude,
                    _json(provenance),
                )
            )
            count += 1
            if len(rows) == 1_000:
                connection.executemany(
                    "INSERT INTO school_point VALUES (?,?,?,?,?,?,?,?,?,?)", rows
                )
                rows.clear()
        if rows:
            connection.executemany("INSERT INTO school_point VALUES (?,?,?,?,?,?,?,?,?,?)", rows)
        return count

    def list_imports(self) -> list[dict[str, Any]]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT * FROM release_import ORDER BY imported_at DESC, dataset_id"
            ).fetchall()
        return [self._row(row) for row in rows]

    def find_import(self, target_feature: str, idempotency_key: str) -> dict[str, Any]:
        """Return the complete retained request evidence and receipt for a publication key."""
        target = _identifier(target_feature, "target_feature")
        key = _identifier(idempotency_key, "idempotency_key")
        with self._connection() as connection:
            row = connection.execute(
                """SELECT request_json,receipt_json,imported_at
                   FROM release_import WHERE target_feature=? AND idempotency_key=?""",
                (target, key),
            ).fetchone()
        if row is None:
            raise NotFoundError("publication operation was not found")
        return {
            "request": _json_object(row["request_json"], "publication request"),
            "receipt": _json_object(row["receipt_json"], "receipt"),
            "imported_at": row["imported_at"],
        }

    def create_market_case(self, payload: JsonObject) -> dict[str, Any]:
        date_from = _optional_date(payload.get("date_from"), "date_from")
        date_to = _optional_date(payload.get("date_to"), "date_to")
        if date_from and date_to and date_from > date_to:
            raise ValidationError("date_from must not follow date_to")
        values = {
            "id": _new_id(payload.get("id")),
            "name": _bounded_text(payload.get("name"), "name", maximum=200),
            "property_ref": _uuid(payload.get("property_ref"), "property_ref"),
            "date_from": date_from,
            "date_to": date_to,
            "notes": str(payload.get("notes") or "")[:4_000],
            "status": str(payload.get("status") or "draft"),
            "filters_json": _json(payload.get("filters") or {}),
        }
        if values["status"] not in {"draft", "active", "complete", "archived"}:
            raise ValidationError("unsupported market case status")
        return self._create("market_case", values)

    def list_market_cases(self) -> list[dict[str, Any]]:
        return self._list("market_case")

    def get_market_case(self, case_id: str) -> dict[str, Any]:
        return self._get("market_case", case_id)

    def update_market_case(
        self, case_id: str, expected_version: int, payload: JsonObject
    ) -> dict[str, Any]:
        allowed = {"name", "property_ref", "date_from", "date_to", "notes", "status", "filters"}
        values = {key: value for key, value in payload.items() if key in allowed}
        if "property_ref" in values:
            values["property_ref"] = _uuid(values["property_ref"], "property_ref")
        for field in ("date_from", "date_to"):
            if field in values:
                values[field] = _optional_date(values[field], field)
        if "filters" in values:
            values["filters_json"] = _json(values.pop("filters"))
        if "name" in values:
            values["name"] = _bounded_text(values["name"], "name", maximum=200)
        if "status" in values and values["status"] not in {
            "draft",
            "active",
            "complete",
            "archived",
        }:
            raise ValidationError("unsupported market case status")
        return self._update("market_case", case_id, expected_version, values)

    def delete_market_case(self, case_id: str, expected_version: int) -> None:
        self._delete("market_case", case_id, expected_version)

    def sales_summary(self, case_id: str) -> dict[str, Any]:
        case = self._get("market_case", case_id)
        clauses = ["property_ref=?"]
        parameters: list[object] = [case["property_ref"]]
        if case["date_from"]:
            clauses.append("contract_date>=?")
            parameters.append(case["date_from"])
        if case["date_to"]:
            clauses.append("contract_date<=?")
            parameters.append(case["date_to"])
        predicate = " AND ".join(clauses)
        query = f"""
            WITH ranked AS (
              SELECT *, row_number() OVER (
                PARTITION BY source_business_key ORDER BY source_revision DESC
              ) AS revision_rank
              FROM sale_observation
              WHERE provider_release_id=(
                SELECT provider_release_id FROM release_import
                WHERE dataset_id='nsw-psi-sales' AND status='accepted'
                ORDER BY imported_at DESC,provider_release_id DESC LIMIT 1
              ) AND {predicate}
            ) SELECT * FROM ranked ORDER BY contract_date, source_business_key
        """
        with self._connection() as connection:
            rows = connection.execute(query, parameters).fetchall()
        latest = [row for row in rows if row["revision_rank"] == 1]
        prices = [row["price_aud"] for row in latest if row["price_aud"] is not None]
        volumes: dict[str, int] = {}
        for row in latest:
            if row["contract_date"]:
                period = row["contract_date"][:7]
                volumes[period] = volumes.get(period, 0) + 1
        return {
            "market_case_id": case_id,
            "policy": "poc-latest-source-revision.v1",
            "observation_count": len(rows),
            "selected_transaction_count": len(latest),
            "priced_sample_count": len(prices),
            "median_price_aud": statistics.median(prices) if prices else None,
            "volume_by_month": [
                {"month": month, "count": count} for month, count in sorted(volumes.items())
            ],
            "exclusions": {
                "superseded_source_revisions": len(rows) - len(latest),
                "missing_price": sum(row["price_aud"] is None for row in latest),
            },
            "limitations": [
                "This is a transparent POC policy, not an approved comparable-sales policy.",
                "The summary does not estimate value or recommend whether to buy.",
            ],
        }

    def create_saved_place(self, payload: JsonObject) -> dict[str, Any]:
        postcode = _identifier(payload.get("postcode"), "postcode")
        if len(postcode) != 4 or not postcode.isdigit():
            raise ValidationError("postcode must contain four digits")
        return self._create(
            "saved_place",
            {
                "id": _new_id(payload.get("id")),
                "actor_ref": _identifier(payload.get("actor_ref"), "actor_ref"),
                "locality": _bounded_text(payload.get("locality"), "locality", maximum=100),
                "postcode": postcode,
                "favourite": int(bool(payload.get("favourite", False))),
                "notes": str(payload.get("notes") or "")[:4_000],
            },
        )

    def list_saved_places(self) -> list[dict[str, Any]]:
        return self._list("saved_place")

    def get_saved_place(self, place_id: str) -> dict[str, Any]:
        return self._get("saved_place", place_id)

    def update_saved_place(
        self, place_id: str, expected_version: int, payload: JsonObject
    ) -> dict[str, Any]:
        allowed = {"locality", "postcode", "favourite", "notes"}
        values = {key: value for key, value in payload.items() if key in allowed}
        if "favourite" in values:
            values["favourite"] = int(bool(values["favourite"]))
        if "postcode" in values:
            postcode = _identifier(values["postcode"], "postcode")
            if len(postcode) != 4 or not postcode.isdigit():
                raise ValidationError("postcode must contain four digits")
            values["postcode"] = postcode
        if "locality" in values:
            values["locality"] = _bounded_text(values["locality"], "locality", maximum=100)
        return self._update("saved_place", place_id, expected_version, values)

    def delete_saved_place(self, place_id: str, expected_version: int) -> None:
        self._delete("saved_place", place_id, expected_version)

    def place_summary(
        self, postcode: str, *, latitude: float | None = None, longitude: float | None = None
    ) -> dict[str, Any]:
        postcode = _identifier(postcode, "postcode")
        with self._connection() as connection:
            crime_rows = connection.execute(
                """SELECT * FROM crime_series
                   WHERE provider_release_id=(
                     SELECT provider_release_id FROM release_import
                     WHERE dataset_id='bocsar-crime' AND status='accepted'
                     ORDER BY imported_at DESC,provider_release_id DESC LIMIT 1
                   ) AND postcode=? ORDER BY offence_label""",
                (postcode,),
            ).fetchall()
            school_rows = connection.execute(
                """SELECT * FROM school_point
                   WHERE provider_release_id=(
                     SELECT provider_release_id FROM release_import
                     WHERE dataset_id='nsw-government-schools' AND status='accepted'
                     ORDER BY imported_at DESC,provider_release_id DESC LIMIT 1
                   ) ORDER BY school_name"""
            ).fetchall()
        crime = []
        for row in crime_rows:
            observations = json.loads(row["observations_json"])
            crime.append(
                {
                    "category": row["offence_label"],
                    "observed_count": sum(item["count"] for item in observations),
                    "first_month": row["first_month"],
                    "last_month": row["last_month"],
                    "blank_means_observed_zero": bool(row["blank_means_observed_zero"]),
                }
            )
        schools: list[dict[str, Any]] = []
        if latitude is not None and longitude is not None:
            for row in school_rows:
                distance = _haversine_km(latitude, longitude, row["latitude"], row["longitude"])
                schools.append(
                    {
                        "school_code": row["school_code"],
                        "school_name": row["school_name"],
                        "operational_status": row["operational_status"],
                        "distance_km": round(distance, 3),
                    }
                )
            schools.sort(key=lambda item: (item["distance_km"], item["school_code"]))
        return {
            "postcode": postcode,
            "crime_series": crime,
            "nearby_schools": schools[:25],
            "limitations": [
                "Crime evidence is postcode-level raw recorded counts, not a suburb safety score.",
                "School distance is straight-line only and does not imply "
                "catchment or eligibility.",
                "No population denominator or general liveability index is available.",
            ],
        }

    def create_site_review(self, payload: JsonObject) -> dict[str, Any]:
        status = str(payload.get("status") or "draft")
        if status not in {"draft", "in_review", "complete", "archived"}:
            raise ValidationError("unsupported site review status")
        return self._create(
            "site_review",
            {
                "id": _new_id(payload.get("id")),
                "property_ref": _uuid(payload.get("property_ref"), "property_ref"),
                "name": _bounded_text(payload.get("name"), "name", maximum=200),
                "status": status,
                "disposition": str(payload.get("disposition") or "")[:1_000],
                "notes": str(payload.get("notes") or "")[:4_000],
            },
        )

    def list_site_reviews(self) -> list[dict[str, Any]]:
        return self._list("site_review")

    def get_site_review(self, review_id: str) -> dict[str, Any]:
        return self._get("site_review", review_id)

    def update_site_review(
        self, review_id: str, expected_version: int, payload: JsonObject
    ) -> dict[str, Any]:
        allowed = {"name", "status", "disposition", "notes"}
        values = {key: value for key, value in payload.items() if key in allowed}
        if "status" in values and values["status"] not in {
            "draft",
            "in_review",
            "complete",
            "archived",
        }:
            raise ValidationError("unsupported site review status")
        if "name" in values:
            values["name"] = _bounded_text(values["name"], "name", maximum=200)
        return self._update("site_review", review_id, expected_version, values)

    def delete_site_review(self, review_id: str, expected_version: int) -> None:
        self._delete("site_review", review_id, expected_version)

    def add_site_item(self, review_id: str, payload: JsonObject) -> dict[str, Any]:
        self._get("site_review", review_id)
        kind = str(payload.get("item_kind") or "")
        if kind not in {"check", "question"}:
            raise ValidationError("item_kind must be check or question")
        return self._create(
            "site_review_item",
            {
                "id": _new_id(payload.get("id")),
                "site_review_id": review_id,
                "item_kind": kind,
                "text": _bounded_text(payload.get("text"), "text"),
                "completed": int(bool(payload.get("completed", False))),
            },
        )

    def list_site_items(self, review_id: str) -> list[dict[str, Any]]:
        self._get("site_review", review_id)
        return self._list("site_review_item", "site_review_id", review_id)

    def update_site_item(
        self, item_id: str, expected_version: int, payload: JsonObject
    ) -> dict[str, Any]:
        allowed = {"text", "completed"}
        values = {key: value for key, value in payload.items() if key in allowed}
        if "completed" in values:
            values["completed"] = int(bool(values["completed"]))
        if "text" in values:
            values["text"] = _bounded_text(values["text"], "text")
        return self._update("site_review_item", item_id, expected_version, values)

    def delete_site_item(self, item_id: str, expected_version: int) -> None:
        self._delete("site_review_item", item_id, expected_version)

    def site_evidence(self, review_id: str) -> dict[str, Any]:
        review = self._get("site_review", review_id)
        return {
            "site_review_id": review_id,
            "property_ref": review["property_ref"],
            "evidence": [
                {
                    "domain": domain,
                    "state": "unavailable",
                    "reason": "Feature 1 has no registered accepted product for this domain.",
                }
                for domain in ("planning", "environmental", "strata", "building")
            ],
            "limitations": [
                "The POC does not certify compliance, safety, or legal suitability.",
                "Historical PSI zoning fields are not treated as current planning evidence.",
            ],
        }

    def create_buyer_case(self, payload: JsonObject) -> dict[str, Any]:
        budget_min = _optional_int(payload.get("budget_min"), "budget_min")
        budget_max = _optional_int(payload.get("budget_max"), "budget_max")
        if budget_min is not None and budget_max is not None and budget_min > budget_max:
            raise ValidationError("budget_min must not exceed budget_max")
        status = str(payload.get("status") or "active")
        if status not in {"active", "paused", "closed", "archived"}:
            raise ValidationError("unsupported buyer case status")
        target_suburbs = payload.get("target_suburbs") or []
        preferences = payload.get("preferences") or {}
        if not isinstance(target_suburbs, list) or not all(
            isinstance(item, str) for item in target_suburbs
        ):
            raise ValidationError("target_suburbs must be an array of strings")
        if not isinstance(preferences, Mapping):
            raise ValidationError("preferences must be an object")
        return self._create(
            "buyer_case",
            {
                "id": _new_id(payload.get("id")),
                "actor_ref": _identifier(payload.get("actor_ref"), "actor_ref"),
                "name": _bounded_text(payload.get("name"), "name", maximum=200),
                "budget_min": budget_min,
                "budget_max": budget_max,
                "target_suburbs_json": _json(target_suburbs),
                "preferences_json": _json(preferences),
                "status": status,
            },
        )

    def list_buyer_cases(self) -> list[dict[str, Any]]:
        return self._list("buyer_case")

    def get_buyer_case(self, case_id: str) -> dict[str, Any]:
        return self._get("buyer_case", case_id)

    def update_buyer_case(
        self, case_id: str, expected_version: int, payload: JsonObject
    ) -> dict[str, Any]:
        allowed = {
            "name",
            "budget_min",
            "budget_max",
            "target_suburbs",
            "preferences",
            "status",
        }
        values = {key: value for key, value in payload.items() if key in allowed}
        current = self._get("buyer_case", case_id)
        if "name" in values:
            values["name"] = _bounded_text(values["name"], "name", maximum=200)
        for field in ("budget_min", "budget_max"):
            if field in values:
                values[field] = _optional_int(values[field], field)
        budget_min = values.get("budget_min", current["budget_min"])
        budget_max = values.get("budget_max", current["budget_max"])
        if budget_min is not None and budget_max is not None and budget_min > budget_max:
            raise ValidationError("budget_min must not exceed budget_max")
        if "status" in values and values["status"] not in {
            "active",
            "paused",
            "closed",
            "archived",
        }:
            raise ValidationError("unsupported buyer case status")
        for field in ("target_suburbs", "preferences"):
            if field in values:
                if field == "target_suburbs" and (
                    not isinstance(values[field], list)
                    or not all(isinstance(item, str) for item in values[field])
                ):
                    raise ValidationError("target_suburbs must be an array of strings")
                if field == "preferences" and not isinstance(values[field], Mapping):
                    raise ValidationError("preferences must be an object")
                values[f"{field}_json"] = _json(values.pop(field))
        return self._update("buyer_case", case_id, expected_version, values)

    def delete_buyer_case(self, case_id: str, expected_version: int) -> None:
        self._delete("buyer_case", case_id, expected_version)

    def add_case_property(self, case_id: str, payload: JsonObject) -> dict[str, Any]:
        self._get("buyer_case", case_id)
        stage = str(payload.get("stage") or "shortlisted")
        if stage not in {"shortlisted", "inspecting", "reviewing", "offer_considered", "closed"}:
            raise ValidationError("unsupported buyer journey stage")
        rating = _optional_int(payload.get("rating"), "rating", minimum=1)
        if rating is not None and rating > 5:
            raise ValidationError("rating must be between 1 and 5")
        return self._create(
            "case_property",
            {
                "id": _new_id(payload.get("id")),
                "buyer_case_id": case_id,
                "property_ref": _uuid(payload.get("property_ref"), "property_ref"),
                "stage": stage,
                "rating": rating,
            },
        )

    def add_case_note(self, case_id: str, payload: JsonObject) -> dict[str, Any]:
        self._get("buyer_case", case_id)
        return self._create(
            "case_note",
            {
                "id": _new_id(payload.get("id")),
                "buyer_case_id": case_id,
                "case_property_id": self._optional_child(case_id, payload.get("case_property_id")),
                "body": _bounded_text(payload.get("body"), "body"),
            },
        )

    def add_case_task(self, case_id: str, payload: JsonObject) -> dict[str, Any]:
        self._get("buyer_case", case_id)
        return self._create(
            "case_task",
            {
                "id": _new_id(payload.get("id")),
                "buyer_case_id": case_id,
                "case_property_id": self._optional_child(case_id, payload.get("case_property_id")),
                "title": _bounded_text(payload.get("title"), "title", maximum=500),
                "due_date": _optional_date(payload.get("due_date"), "due_date"),
                "completed": int(bool(payload.get("completed", False))),
            },
        )

    def list_case_children(self, case_id: str, kind: str) -> list[dict[str, Any]]:
        self._get("buyer_case", case_id)
        table = {"properties": "case_property", "notes": "case_note", "tasks": "case_task"}.get(
            kind
        )
        if table is None:
            raise ValidationError("unsupported buyer case child kind")
        return self._list(table, "buyer_case_id", case_id)

    def update_case_child(
        self, kind: str, child_id: str, expected_version: int, payload: JsonObject
    ) -> dict[str, Any]:
        definitions = {
            "properties": ("case_property", {"stage", "rating"}),
            "notes": ("case_note", {"body"}),
            "tasks": ("case_task", {"title", "due_date", "completed"}),
        }
        definition = definitions.get(kind)
        if definition is None:
            raise ValidationError("unsupported buyer case child kind")
        table, allowed = definition
        values = {key: value for key, value in payload.items() if key in allowed}
        if "completed" in values:
            values["completed"] = int(bool(values["completed"]))
        if "stage" in values and values["stage"] not in {
            "shortlisted",
            "inspecting",
            "reviewing",
            "offer_considered",
            "closed",
        }:
            raise ValidationError("unsupported buyer journey stage")
        if "rating" in values:
            values["rating"] = _optional_int(values["rating"], "rating", minimum=1)
            if values["rating"] is not None and values["rating"] > 5:
                raise ValidationError("rating must be between 1 and 5")
        if "due_date" in values:
            values["due_date"] = _optional_date(values["due_date"], "due_date")
        if "body" in values:
            values["body"] = _bounded_text(values["body"], "body")
        if "title" in values:
            values["title"] = _bounded_text(values["title"], "title", maximum=500)
        return self._update(table, child_id, expected_version, values)

    def delete_case_child(self, kind: str, child_id: str, expected_version: int) -> None:
        tables = {"properties": "case_property", "notes": "case_note", "tasks": "case_task"}
        table = tables.get(kind)
        if table is None:
            raise ValidationError("unsupported buyer case child kind")
        self._delete(table, child_id, expected_version)

    def buyer_summary(self, case_id: str) -> dict[str, Any]:
        case = self._get("buyer_case", case_id)
        properties = self.list_case_children(case_id, "properties")
        tasks = self.list_case_children(case_id, "tasks")
        notes = self.list_case_children(case_id, "notes")
        open_tasks = [task for task in tasks if not task["completed"]]
        missing = []
        if not properties:
            missing.append("No properties have been shortlisted.")
        if properties:
            missing.append("Planning, environmental, strata and building evidence is unavailable.")
        return {
            "buyer_case_id": case_id,
            "status": case["status"],
            "shortlist_count": len(properties),
            "open_task_count": len(open_tasks),
            "note_count": len(notes),
            "stage_counts": {
                stage: sum(item["stage"] == stage for item in properties)
                for stage in (
                    "shortlisted",
                    "inspecting",
                    "reviewing",
                    "offer_considered",
                    "closed",
                )
            },
            "missing_evidence": missing,
            "suggested_next_actions": [
                "Add a property before retrieving related evidence."
                if not properties
                else "Review the source-attributed sales and postcode context for each property.",
                "Record professional-verification questions for unavailable "
                "due-diligence evidence.",
            ],
            "limitations": [
                "Suggested actions are deterministic POC prompts, not recommendations."
            ],
        }

    def _optional_child(self, case_id: str, value: object) -> str | None:
        if not value:
            return None
        child_id = _uuid(value, "case_property_id")
        child = self._get("case_property", child_id)
        if child["buyer_case_id"] != case_id:
            raise ValidationError("case property belongs to another buyer case")
        return child_id

    def _create(self, table: str, values: dict[str, Any]) -> dict[str, Any]:
        timestamp = _now()
        record = {**values, "version": 1, "created_at": timestamp, "updated_at": timestamp}
        columns = ",".join(record)
        placeholders = ",".join("?" for _ in record)
        with self._connection() as connection:
            try:
                connection.execute(
                    f"INSERT INTO {table} ({columns}) VALUES ({placeholders})",
                    tuple(record.values()),
                )
                connection.commit()
            except sqlite3.IntegrityError as exc:
                raise ConflictError(f"could not create {table}: retained data conflicts") from exc
        return self._get(table, record["id"])

    def _get(self, table: str, record_id: str) -> dict[str, Any]:
        record_id = _uuid(record_id, "id")
        with self._connection() as connection:
            row = connection.execute(f"SELECT * FROM {table} WHERE id=?", (record_id,)).fetchone()
        if row is None:
            raise NotFoundError(f"{table} record was not found")
        return self._row(row)

    def _list(
        self, table: str, foreign_key: str | None = None, foreign_value: object | None = None
    ) -> list[dict[str, Any]]:
        with self._connection() as connection:
            if foreign_key:
                rows = connection.execute(
                    f"SELECT * FROM {table} WHERE {foreign_key}=? ORDER BY created_at,id",
                    (foreign_value,),
                ).fetchall()
            else:
                rows = connection.execute(
                    f"SELECT * FROM {table} ORDER BY created_at,id"
                ).fetchall()
        return [self._row(row) for row in rows]

    def _update(
        self, table: str, record_id: str, expected_version: int, values: dict[str, Any]
    ) -> dict[str, Any]:
        record_id = _uuid(record_id, "id")
        if not values:
            raise ValidationError("at least one supported field is required")
        if not isinstance(expected_version, int) or expected_version < 1:
            raise ValidationError("expected_version must be a positive integer")
        values = {**values, "updated_at": _now()}
        assignments = ",".join(f"{column}=?" for column in values)
        with self._connection() as connection:
            cursor = connection.execute(
                f"UPDATE {table} SET {assignments},version=version+1 WHERE id=? AND version=?",
                (*values.values(), record_id, expected_version),
            )
            connection.commit()
            if cursor.rowcount == 0:
                exists = connection.execute(
                    f"SELECT version FROM {table} WHERE id=?", (record_id,)
                ).fetchone()
                if exists is None:
                    raise NotFoundError(f"{table} record was not found")
                raise ConflictError(
                    f"version conflict: expected {expected_version}, current {exists['version']}"
                )
        return self._get(table, record_id)

    def _delete(self, table: str, record_id: str, expected_version: int) -> None:
        record_id = _uuid(record_id, "id")
        with self._connection() as connection:
            cursor = connection.execute(
                f"DELETE FROM {table} WHERE id=? AND version=?", (record_id, expected_version)
            )
            connection.commit()
            if cursor.rowcount == 0:
                exists = connection.execute(
                    f"SELECT version FROM {table} WHERE id=?", (record_id,)
                ).fetchone()
                if exists is None:
                    raise NotFoundError(f"{table} record was not found")
                raise ConflictError(
                    f"version conflict: expected {expected_version}, current {exists['version']}"
                )

    @staticmethod
    def _row(row: sqlite3.Row) -> dict[str, Any]:
        result = dict(row)
        for field in tuple(result):
            if field.endswith("_json"):
                result[field.removesuffix("_json")] = json.loads(result.pop(field))
        for field in ("favourite", "completed", "blank_means_observed_zero"):
            if field in result:
                result[field] = bool(result[field])
        return result


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6_371.0088
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    value = (
        math.sin(delta_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    )
    return radius * 2 * math.atan2(math.sqrt(value), math.sqrt(1 - value))
