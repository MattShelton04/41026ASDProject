"""Tests for the bounded read-only operator workflow."""

from __future__ import annotations

from collections.abc import Iterator

import httpx
import pytest
from scripts.devtools.operator_report import (
    MAX_PROJECTED_ITEMS,
    OperatorReportError,
    _prerequisite,
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
    assert "consumer accepted; activation is queued" in output
    assert "explicit approval and consumer acceptance are required" not in output
    assert "No review, publication, import, or activation action was performed." in output


@pytest.mark.parametrize(
    ("operation_status", "expected"),
    [
        ("queued", "explicit approval recorded; consumer import is queued"),
        ("claimed", "explicit approval recorded; consumer import is claimed"),
        ("polling", "explicit approval recorded; consumer import is polling"),
        ("receipt_pending", "consumer finished; receipt validation and persistence are pending"),
        (
            "activation_pending",
            "consumer accepted; activation queueing or reconciliation is pending",
        ),
        ("activation_queued", "consumer accepted; activation is queued"),
        ("published", "activation succeeded; release-status reconciliation is pending"),
        ("rejected", "consumer import is rejected; inspect it before a reviewed retry"),
        ("failed", "consumer import is failed; inspect it before a reviewed retry"),
    ],
)
def test_awaiting_review_prerequisite_uses_durable_publication_state(
    operation_status: str, expected: str
) -> None:
    assert (
        _prerequisite(
            "awaiting_review",
            consumer_imports=[{"status": operation_status}],
        )
        == expected
    )


def test_operator_cli_is_explicit_and_read_only(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from scripts import dev

    observed: dict[str, str] = {}
    monkeypatch.setenv("PROPERTYSCOPE_PORT", "5420")
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
    assert observed["data_base_url"] == "http://127.0.0.1:5420/api/data-platform/v1"
    assert observed["feature_health_url"] == "http://127.0.0.1:5420/health/ready"
    assert "read-only" in capsys.readouterr().out


def test_report_rejects_oversized_responses() -> None:
    class OversizedStream(httpx.SyncByteStream):
        chunks_read = 0

        def __iter__(self) -> Iterator[bytes]:
            for _ in range(2):
                self.chunks_read += 1
                yield b"x" * 600_000
            raise AssertionError("bounded reader consumed beyond the limit")

    stream = OversizedStream()
    with (
        httpx.Client(
            transport=httpx.MockTransport(lambda _request: httpx.Response(200, stream=stream))
        ) as client,
        pytest.raises(OperatorReportError, match="response limit"),
    ):
        collect_operator_report(
            client,
            data_base_url="https://data.test/api/data-platform/v1",
            feature_health_url="https://feature.test/health/ready",
            ai_health_url="https://ai.test/health/ready",
        )
    assert stream.chunks_read == 2


def test_report_requests_identity_encoding_and_rejects_compressed_control_plane() -> None:
    def service(request: httpx.Request) -> httpx.Response:
        assert request.headers["Accept-Encoding"] == "identity"
        class EncodedStream(httpx.SyncByteStream):
            def __iter__(self) -> Iterator[bytes]:
                yield b"compressed"

        return httpx.Response(
            200,
            headers={"Content-Encoding": "gzip"},
            stream=EncodedStream(),
        )

    with (
        httpx.Client(transport=httpx.MockTransport(service)) as client,
        pytest.raises(OperatorReportError, match="content encoding"),
    ):
        collect_operator_report(
            client,
            data_base_url="https://data.test/api/data-platform/v1",
            feature_health_url="https://feature.test/health/ready",
            ai_health_url="https://ai.test/health/ready",
        )


@pytest.mark.parametrize("content_length", ["-1", "invalid", str(1_048_577)])
def test_report_rejects_invalid_or_excessive_content_length(content_length: str) -> None:
    with (
        httpx.Client(
            transport=httpx.MockTransport(
                lambda _request: httpx.Response(
                    200, headers={"Content-Length": content_length}, content=b"{}"
                )
            )
        ) as client,
        pytest.raises(OperatorReportError),
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
    assert {item["collection"] for item in report["bounded_evidence"]} == {
        "consumer-import operations",
        "activations",
    }
    output = render_operator_report(report)
    assert "Bounded evidence warning: consumer-import operations may be partial" in output
    assert "Bounded evidence warning: activations may be partial" in output


def test_release_page_at_the_bound_is_explicitly_possibly_partial() -> None:
    releases = [
        {"id": f"release-{index}", "status": "candidate"} for index in range(MAX_PROJECTED_ITEMS)
    ]

    def service(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/data-products"):
            return httpx.Response(200, json={"items": []})
        if request.url.path.endswith("/dataset-releases"):
            return httpx.Response(200, json={"items": releases})
        if "/dataset-releases/" in request.url.path:
            return httpx.Response(200, json={"consumer_imports": [], "activations": []})
        return httpx.Response(200, json={"service": "test", "status": "healthy"})

    with httpx.Client(transport=httpx.MockTransport(service)) as client:
        report = collect_operator_report(
            client,
            data_base_url="https://data.test/api/data-platform/v1",
            feature_health_url="https://feature.test/health/ready",
            ai_health_url="https://ai.test/health/ready",
        )

    assert report["bounded_evidence"] == [
        {
            "collection": "release catalogue",
            "returned": MAX_PROJECTED_ITEMS,
            "limit": MAX_PROJECTED_ITEMS,
            "possibly_truncated": True,
        }
    ]
    assert "release catalogue may be partial" in render_operator_report(report)
