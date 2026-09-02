"""SQLite persistence owned exclusively by the Student 3 database service."""

from __future__ import annotations

import json
import math
import sqlite3
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

SCHEMA = """
CREATE TABLE IF NOT EXISTS suburb_info (
  id TEXT PRIMARY KEY, state TEXT NOT NULL, locality TEXT NOT NULL, postcode TEXT NOT NULL,
  lga TEXT NOT NULL, latitude REAL NOT NULL, longitude REAL NOT NULL,
  source_release TEXT NOT NULL, coverage_status TEXT NOT NULL,
  UNIQUE(state, locality)
);
CREATE TABLE IF NOT EXISTS suburb_indicators (
  id TEXT PRIMARY KEY, suburb_id TEXT NOT NULL REFERENCES suburb_info(id),
  metric_key TEXT NOT NULL, period TEXT NOT NULL, value REAL, unit TEXT NOT NULL,
  zero_missing_state TEXT NOT NULL, measure_source TEXT NOT NULL,
  source_release TEXT NOT NULL, UNIQUE(suburb_id, metric_key, period)
);
CREATE TABLE IF NOT EXISTS suburb_amenity (
  id TEXT PRIMARY KEY, suburb_id TEXT NOT NULL REFERENCES suburb_info(id),
  place_type TEXT NOT NULL, name TEXT NOT NULL, latitude REAL NOT NULL, longitude REAL NOT NULL,
  coverage_status TEXT NOT NULL, source_release TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS suburb_overview (
  id TEXT PRIMARY KEY, suburb_id TEXT NOT NULL UNIQUE REFERENCES suburb_info(id),
  population INTEGER NOT NULL, area_km2 REAL NOT NULL, description TEXT NOT NULL,
  observed_at TEXT NOT NULL, source_release TEXT NOT NULL, coverage_status TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS user_suburbs (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, localities_json TEXT NOT NULL,
  from_month TEXT NOT NULL, to_month TEXT NOT NULL, measure TEXT NOT NULL,
  selected_indicators_json TEXT NOT NULL, priorities_json TEXT NOT NULL,
  notes TEXT NOT NULL, status TEXT NOT NULL, agent_run_id TEXT,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL, version INTEGER NOT NULL
);
"""

SUBURBS = (
    ("surry-hills", "Surry Hills", "2010", "City of Sydney", -33.8841, 151.2113, 16412, 1.2),
    ("parramatta", "Parramatta", "2150", "City of Parramatta", -33.8150, 151.0011, 30211, 5.3),
    ("newtown", "Newtown", "2042", "City of Sydney", -33.8978, 151.1797, 15718, 1.6),
    ("manly", "Manly", "2095", "Northern Beaches", -33.7972, 151.2887, 16036, 5.6),
    ("chatswood", "Chatswood", "2067", "Willoughby", -33.7969, 151.1838, 25742, 2.9),
    ("bankstown", "Bankstown", "2200", "Canterbury-Bankstown", -33.9173, 151.0349, 34750, 7.7),
    ("burwood", "Burwood", "2134", "Burwood", -33.8774, 151.1037, 19181, 2.5),
    ("hurstville", "Hurstville", "2220", "Georges River", -33.9674, 151.1011, 31280, 4.2),
    ("sutherland", "Sutherland", "2232", "Sutherland Shire", -34.0315, 151.0557, 11011, 3.6),
    ("penrith", "Penrith", "2750", "Penrith", -33.7507, 150.6877, 15700, 12.3),
)
MONTHS = ("2026-01", "2026-02", "2026-03", "2026-04", "2026-05", "2026-06")


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


