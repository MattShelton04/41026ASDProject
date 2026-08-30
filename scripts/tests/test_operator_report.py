"""Tests for the bounded read-only operator workflow."""

from __future__ import annotations

import httpx
import pytest
from scripts.devtools.operator_report import (
    MAX_PROJECTED_ITEMS,
    OperatorReportError,
    collect_operator_report,
    render_operator_report,
)


def test_report_projects_products_release_work_and_degraded_dependencies() -> None:
    def service(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/data-products"):
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "dataset_id": "schools",
                            "product_schema_version": "2",
                            "latest_accepted_release": {
                                "id": "accepted-1",
                                "record_count": 2210,
                            },
                        }
                    ]
                },
            )
        if request.url.path.endswith("/dataset-releases"):
            assert str(request.url.params) == "limit=100&offset=0"
            return httpx.Response(
                200,
                json={"items": [{"id": "candidate-1", "status": "awaiting_review"}]},
            )
        if request.url.path.endswith("/dataset-releases/candidate-1"):
            return httpx.Response(
                200,
                json={
                    "consumer_imports": [{"id": "import-1", "status": "running"}],
                    "activations": [{"id": "activation-1", "status": "queued"}],
                },
            )
        if request.url.host == "feature.test":
            return httpx.Response(200, json={"service": "feature-1", "status": "healthy"})
        if request.url.host == "ai.test":
            return httpx.Response(
                200,
                json={
                    "service": "ai-mode",
                    "status": "degraded",
                    "checks": {"llm_provider": {"status": "degraded"}},
                },
            )
        raise AssertionError(f"unexpected request {request.url}")

    with httpx.Client(transport=httpx.MockTransport(service)) as client:
        report = collect_operator_report(
            client,
            data_base_url="https://data.test/api/data-platform/v1",
            feature_health_url="https://feature.test/health/ready",
            ai_health_url="https://ai.test/health/ready",
        )

    assert report["accepted_releases"][0]["release"]["id"] == "accepted-1"
    assert report["consumer_import_operations"] == [{"id": "import-1", "status": "running"}]
    assert report["activations"] == [{"id": "activation-1", "status": "queued"}]
    assert report["health"][1]["status"] == "degraded"
    output = render_operator_report(report)
    assert "explicit approval and consumer acceptance are required" in output
    assert "No review, publication, import, or activation action was performed." in output


def test_operator_cli_is_explicit_and_read_only(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from scripts import dev

    observed: dict[str, str] = {}
    monkeypatch.setattr(
        dev,
        "collect_operator_report",
        lambda _client, **values: (
            observed.update(values)
            or {
                "registered_products": [],
                "accepted_releases": [],
                "review_publication_prerequisites": [],
                "consumer_import_operations": [],
                "activations": [],
                "health": [],
            }
        ),
    )

    assert dev.main(["operator", "report"]) == 0
    assert observed["data_base_url"].endswith("/api/data-platform/v1")
    assert "read-only" in capsys.readouterr().out


def test_report_rejects_oversized_responses() -> None:
    with (
        httpx.Client(
            transport=httpx.MockTransport(
                lambda _request: httpx.Response(200, content=b"x" * 1_048_577)
            )
        ) as client,
        pytest.raises(OperatorReportError, match="response limit"),
    ):
        collect_operator_report(
            client,
            data_base_url="https://data.test/api/data-platform/v1",
            feature_health_url="https://feature.test/health/ready",
            ai_health_url="https://ai.test/health/ready",
        )


def test_nested_operation_projection_stops_at_global_bound() -> None:
    nested = [{"id": f"operation-{index}", "status": "running"} for index in range(150)]

    def service(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/data-products"):
            return httpx.Response(200, json={"items": []})
        if request.url.path.endswith("/dataset-releases"):
            return httpx.Response(200, json={"items": [{"id": "release-1", "status": "candidate"}]})
        if request.url.path.endswith("/dataset-releases/release-1"):
            return httpx.Response(200, json={"consumer_imports": nested, "activations": nested})
        return httpx.Response(200, json={"service": "test", "status": "healthy"})

    with httpx.Client(transport=httpx.MockTransport(service)) as client:
        report = collect_operator_report(
            client,
            data_base_url="https://data.test/api/data-platform/v1",
            feature_health_url="https://feature.test/health/ready",
            ai_health_url="https://ai.test/health/ready",
        )

    assert len(report["consumer_import_operations"]) == MAX_PROJECTED_ITEMS
    assert len(report["activations"]) == MAX_PROJECTED_ITEMS
