from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).parents[3]
sys.path.insert(0, str(ROOT / "poc" / "feature-6" / "backend" / "src"))
sys.path.insert(0, str(ROOT / "poc" / "feature-6" / "database" / "src"))

from propertyscope_integration_poc import Settings, StoreHttpClient  # noqa: E402
from propertyscope_integration_store import create_app  # noqa: E402
from propertyscope_integration_store.errors import ConflictError, ValidationError  # noqa: E402
from propertyscope_integration_store.repository import IntegrationStore  # noqa: E402

PROPERTY = "a0000000-0000-0000-0000-000000000001"
SALES_RELEASE = "60000000-0000-0000-0000-000000000002"
CRIME_RELEASE = "60000000-0000-0000-0000-000000000003"
SCHOOL_RELEASE = "60000000-0000-0000-0000-000000000004"


@pytest.fixture
def store(tmp_path: Path) -> IntegrationStore:
    result = IntegrationStore(tmp_path / "poc.sqlite3")
    result.initialise()
    return result


def sale(key: str, revision: int, price: int | None, date: str = "2025-01-01") -> dict[str, Any]:
    return {
        "source_business_key": key,
        "source_revision": revision,
        "property_ref": PROPERTY,
        "contract_date": date,
        "settlement_date": "2025-02-01",
        "price_aud": price,
        "locality": "SYDNEY",
        "postcode": "2000",
        "match_tier": "A",
        "provenance": {"release_id": SALES_RELEASE},
    }


def import_release(
    store: IntegrationStore,
    *,
    release_id: str,
    dataset: str,
    schema: str,
    records: list[dict[str, Any]],
    key: str,
) -> dict[str, Any]:
    target_feature = "feature-2" if dataset == "nsw-psi-sales" else "feature-3"
    request = {
        "release_id": release_id,
        "dataset_id": dataset,
        "target_feature": target_feature,
        "schema_version": schema,
        "content_sha256": "a" * 64,
        "record_count": len(records),
        "manifest": {"release_id": release_id},
        "artifact_path": f"/api/data-platform/v1/dataset-releases/{release_id}/artifact",
        "idempotency_key": key,
    }
    return store.import_release(
        target_feature=target_feature,
        idempotency_key=key,
        provider_release_id=release_id,
        dataset_id=dataset,
        schema_version=schema,
        content_sha256="a" * 64,
        record_count=len(records),
        records=records,
        request_evidence=request,
    )


def test_atomic_import_is_idempotent_and_rejects_conflicting_evidence(
    store: IntegrationStore,
) -> None:
    records = [sale("sale-1", 1, 800_000)]
    first = import_release(
        store,
        release_id=SALES_RELEASE,
        dataset="nsw-psi-sales",
        schema="propertyscope.property-sales.v2",
        records=records,
        key="sales-import-0001",
    )
    replay = import_release(
        store,
        release_id=SALES_RELEASE,
        dataset="nsw-psi-sales",
        schema="propertyscope.property-sales.v2",
        records=records,
        key="sales-import-0001",
    )

    assert first["status"] == "accepted"
    assert replay["replayed"] is True
    retained = store.find_import("feature-2", "sales-import-0001")
    assert retained["request"]["release_id"] == SALES_RELEASE
    assert retained["receipt"]["rows_accepted"] == 1

    with pytest.raises(ConflictError, match="different evidence"):
        store.import_release(
            target_feature="feature-2",
            idempotency_key="sales-import-0001",
            provider_release_id=SALES_RELEASE,
            dataset_id="nsw-psi-sales",
            schema_version="propertyscope.property-sales.v2",
            content_sha256="b" * 64,
            record_count=1,
            records=records,
        )


def test_failed_record_validation_rolls_back_the_whole_release(store: IntegrationStore) -> None:
    records = [sale("valid", 1, 700_000), {**sale("invalid", 1, 800_000), "property_ref": "no"}]
    with pytest.raises(ValidationError, match="property_ref must be a UUID"):
        import_release(
            store,
            release_id=SALES_RELEASE,
            dataset="nsw-psi-sales",
            schema="propertyscope.property-sales.v2",
            records=records,
            key="rollback-import-0001",
        )
    assert store.list_imports() == []


def test_stream_failure_after_flushed_batch_rolls_back_every_row(store: IntegrationStore) -> None:
    def records() -> Any:
        for index in range(1_000):
            yield sale(f"sale-{index}", 1, 700_000 + index)
        yield {**sale("invalid", 1, 800_000), "property_ref": "not-a-uuid"}

    with pytest.raises(ValidationError, match="property_ref must be a UUID"):
        store.import_release(
            target_feature="feature-2",
            idempotency_key="large-rollback-0001",
            provider_release_id=SALES_RELEASE,
            dataset_id="nsw-psi-sales",
            schema_version="propertyscope.property-sales.v2",
            content_sha256="c" * 64,
            record_count=1_001,
            records=records(),
        )

    assert store.list_imports() == []
    accepted = import_release(
        store,
        release_id=SALES_RELEASE,
        dataset="nsw-psi-sales",
        schema="propertyscope.property-sales.v2",
        records=[sale("sale-after-rollback", 1, 900_000)],
        key="retry-after-rollback-0001",
    )
    assert accepted["rows_accepted"] == 1