class Repository:
    """Small deterministic repository with explicit bounded query methods."""

    def __init__(self, path: str | Path) -> None:
        self.path = str(path)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialise(self) -> None:
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            connection.executescript(SCHEMA)
            if connection.execute("SELECT COUNT(*) FROM suburb_info").fetchone()[0] == 0:
                self._seed(connection)
            self._ensure_fixture_revision(connection)

    def _seed(self, connection: sqlite3.Connection) -> None:
        for index, (key, locality, postcode, lga, lat, lng, population, area) in enumerate(SUBURBS):
            connection.execute(
                "INSERT INTO suburb_info VALUES "
                "(?, 'NSW', ?, ?, ?, ?, ?, 'demo-2026.1', 'partial')",
                (key, locality, postcode, lga, lat, lng),
            )
            connection.execute(
                "INSERT INTO suburb_overview VALUES "
                "(?, ?, ?, ?, ?, '2026-08-01T00:00:00Z', 'demo-2026.1', 'partial')",
                (
                    f"overview-{key}",
                    key,
                    population,
                    area,
                    f"A bounded demonstration profile for {locality}. Verify current figures "
                    "with the cited publisher before making decisions.",
                ),
            )
            for month_index, month in enumerate(MONTHS):
                count = (index * 3 + month_index * 2 + 7) % 29
                missing = key == "manly" and month == "2026-03"
                value = None if missing else count
                state = "missing" if missing else "recorded_zero" if count == 0 else "observed"
                connection.execute(
                    "INSERT INTO suburb_indicators VALUES "
                    "(?, ?, 'recorded_offences', ?, ?, 'count', ?, 'fixture_count', "
                    "'demo-2026.1')",
                    (f"crime-{key}-{month}", key, month, value, state),
                )
                connection.execute(
                    "INSERT INTO suburb_indicators VALUES "
                    "(?, ?, 'offence_rate', ?, ?, 'per 100,000', ?, "
                    "'calculated_fixture_rate', 'demo-2026.1')",
                    (
                        f"rate-{key}-{month}",
                        key,
                        month,
                        None if missing else round(count / population * 100000, 1),
                        state,
                    ),
                )
            for place_index, place_type in enumerate(("school", "transport", "park")):
                connection.execute(
                    "INSERT INTO suburb_amenity VALUES "
                    "(?, ?, ?, ?, ?, ?, 'observed', 'demo-2026.1')",
                    (
                        f"amenity-{key}-{place_index}",
                        key,
                        place_type,
                        f"{locality} {place_type.title()} {place_index + 1}",
                        lat + 0.003 * (place_index - 1),
                        lng + 0.003 * (1 - place_index),
                    ),
                )
        for index, (_, locality, *_rest) in enumerate(SUBURBS):
            now = _now()
            connection.execute(
                "INSERT INTO user_suburbs VALUES "
                "(?, ?, ?, '2026-01', '2026-06', 'rate', ?, ?, ?, 'saved', "
                "NULL, ?, ?, 1)",
                (
                    f"comparison-{index + 1}",
                    f"{locality} research",
                    json.dumps([locality]),
                    json.dumps(["offence_rate"]),
                    json.dumps(["transport", "parks"]),
                    "Seeded comparison for demonstration.",
                    now,
                    now,
                ),
            )

    def _ensure_fixture_revision(self, connection: sqlite3.Connection) -> None:
        """Add deterministic factual context metrics to old and new scaffold databases."""
        for key, _locality, _postcode, _lga, _lat, _lng, population, area in SUBURBS:
            metrics = (
                ("population_density", round(population / area, 1), "people per km²"),
                ("amenity_observations", 3.0, "observations"),
                ("school_observations", 1.0, "observations"),
                ("transport_observations", 1.0, "observations"),
            )
            for metric, value, unit in metrics:
                connection.execute(
                    "INSERT OR IGNORE INTO suburb_indicators VALUES "
                    "(?, ?, ?, '2026-06', ?, ?, 'observed', 'derived_fixture_context', "
                    "'demo-2026.1')",
                    (f"context-{key}-{metric}", key, metric, value, unit),
                )
            suburb_index = next(index for index, item in enumerate(SUBURBS) if item[0] == key)
            for month_index, month in enumerate(MONTHS):
                base_count = (suburb_index * 3 + month_index * 2 + 7) % 29
                missing = key == "manly" and month == "2026-03"
                categories = {
                    "property": round(base_count * 0.55),
                    "person": base_count - round(base_count * 0.55),
                }
                for category, count in categories.items():
                    state = "missing" if missing else "recorded_zero" if count == 0 else "observed"
                    connection.execute(
                        "INSERT OR IGNORE INTO suburb_indicators VALUES "
                        "(?, ?, ?, ?, ?, 'count', ?, 'derived_fixture_category', "
                        "'demo-2026.1')",
                        (
                            f"crime-{category}-{key}-{month}",
                            key,
                            f"crime_{category}_count",
                            month,
                            None if missing else count,
                            state,
                        ),
                    )
                    connection.execute(
                        "INSERT OR IGNORE INTO suburb_indicators VALUES "
                        "(?, ?, ?, ?, ?, 'per 100,000', ?, 'calculated_fixture_rate', "
                        "'demo-2026.1')",
                        (
                            f"rate-{category}-{key}-{month}",
                            key,
                            f"crime_{category}_rate",
                            month,
                            None if missing else round(count / population * 100000, 1),
                            state,
                        ),
                    )
        connection.execute(
            "UPDATE suburb_indicators SET value=NULL, zero_missing_state='missing' "
            "WHERE id IN ('crime-manly-2026-03', 'rate-manly-2026-03')"
        )

    @staticmethod
    def _rows(rows: Iterable[sqlite3.Row]) -> list[dict[str, Any]]:
        return [dict(row) for row in rows]

    def list_suburbs(
        self,
        query: str = "",
        lga: str = "",
        amenity: str = "",
        sort: str = "locality",
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[dict[str, Any]], int]:
        clauses, values = [], []
        if query:
            clauses.append("(lower(locality) LIKE ? OR postcode LIKE ?)")
            values.extend([f"%{query.lower()}%", f"%{query}%"])
        if lga:
            clauses.append("lower(lga) = ?")
            values.append(lga.lower())
        if amenity:
            clauses.append(
                "EXISTS (SELECT 1 FROM suburb_amenity a WHERE a.suburb_id=suburb_info.id "
                "AND a.place_type=?)"
            )
            values.append(amenity)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        order = (
            "postcode, locality"
            if sort == "postcode"
            else "lga, locality"
            if sort == "lga"
            else "locality"
        )
        with self.connect() as connection:
            total = connection.execute(
                f"SELECT COUNT(*) FROM suburb_info{where}", values
            ).fetchone()[0]
            items = self._rows(
                connection.execute(
                    f"SELECT * FROM suburb_info{where} ORDER BY {order} LIMIT ? OFFSET ?",
                    (*values, min(max(limit, 1), 100), max(offset, 0)),
                )
            )
        return items, total

    def suburb(self, state: str, locality: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT i.*, o.population, o.area_km2, o.description, o.observed_at "
                "FROM suburb_info i JOIN suburb_overview o ON o.suburb_id=i.id "
                "WHERE lower(i.state)=? AND lower(i.locality)=?",
                (state.lower(), locality.lower()),
            ).fetchone()
            return dict(row) if row else None

    def places(
        self, state: str, locality: str, place_type: str = "", limit: int = 50
    ) -> list[dict[str, Any]]:
        suburb = self.suburb(state, locality)
        if suburb is None:
            return []
        sql, values = "SELECT * FROM suburb_amenity WHERE suburb_id=?", [suburb["id"]]
        if place_type:
            sql += " AND place_type=?"
            values.append(place_type)
        with self.connect() as connection:
            return self._rows(
                connection.execute(
                    sql + " ORDER BY place_type, name LIMIT ?", (*values, min(max(limit, 1), 100))
                )
            )

    def series(
        self,
        state: str,
        locality: str,
        measure: str,
        start: str,
        end: str,
        offence: str = "all_recorded",
    ) -> list[dict[str, Any]]:
        suburb = self.suburb(state, locality)
        if suburb is None:
            return []
        metric = (
            "recorded_offences"
            if offence == "all_recorded" and measure == "count"
            else "offence_rate"
            if offence == "all_recorded"
            else f"crime_{offence}_{measure}"
        )
        with self.connect() as connection:
            return self._rows(
                connection.execute(
                    "SELECT period AS month, value, unit, zero_missing_state, measure_source, "
                    "source_release FROM suburb_indicators WHERE suburb_id=? AND metric_key=? "
                    "AND period BETWEEN ? AND ? ORDER BY period",
                    (suburb["id"], metric, start, end),
                )
            )

    def area_series(self, state: str, locality: str, metric: str) -> list[dict[str, Any]]:
        suburb = self.suburb(state, locality)
        if suburb is None:
            return []
        with self.connect() as connection:
            return self._rows(
                connection.execute(
                    "SELECT period, value, unit, zero_missing_state, measure_source, "
                    "source_release FROM suburb_indicators WHERE suburb_id=? AND metric_key=? "
                    "ORDER BY period LIMIT 120",
                    (suburb["id"], metric),
                )
            )

    def nearby_places(
        self, latitude: float, longitude: float, radius_m: int, limit: int = 50
    ) -> list[dict[str, Any]]:
        with self.connect() as connection:
            places = self._rows(connection.execute("SELECT * FROM suburb_amenity LIMIT 500"))
        projected = []
        for place in places:
            lat1, lat2 = math.radians(latitude), math.radians(float(place["latitude"]))
            delta_lat = math.radians(float(place["latitude"]) - latitude)
            delta_lng = math.radians(float(place["longitude"]) - longitude)
            value = (
                math.sin(delta_lat / 2) ** 2
                + math.cos(lat1) * math.cos(lat2) * math.sin(delta_lng / 2) ** 2
            )
            distance = 6_371_000 * 2 * math.atan2(math.sqrt(value), math.sqrt(1 - value))
            if distance <= radius_m:
                projected.append(place | {"distance_m": round(distance)})
        return sorted(projected, key=lambda item: (item["distance_m"], item["name"]))[:limit]

    def comparisons(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = self._rows(
                connection.execute("SELECT * FROM user_suburbs ORDER BY updated_at DESC LIMIT 50")
            )
        return [self._decode_comparison(row) for row in rows]

    def comparison(self, comparison_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM user_suburbs WHERE id=?", (comparison_id,)
            ).fetchone()
        return self._decode_comparison(dict(row)) if row else None

    @staticmethod
    def _decode_comparison(row: dict[str, Any]) -> dict[str, Any]:
        for field in ("localities_json", "selected_indicators_json", "priorities_json"):
            row[field.removesuffix("_json")] = json.loads(row.pop(field))
        return row

    def create_comparison(self, payload: dict[str, Any]) -> dict[str, Any]:
        comparison_id, now = str(uuid4()), _now()
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO user_suburbs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, 1)",
                (
                    comparison_id,
                    payload["name"],
                    json.dumps(payload["localities"]),
                    payload["from_month"],
                    payload["to_month"],
                    payload["measure"],
                    json.dumps(payload.get("selected_indicators", [])),
                    json.dumps(payload.get("priorities", [])),
                    payload.get("notes", ""),
                    payload.get("status", "saved"),
                    now,
                    now,
                ),
            )
        return self.comparison(comparison_id) or {}

    def update_comparison(
        self, comparison_id: str, payload: dict[str, Any]
    ) -> dict[str, Any] | None:
        current = self.comparison(comparison_id)
        if current is None:
            return None
        version = int(payload.get("version", 0))
        if version != current["version"]:
            raise ValueError("version_conflict")
        merged = current | payload
        with self.connect() as connection:
            connection.execute(
                "UPDATE user_suburbs SET name=?, localities_json=?, from_month=?, to_month=?, "
                "measure=?, selected_indicators_json=?, priorities_json=?, notes=?, status=?, "
                "updated_at=?, version=version+1 WHERE id=? AND version=?",
                (
                    merged["name"],
                    json.dumps(merged["localities"]),
                    merged["from_month"],
                    merged["to_month"],
                    merged["measure"],
                    json.dumps(merged.get("selected_indicators", [])),
                    json.dumps(merged.get("priorities", [])),
                    merged.get("notes", ""),
                    merged.get("status", "saved"),
                    _now(),
                    comparison_id,
                    version,
                ),
            )
        return self.comparison(comparison_id)

    def delete_comparison(self, comparison_id: str) -> bool:
        with self.connect() as connection:
            result = connection.execute("DELETE FROM user_suburbs WHERE id=?", (comparison_id,))
        return result.rowcount > 0

    def table_counts(self) -> dict[str, int]:
        tables = (
            "suburb_info",
            "suburb_indicators",
            "suburb_amenity",
            "suburb_overview",
            "user_suburbs",
        )
        with self.connect() as connection:
            return {
                table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for table in tables
            }
