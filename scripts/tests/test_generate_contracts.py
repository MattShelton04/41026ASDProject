"""Tests for semantic links in generated Shared API contracts."""

from __future__ import annotations

from scripts.generate_contracts import _openapi


def test_ai_health_operations_reference_the_typed_health_projection() -> None:
    document = _openapi()

    for path, statuses in {
        "/health/live": ("200",),
        "/health/ready": ("200", "503"),
    }.items():
        responses = document["paths"][path]["get"]["responses"]
        for status in statuses:
            assert responses[status]["content"]["application/json"]["schema"] == {
                "$ref": "#/components/schemas/TypedHealthProjection"
            }

    typed = document["components"]["schemas"]["TypedHealthProjection"]
    assert typed["additionalProperties"] is False
    assert set(typed["required"]) == {
        "checks",
        "http_status",
        "media_type",
        "schema_version",
        "service",
        "status",
        "version",
    }