def test_market_summary_uses_visible_poc_policy_and_optimistic_versions(
    store: IntegrationStore,
) -> None:
    import_release(
        store,
        release_id=SALES_RELEASE,
        dataset="nsw-psi-sales",
        schema="propertyscope.property-sales.v2",
        records=[
            sale("sale-1", 1, 700_000),
            sale("sale-1", 2, 900_000),
            sale("sale-2", 1, 1_100_000, "2025-02-01"),
            sale("sale-3", 1, None, "2025-02-02"),
        ],
        key="summary-import-0001",
    )
    market_case = store.create_market_case(
        {
            "name": "Sydney evidence",
            "property_ref": PROPERTY,
            "date_from": "2025-01-01",
            "date_to": "2025-12-31",
        }
    )
    summary = store.sales_summary(market_case["id"])
    assert summary["observation_count"] == 4
    assert summary["selected_transaction_count"] == 3
    assert summary["priced_sample_count"] == 2
    assert summary["median_price_aud"] == 1_000_000
    assert summary["exclusions"] == {
        "missing_price": 1,
        "superseded_source_revisions": 1,
    }
    assert "not an approved comparable-sales policy" in summary["limitations"][0]

    updated = store.update_market_case(market_case["id"], 1, {"notes": "Reviewed"})
    assert updated["version"] == 2
    with pytest.raises(ConflictError, match="version conflict"):
        store.update_market_case(market_case["id"], 1, {"notes": "Stale"})


def test_place_summary_preserves_postcode_and_school_limitations(store: IntegrationStore) -> None:
    import_release(
        store,
        release_id=CRIME_RELEASE,
        dataset="bocsar-crime",
        schema="propertyscope.crime-series.v1",
        records=[
            {
                "geography_kind": "postcode",
                "geography_value": "2000",
                "source_category_key": "category-1",
                "offence_label": "Synthetic offence label",
                "subcategory_label": "Synthetic subcategory",
                "observed_months": ["2025-01-01", "2025-02-01"],
                "first_month": "2025-01-01",
                "last_month": "2025-02-01",
                "blank_means_observed_zero": True,
                "observations": [{"month": "2025-02-01", "count": 2}],
                "provenance": {"release_id": CRIME_RELEASE},
            }
        ],
        key="crime-import-0001",
    )
    import_release(
        store,
        release_id=SCHOOL_RELEASE,
        dataset="nsw-government-schools",
        schema="propertyscope.school-points.v1",
        records=[
            {
                "school_code": "S001",
                "school_name": "Example Public School",
                "school_type": "Primary",
                "operational_status": "Open",
                "locality_original": "Sydney",
                "locality_normalised": "SYDNEY",
                "lga": "CITY OF SYDNEY",
                "latitude": -33.86,
                "longitude": 151.20,
                "provenance": {"release_id": SCHOOL_RELEASE},
            }
        ],
        key="school-import-0001",
    )
    summary = store.place_summary("2000", latitude=-33.86, longitude=151.20)
    assert summary["crime_series"][0]["observed_count"] == 2
    assert summary["nearby_schools"][0]["distance_km"] == 0
    assert any("not a suburb safety score" in item for item in summary["limitations"])
    assert any("does not imply catchment" in item for item in summary["limitations"])


def test_site_and_buyer_aggregates_never_invent_due_diligence_evidence(
    store: IntegrationStore,
) -> None:
    review = store.create_site_review(
        {"property_ref": PROPERTY, "name": "Professional verification review"}
    )
    check = store.add_site_item(
        review["id"], {"item_kind": "check", "text": "Ask council about current zoning"}
    )
    question = store.add_site_item(
        review["id"], {"item_kind": "question", "text": "Is a planning certificate current?"}
    )
    assert {item["item_kind"] for item in store.list_site_items(review["id"])} == {
        "check",
        "question",
    }
    assert all(
        item["state"] == "unavailable" for item in store.site_evidence(review["id"])["evidence"]
    )
    store.update_site_item(check["id"], 1, {"completed": True})
    store.delete_site_item(question["id"], 1)

    buyer = store.create_buyer_case({"actor_ref": "demo-user", "name": "Buyer POC"})
    shortlisted = store.add_case_property(
        buyer["id"], {"property_ref": PROPERTY, "stage": "shortlisted", "rating": 4}
    )
    store.add_case_note(
        buyer["id"], {"case_property_id": shortlisted["id"], "body": "Inspect Saturday"}
    )
    task = store.add_case_task(
        buyer["id"], {"case_property_id": shortlisted["id"], "title": "Book inspection"}
    )
    store.update_case_child("properties", shortlisted["id"], 1, {"stage": "inspecting"})
    store.update_case_child("tasks", task["id"], 1, {"completed": True})
    summary = store.buyer_summary(buyer["id"])
    assert summary["stage_counts"]["inspecting"] == 1
    assert summary["open_task_count"] == 0
    assert (
        "Planning, environmental, strata and building evidence is unavailable."
        in summary["missing_evidence"]
    )


