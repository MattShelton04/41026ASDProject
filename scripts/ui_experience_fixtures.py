"""Isolated synthetic browser fixtures, not live service or model integration.

The canonical shared/F1 fixture responses retain their existing contracts. All
additional mutations are bounded to one in-memory browser session. Unknown APIs
fail loudly. The adjacent JSON is explicitly synthetic evidence, not product data.
"""

from __future__ import annotations

import copy
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote

from scripts.ui_fixtures import SCENARIOS, fixture_response

STAMP = "2026-08-10T09:00:00Z"
PROPERTY_ID = "a0000000-0000-0000-0000-000000000001"
MARKET_ID = "b2000000-0000-4000-8000-000000000001"
REVIEW_ID = "b4000000-0000-4000-8000-000000000001"
BUYER_ID = "b5000000-0000-4000-8000-000000000001"
COMPARISON_ID = "b3000000-0000-4000-8000-000000000001"
ADDRESS = "11 Example Street, Sydney NSW 2000"
FIXTURE_NOTE = (
    "Synthetic browser fixture; not a property assessment, valuation or live provider response."
)
MODES = (
    *SCENARIOS,
    "capabilities-error",
    "provider-unavailable",
    "ai-failed",
    "ai-review",
    "ai-poll-error",
    "ai-no-evidence",
)
_SEED = json.loads(Path(__file__).with_name("ui_experience_seed.json").read_text(encoding="utf-8"))


def problem(status: int, detail: str) -> tuple[int, dict[str, Any]]:
    return status, {
        "status": status,
        "code": "ui_fixture_problem",
        "title": "Deterministic fixture",
        "detail": detail,
        "request_id": "ui-experience-fixture",
    }


def page(items: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "items": copy.deepcopy(items),
        "count": len(items),
        "total": len(items),
        "page": {"number": 1, "size": 100, "total": len(items), "total_pages": 1},
    }


def _base_records() -> dict[str, list[dict[str, Any]]]:
    return copy.deepcopy(_SEED["records"])


