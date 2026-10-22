"""Read-only Feature 3 tools used by the Release 2 comparison review workflow."""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from propertyscope_suburb_analytics.app import create_app
from propertyscope_suburb_analytics.clients import ServiceError

BASE = "/api/suburb-analytics/v1/tools"
COMPARISON_ID = "comparison-1"
ROOT = Path(__file__).resolve().parents[2]


class ReviewData:
    def __init__(
        self,
        *,
        measure: str = "count",
        missing_population: bool = False,
        source_release: str = "crime-release-1",
    ) -> None:
        self.calls: list[tuple[str, str, dict[str, Any] | None]] = []
        self.measure = measure
        self.missing_population = missing_population
        self.source_release = source_release

    def request(
        self, method: str, path: str, payload: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        self.calls.append((method, path, payload))
        if path == f"/internal/v1/suburb-comparisons/{COMPARISON_ID}":
            return {
                "comparison": {
                    "id": COMPARISON_ID,
                    "version": 4,
                    "name": "Parramatta and Newtown",
                    "status": "saved",
                    "localities": ["PARRAMATTA", "NEWTOWN"],
                    "from_month": "2026-01",
                    "to_month": "2026-02",
                    "measure": self.measure,
                    "selected_indicators": ["recorded_offences"],
                    "priorities": ["transport"],
                    "notes": "Seeded published-locality comparison for demonstration.",
                }
            }
        if path.startswith("/internal/v1/published/context?locality="):
            locality = path.rsplit("=", 1)[-1]
            population = (
                []
                if self.missing_population and locality == "NEWTOWN"
                else [{"sal_name": locality, "usual_resident_population": 20_000}]
            )
            observations = (
                [{"month": "2026-01", "count": 0}]
                if locality == "PARRAMATTA"
                else [
                    {"month": "2026-01", "count": 3},
                    {"month": "2026-02", "count": 5},
                ]
            )
            return {
                "locality": locality,
                "population": population,
                "schools": [],
                "crime": [
                    {
                        "source_category_key": "property",
                        "observed_months": ["2026-01", "2026-02"],
                        "observations": observations,
                    }
                ],
                "sources": [{"dataset_id": "bocsar-crime", "release_id": self.source_release}],
            }
        raise AssertionError((method, path, payload))


class MissingComparison(ReviewData):
    def request(
        self, method: str, path: str, payload: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        if path.startswith("/internal/v1/suburb-comparisons/"):
            raise ServiceError(404, {"code": "comparison_not_found"})
        return super().request(method, path, payload)


class UnusedService:
    base_url = "http://unused"

    def request(
        self, method: str, path: str, payload: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        raise AssertionError((method, path, payload))


def call_tool(
    data: ReviewData,
    tool: str,
    body: dict[str, Any],
) -> tuple[int, dict[str, Any]]:
    encoded = json.dumps(body).encode()
    environ = {
        "REQUEST_METHOD": "POST",
        "PATH_INFO": f"{BASE}/{tool}",
        "QUERY_STRING": "",
        "CONTENT_LENGTH": str(len(encoded)),
        "wsgi.input": io.BytesIO(encoded),
    }
    statuses: list[str] = []
    result = b"".join(
        create_app(data, UnusedService(), UnusedService())(
            environ, lambda status, _headers: statuses.append(status)
        )
    )
    return int(statuses[0].split()[0]), json.loads(result)


def test_comparison_inspection_is_bounded_and_read_only() -> None:
    data = ReviewData()
    status, payload = call_tool(
        data, "suburb.comparison.inspect.v1", {"suburb_comparison_id": COMPARISON_ID}
    )

    assert status == 200
    assert payload["comparison"] == {
        "id": COMPARISON_ID,
        "version": 4,
        "name": "Parramatta and Newtown",
        "status": "saved",
        "localities": ["PARRAMATTA", "NEWTOWN"],
        "from_month": "2026-01",
        "to_month": "2026-02",
        "measure": "count",
        "selected_indicators": ["recorded_offences"],
        "priorities": ["transport"],
        "notes": "Seeded published-locality comparison for demonstration.",
    }
    assert payload["comparison_origin"] == "seeded_demonstration"
    assert any("does not change" in item for item in payload["limitations"])
    assert data.calls == [("GET", f"/internal/v1/suburb-comparisons/{COMPARISON_ID}", None)]


def test_saved_comparison_evidence_preserves_recorded_zero_and_missing() -> None:
    data = ReviewData()
    status, payload = call_tool(
        data,
        "crime.saved-comparison-evidence.v1",
        {"suburb_comparison_id": COMPARISON_ID},
    )

    assert status == 200
    assert payload["comparison_id"] == COMPARISON_ID
    assert payload["measure"] == "count"
    assert payload["unit"] == "count"
    assert payload["offence"] == "all_recorded"
    assert payload["source_releases"] == ["crime-release-1"]
    assert payload["evidence_mode"] == "published_release"
    assert payload["coverage"] == "partial"
    parramatta = payload["series"][0]["items"]
    assert parramatta[0]["value"] == 0
    assert parramatta[0]["zero_missing_state"] == "recorded_zero"
    assert parramatta[1]["value"] is None
    assert parramatta[1]["zero_missing_state"] == "missing"
    assert payload["validation"] == {
        "period_consistent": True,
        "measure_consistent": True,
        "missing_values_preserved": True,
        "rate_denominator_valid": True,
    }
    assert all(method == "GET" and body is None for method, _path, body in data.calls)
    assert data.calls[0][1].endswith(COMPARISON_ID)


def test_rate_review_reports_an_unavailable_denominator() -> None:
    status, payload = call_tool(
        ReviewData(measure="rate", missing_population=True),
        "crime.saved-comparison-evidence.v1",
        {"suburb_comparison_id": COMPARISON_ID},
    )

    assert status == 200
    assert payload["unit"] == "per 100,000"
    assert payload["validation"]["rate_denominator_valid"] is False
    assert any("not current denominators" in item for item in payload["limitations"])


def test_saved_comparison_evidence_discloses_a_synthetic_release() -> None:
    status, payload = call_tool(
        ReviewData(source_release="synthetic-offline-test"),
        "crime.saved-comparison-evidence.v1",
        {"suburb_comparison_id": COMPARISON_ID},
    )

    assert status == 200
    assert payload["evidence_mode"] == "seeded_demonstration"


@pytest.mark.parametrize("comparison_id", ["", " contains spaces", "../comparison-1", "x" * 101, 7])
def test_review_tools_reject_unsafe_comparison_identifiers(comparison_id: object) -> None:
    data = ReviewData()
    status, payload = call_tool(
        data,
        "suburb.comparison.inspect.v1",
        {"suburb_comparison_id": comparison_id},
    )

    assert status == 422
    assert payload["code"] == "invalid_request"
    assert data.calls == []


def test_missing_comparison_preserves_the_dependency_not_found_code() -> None:
    status, payload = call_tool(
        MissingComparison(),
        "suburb.comparison.inspect.v1",
        {"suburb_comparison_id": COMPARISON_ID},
    )

    assert status == 404
    assert payload["code"] == "comparison_not_found"


def test_review_tool_catalogue_entries_are_read_only_and_approval_free() -> None:
    catalogue = yaml.safe_load((ROOT / "student-3/tool-catalog.yaml").read_text("utf-8"))
    definitions = {item["definition"]["name"]: item["definition"] for item in catalogue["tools"]}

    for name in (
        "suburb.comparison.inspect.v1",
        "crime.saved-comparison-evidence.v1",
    ):
        assert definitions[name]["feature_key"] == "student-3-suburb-analytics"
        assert definitions[name]["side_effect"] == "read_only"
        assert definitions[name]["requires_approval"] is False