def test_private_http_api_requires_token_and_returns_problem_details(tmp_path: Path) -> None:
    app = create_app(
        {"TESTING": True, "DATABASE_PATH": tmp_path / "api.sqlite3", "INTERNAL_TOKEN": "test-token"}
    )
    client = app.test_client()

    unauthorised = client.get("/internal/v1/imports", headers={"X-Request-ID": "request-123"})
    assert unauthorised.status_code == 401
    assert unauthorised.content_type == "application/problem+json"
    problem = unauthorised.get_json()
    assert isinstance(problem, dict)
    assert problem["request_id"] == "request-123"
    assert unauthorised.headers["X-Request-ID"] == "request-123"

    authorised = client.get("/internal/v1/imports", headers={"Authorization": "Bearer test-token"})
    assert authorised.status_code == 200
    assert authorised.json == {"count": 0, "items": []}
    uuid.UUID(authorised.headers["X-Request-ID"])

    malformed = client.post(
        "/internal/v1/market-cases",
        headers={"Authorization": "Bearer test-token"},
        json={"name": "Missing property"},
    )
    assert malformed.status_code == 422
    assert malformed.content_type == "application/problem+json"


def test_private_http_api_streams_ndjson_publication(tmp_path: Path) -> None:
    app = create_app(
        {"TESTING": True, "DATABASE_PATH": tmp_path / "stream.sqlite3", "INTERNAL_TOKEN": "token"}
    )
    client = app.test_client()
    publication = {
        "release_id": SALES_RELEASE,
        "dataset_id": "nsw-psi-sales",
        "target_feature": "feature-2",
        "schema_version": "propertyscope.property-sales.v2",
        "content_sha256": "d" * 64,
        "record_count": 2,
        "manifest": {"release_id": SALES_RELEASE},
        "artifact_path": f"/api/data-platform/v1/dataset-releases/{SALES_RELEASE}/artifact",
        "idempotency_key": "http-stream-import-0001",
    }
    lines = [
        json.dumps({"publication": publication}),
        json.dumps(sale("stream-1", 1, 800_000)),
        json.dumps(sale("stream-2", 1, 1_000_000)),
    ]
    response = client.post(
        "/internal/v1/imports",
        headers={"Authorization": "Bearer token"},
        content_type="application/x-ndjson",
        data="\n".join(lines),
    )
    assert response.status_code == 201
    assert response.get_json()["rows_accepted"] == 2

    retained = client.get(
        "/internal/v1/imports/feature-2/http-stream-import-0001",
        headers={"Authorization": "Bearer token"},
    )
    assert retained.status_code == 200
    assert retained.get_json()["request"] == publication


def test_store_client_uses_separate_source_scale_deadlines() -> None:
    client = StoreHttpClient(
        "http://store.local",
        "token",
        connect_timeout_seconds=2,
        read_timeout_seconds=14_400,
        write_timeout_seconds=300,
        pool_timeout_seconds=3,
    )
    try:
        assert client.timeout_configuration.connect == 2
        assert client.timeout_configuration.read == 14_400
        assert client.timeout_configuration.write == 300
        assert client.timeout_configuration.pool == 3
    finally:
        client.close()

    with pytest.raises(ValueError, match="timeouts must be positive"):
        StoreHttpClient("http://store.local", "token", read_timeout_seconds=0)


def test_source_scale_limits_are_operator_configurable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("POC_F6_MAX_ARTIFACT_BYTES", "300000000")
    monkeypatch.setenv("POC_F6_STORE_CONNECT_TIMEOUT_SECONDS", "7")
    monkeypatch.setenv("POC_F6_STORE_READ_TIMEOUT_SECONDS", "18000")
    monkeypatch.setenv("POC_F6_STORE_WRITE_TIMEOUT_SECONDS", "600")
    monkeypatch.setenv("POC_F6_STORE_POOL_TIMEOUT_SECONDS", "9")

    settings = Settings.from_environment()

    assert settings.maximum_artifact_bytes == 300_000_000
    assert settings.store_connect_timeout_seconds == 7
    assert settings.store_read_timeout_seconds == 18_000
    assert settings.store_write_timeout_seconds == 600
    assert settings.store_pool_timeout_seconds == 9