@dataclass
class ExperienceFixtures:
    """A disposable session. No database, credentials, sockets or external calls."""

    mode: str = "populated"
    records: dict[str, list[dict[str, Any]]] = field(default_factory=_base_records)
    turns: dict[str, dict[str, Any]] = field(default_factory=dict)
    requests: list[dict[str, Any]] = field(default_factory=list)
    next_id: int = 2

    def __post_init__(self) -> None:
        if self.mode not in MODES:
            raise ValueError(f"Unknown scenario {self.mode}")
        if self.mode == "empty":
            self.records = {key: [] for key in self.records}
        elif self.mode == "long-content":
            for rows in self.records.values():
                for row in rows:
                    for name in ("name", "title"):
                        if name in row:
                            row[name] = ("Long but valid research title — " * 6)[:120]
                    for name in ("address_display", "property_label"):
                        if name in row:
                            row[name] = ("An unusually long synthetic street address " * 12)[:500]
                    if "notes" in row:
                        row["notes"] = (FIXTURE_NOTE + " ") * 20
        elif self.mode == "large":
            for key in ("market-cases", "site-reviews", "buyer-cases", "suburb-comparisons"):
                first = self.records[key][0]
                title_key = "name" if "name" in first else "title"
                self.records[key] = [
                    {
                        **copy.deepcopy(first),
                        "id": f"{first['id'][:-12]}{index:012}",
                        title_key: f"{first[title_key]} · {index}",
                    }
                    for index in range(1, 101)
                ]

    def _mutate(
        self,
        collection: str,
        method: str,
        identifier: str | None,
        body: dict[str, Any],
        parent_id: str | None = None,
    ) -> tuple[int, Any]:
        rows = self.records[collection]
        scoped = [
            row for row in rows if parent_id is None or row.get("buyer_case_id") == parent_id
        ]
        item = next((row for row in scoped if row["id"] == identifier), None)
        if method == "GET":
            if not identifier:
                return 200, page(scoped)
            if item:
                return 200, copy.deepcopy(item)
            return problem(404, "That fixture record does not exist.")
        if self.mode == "validation-error":
            return problem(422, "Review the submitted fields; nothing was saved.")
        if method == "POST" and not identifier:
            self.next_id += 1
            item = {
                **copy.deepcopy(body),
                "id": f"f0000000-0000-4000-8000-{self.next_id:012}",
                "version": 1,
                "created_at": STAMP,
                "updated_at": STAMP,
            }
            if parent_id is not None:
                item["buyer_case_id"] = parent_id
            if collection in {"market-cases", "properties"}:
                item["property_validation_state"] = "validated"
            if collection == "properties":
                item.setdefault("property_label", ADDRESS)
            if collection == "site-reviews":
                item.setdefault("address_display", ADDRESS)
                item.setdefault("checklist", [])
                item.setdefault("verification_questions", [])
            rows.append(item)
            return 201, copy.deepcopy(item)
        if not item:
            return problem(404, "That fixture record does not exist.")
        if method == "DELETE":
            rows.remove(item)
            if collection == "buyer-cases":
                for child in ("properties", "notes", "tasks"):
                    self.records[child] = [
                        row for row in self.records[child] if row["buyer_case_id"] != identifier
                    ]
            return 204, {}
        if method in {"PUT", "PATCH"}:
            if "version" in body and body["version"] != item.get("version"):
                return problem(409, "The version changed. Reload before trying again.")
            item.update(copy.deepcopy(body))
            item["version"] = item.get("version", 1) + 1
            return 200, copy.deepcopy(item)
        return problem(405, "Unsupported fixture mutation.")

    def response(
        self, method: str, path: str, query: str = "", body: dict[str, Any] | None = None
    ) -> tuple[int, Any]:
        """Resolve a known public route; unknown methods and paths cannot pass silently."""
        body = body or {}
        self.requests.append(
            {"method": method, "path": path, "query": query, "body": copy.deepcopy(body)}
        )
        if self.mode == "error" and path.startswith("/api/"):
            return problem(503, "This fixture dependency is temporarily unavailable.")
        if "/assistant/" in path:
            return self._assistant(method, path, body)
        if path.endswith("/health/ready") or path.startswith("/api/shared-health/"):
            return 200, {"status": "healthy", "service": "synthetic-ui-fixture"}
        if path.startswith("/api/market-intelligence/v1/"):
            route = path.removeprefix("/api/market-intelligence/v1/").strip("/").split("/")
            if route[0] == "market-cases":
                if len(route) == 3 and route[2] == "evidence":
                    item = self._record("market-cases", route[1])
                    if not item:
                        return problem(404, "Unknown market case.")
                    return 200, self._market_evidence(item)
                return self._mutate(
                    "market-cases", method, route[1] if len(route) > 1 else None, body
                )
        if path.startswith("/api/due-diligence/v1/"):
            return self._review(
                method, path.removeprefix("/api/due-diligence/v1/"), body
            )
        if path.startswith("/api/buyer-workspaces/v1/"):
            return self._buyer(
                method, path.removeprefix("/api/buyer-workspaces/v1/"), body
            )
        if path.startswith("/api/suburb-analytics/v1/"):
            return self._suburb(
                method, path.removeprefix("/api/suburb-analytics/v1/"), parse_qs(query), body
            )
        if path.startswith(("/api/data-platform/", "/api/ai-mode/", "/api/v1/")):
            scenario = self.mode if self.mode in SCENARIOS else "populated"
            result = fixture_response(method, path, query, scenario)
            return result.status, result.body
        return problem(404, f"No deterministic fixture for {method} {path}.")

    def _record(self, collection: str, identifier: str) -> dict[str, Any] | None:
        return next((row for row in self.records[collection] if row["id"] == identifier), None)

    def _review(self, method: str, path: str, body: dict[str, Any]) -> tuple[int, Any]:
        route = path.strip("/").split("/")
        if route[:2] == ["properties", "search"]:
            items = [{"property_ref": PROPERTY_ID, "address_display": ADDRESS}]
            return 200, {"available": True, "items": [] if self.mode == "empty" else items}
        if route[0] != "site-reviews":
            return problem(404, "Unknown due-diligence fixture route.")
        if len(route) <= 2:
            return self._mutate("site-reviews", method, route[1] if len(route) > 1 else None, body)
        item = self._record("site-reviews", route[1])
        if not item:
            return problem(404, "Unknown site review.")
        if len(route) == 3 and route[2] == "evidence":
            return 200, self._review_evidence(item)
        if len(route) == 3 and route[2] == "map":
            return 200, {
                "available": False,
                "reason": "Synthetic fixture has no verified map coordinate.",
            }
        return problem(404, "Unknown site-review fixture route.")

    def _buyer(self, method: str, path: str, body: dict[str, Any]) -> tuple[int, Any]:
        route = path.strip("/").split("/")
        if route[0] != "buyer-cases":
            return problem(404, "Unknown buyer fixture route.")
        if len(route) <= 2:
            return self._mutate("buyer-cases", method, route[1] if len(route) > 1 else None, body)
        if not self._record("buyer-cases", route[1]):
            return problem(404, "Unknown buyer case.")
        if route[2] in {"properties", "notes", "tasks"}:
            return self._mutate(
                route[2], method, route[3] if len(route) > 3 else None, body, parent_id=route[1]
            )
        if route[2] == "evidence":
            return 200, self._buyer_evidence()
        if route[2] == "case-summary-runs":
            result = {
                "id": "f5000000-0000-4000-8000-000000000001",
                "status": "succeeded",
                "summary": FIXTURE_NOTE,
                "phases": [{"name": "evidence", "status": "succeeded"}],
                "suggested_next_actions": [
                    "Verify the missing coverage before relying on this case."
                ],
                "evidence_used": [{"label": "Property data", "status": "partial"}],
                "evidence_references": ["fixture:buyer-case"],
                "limitations": [FIXTURE_NOTE],
            }
            return (202 if method == "POST" else 200), result
        return problem(404, "Unknown buyer-case fixture route.")

    def _market_evidence(self, item: dict[str, Any]) -> dict[str, Any]:
        result = copy.deepcopy(_SEED["market_evidence"])
        result["market_case"] = copy.deepcopy(item)
        for key in ("date_from", "date_to"):
            result["summary"][key] = item[key]
        result["summary"]["minimum_match_tier"] = item["filters"]["minimum_match_tier"]
        if self.mode == "partial":
            result["summary"]["limitations"].append("One optional source is unavailable.")
        return result

    def _review_evidence(self, item: dict[str, Any]) -> dict[str, Any]:
        result = copy.deepcopy(_SEED["review_evidence"])
        result["site_review"] = copy.deepcopy(item)
        if self.mode == "partial":
            result["buildings"][0]["evidence_state"] = "unavailable"
        return result

    def _buyer_evidence(self) -> dict[str, Any]:
        return copy.deepcopy(_SEED["buyer_evidence"])

    def _suburb(
        self, method: str, route: str, params: dict[str, list[str]], body: dict[str, Any]
    ) -> tuple[int, Any]:
        parts = route.strip("/").split("/")
        if parts[0] == "suburb-comparisons":
            return self._mutate(parts[0], method, parts[1] if len(parts) > 1 else None, body)
        if route == "suburbs":
            query = params.get("q", [""])[0].casefold()
            lga = params.get("lga", [""])[0]
            rows = [
                item
                for item in self.records["suburbs"]
                if (not query or query in (item["locality"] + item["postcode"]).casefold())
                and (not lga or item["lga"] == lga)
            ]
            return 200, page(rows)
        if parts[:2] == ["suburbs", "NSW"] and len(parts) >= 3:
            return self._suburb_detail(parts, params)
        if route == "crime/compare":
            return 200, self._crime_comparison(params)
        if route == "published/sources":
            return 200, (
                {"items": []} if self.mode == "empty" else copy.deepcopy(_SEED["published_sources"])
            )
        if route == "published/suburbs":
            names = [row["locality"] for row in self.records["suburbs"]]
            query = params.get("q", [""])[0].casefold()
            return 200, {
                "items": [name for name in names if query in name.casefold()],
                "next_offset": None,
            }
        if route == "published/context":
            return 200, copy.deepcopy(_SEED["published_context"])
        if re.fullmatch(r"data-imports/[^/]+/(sync|retry)", route):
            return 202, {"consumer_operation_id": "fixture-import", "status": "queued"}
        return problem(404, f"No suburb fixture for {route}")

    def _suburb_detail(
        self, parts: list[str], params: dict[str, list[str]]
    ) -> tuple[int, Any]:
        item = next(
            (
                row
                for row in self.records["suburbs"]
                if row["locality"].casefold() == unquote(parts[2]).casefold()
            ),
            None,
        )
        if item is None:
            return problem(404, "Unknown fixture suburb.")
        if len(parts) == 3:
            return 200, {"suburb": copy.deepcopy(item)}
        if parts[3] == "places":
            return 200, page(
                [
                    {
                        "id": f"fixture-place-{index}",
                        "name": f"Synthetic {kind}",
                        "place_type": kind,
                        "latitude": item["latitude"] + index * 0.001,
                        "longitude": item["longitude"] + index * 0.001,
                    }
                    for index, kind in enumerate(("school", "transport", "park"), 1)
                ]
            )
        if parts[3] == "area-series":
            metric = params.get("metric", [""])[0]
            density = metric == "population_density"
            return 200, page(
                [
                    {
                        "value": 2400 if density else 4,
                        "unit": "people/km²" if density else "observations",
                        "metric": metric,
                        "source_release": "synthetic-browser-fixture",
                    }
                ]
            )
        return problem(404, "Unknown suburb detail fixture.")

    def _crime_comparison(self, params: dict[str, list[str]]) -> dict[str, Any]:
        localities = params.get("localities", ["Parramatta,Newtown"])[0].split(",")
        measure = params.get("measure", ["count"])[0]
        series = []
        for number, name in enumerate(localities):
            observations = []
            values = [10, 12, 11, 15, 13, 9] if number == 0 else [6, 4, 0, 7, 8, 6]
            for month, value in enumerate(values, 1):
                missing = self.mode == "partial" and month == 3
                observations.append(
                    {
                        "month": f"2026-{month:02}",
                        "value": None if missing else value,
                        "unit": "per 100,000" if measure == "rate" else "count",
                        "zero_missing_state": (
                            "missing" if missing else "recorded_zero" if value == 0 else "observed"
                        ),
                    }
                )
            series.append({"locality": name, "items": observations})
        return {
            "series": series,
            "measure": measure,
            "offence": params.get("offence", ["all_recorded"])[0],
            "limitations": [FIXTURE_NOTE, "Missing values are never zero."],
        }

    def _assistant(self, method: str, path: str, body: dict[str, Any]) -> tuple[int, Any]:
        if path.endswith("/capabilities") and method == "GET":
            if self.mode == "capabilities-error":
                return problem(503, "Capability guide unavailable in this scenario.")
            return 200, {
                "revision": "synthetic-ui-v1",
                "suggested_questions": [
                    "What can PropertyScope help me research?",
                    "How can I check the source coverage?",
                ],
                "tools": [],
                "fixture": True,
            }
        tail = path.split("/assistant/", 1)[1].split("/")
        if tail == ["turns"] and method == "POST":
            if self.mode == "provider-unavailable":
                return problem(503, "The provider is unavailable. No run was created.")
            if self.mode == "validation-error":
                return problem(422, "The supplied context is not valid for this scope.")
            identifier = f"f1000000-0000-4000-8000-{len(self.turns) + 1:012}"
            self.turns[identifier] = {
                "id": identifier,
                "polls": 0,
                "status": "queued",
                "message": body.get("message", "Bounded evidence review"),
                "cancelled": False,
            }
            return 202, self._turn(self.turns[identifier])["run"]
        identifier = tail[1] if len(tail) > 1 else ""
        turn = self.turns.get(identifier)
        if turn is None:
            return problem(404, "Unknown assistant fixture turn.")
        if len(tail) == 3 and tail[2] == "cancel" and method == "POST":
            turn["cancelled"] = True
            turn["status"] = "cancelled"
            return 200, self._turn(turn)
        if len(tail) == 3 and tail[2] == "events" and method == "GET":
            return 200, {"items": [], "next_cursor": 0}
        if method != "GET" or len(tail) != 2:
            return problem(405, "Unsupported assistant fixture method.")
        turn["polls"] += 1
        if self.mode == "ai-poll-error" and turn["polls"] == 2:
            return problem(503, "Temporary deterministic polling outage.")
        if not turn["cancelled"]:
            if turn["polls"] <= 2:
                turn["status"] = "planning"
            elif turn["polls"] == 3:
                turn["status"] = "acting"
            else:
                turn["status"] = {
                    "ai-failed": "failed", "ai-review": "review_required"
                }.get(self.mode, "succeeded")
        return 200, self._turn(turn)

    def _turn(self, turn: dict[str, Any]) -> dict[str, Any]:
        status = turn["status"]
        final = None
        if status == "succeeded":
            final = {
                "summary": (
                    "No matching evidence was returned."
                    if self.mode == "ai-no-evidence"
                    else (
                        "The fixture record has source-attributed evidence and incomplete coverage."
                    )
                ),
                "findings": ["This is a deterministic browser fixture, not a live model answer."],
                "limitations": [
                    "Accepted data and complete evidence are different claims.", FIXTURE_NOTE
                ],
                "recommended_next_step": "Verify the source record's date and limitations.",
                "verification_questions": [
                    "Which evidence is still missing?", "What requires professional verification?"
                ],
            }
        steps = []
        if turn["polls"] >= 3 and self.mode != "ai-no-evidence":
            steps = [
                {
                    "id": "fixture-step",
                    "phase": "act",
                    "status": "running" if status == "acting" else "succeeded",
                    "input": {"tool_call": {"tool_name": "property.inspect.v1"}},
                    "output": None if status == "acting" else {
                        "tool_result": {
                            "outcome": "succeeded",
                            "summary": "Recorded synthetic source result",
                            "evidence_references": ["fixture:property:001"],
                        }
                    },
                }
            ]
        return {
            "run": {
                "id": turn["id"],
                "status": status,
                "created_at": STAMP,
                "updated_at": STAMP,
                "final_result": final,
                "error": (
                    {"message": "The provider stopped. Recorded activity is retained."}
                    if status == "failed" else None
                ),
            },
            "steps": steps,
        }
