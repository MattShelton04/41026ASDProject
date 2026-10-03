"""Live evidence keeps record contents private and cleans up only owned audit records."""

from __future__ import annotations

import json

import httpx
import pytest
from scripts import capture_release1_integration as integration

EXISTING_ID = "d4000000-0000-0000-0000-000000000001"
AUDIT_ID = "12345678-1234-4234-8234-123456789abc"
SOURCE_AUDIT_ID = "22345678-1234-4234-8234-123456789abc"
PRIVATE_VALUE = "private user note and secret must not be exported"


@pytest.mark.parametrize(
    "update_fails, shared_fails", [(False, False), (True, False), (False, True)]
)
def test_capture_exports_http_evidence_and_removes_only_created_records(
    update_fails: bool, shared_fails: bool
) -> None:
    records: dict[int, dict[str, object] | None] = {5200: None, 5400: None}
    deleted: list[tuple[int, str]] = []
    inspected: list[str] = []

    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/":
            return httpx.Response(
                503 if shared_fails and request.url.port == 5100 else 200,
                text="<title>PropertyScope</title>",
                headers={"Content-Type": "text/html"},
            )
        source_definition = request.url.port == 5200
        port = request.url.port or 0
        path = (
            "/api/data-platform/v1/sources"
            if source_definition
            else "/api/due-diligence/v1/site-reviews"
        )
        if port not in records or (request.url.path == path and request.method == "GET"):
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "id": EXISTING_ID,
                            "property_ref": "a0000000-0000-0000-0000-000000000001",
                            "address_display": "11 Example Street",
                            "notes": PRIVATE_VALUE,
                        }
                    ]
                },
            )
        if request.method == "POST":
            body = json.loads(request.content)
            label = "name" if source_definition else "title"
            assert body[label].startswith("Release 1 transient integration audit ")
            record_id = SOURCE_AUDIT_ID if source_definition else AUDIT_ID
            records[port] = {**body, "id": record_id, "version": 1}
            return httpx.Response(
                201, json={"source": records[port]} if source_definition else records[port]
            )
        record_id = SOURCE_AUDIT_ID if source_definition else AUDIT_ID
        assert request.url.path == path + "/" + record_id
        if request.method == "PUT":
            if update_fails and not source_definition:
                return httpx.Response(500, json={"detail": PRIVATE_VALUE})
            record = records[port]
            assert record is not None
            payload = json.loads(request.content)
            if source_definition:
                assert payload["version"] == 1
                assert payload["status"] == "draft"
            record.update(payload)
        elif request.method == "DELETE":
            deleted.append((port, request.url.path.rsplit("/", 1)[-1]))
            records[port] = None
            return (
                httpx.Response(204)
                if source_definition
                else httpx.Response(200, json={"deleted": record_id})
            )
        record = records[port]
        return (
            httpx.Response(404, json={"error": "not_found"})
            if record is None
            else httpx.Response(200, json={"source": record} if source_definition else record)
        )

    def owner(feature: integration.Feature, project: str) -> dict[str, object]:
        assert project == "existing-audit-project"
        inspected.append(feature.database_service)
        return {
            "http_status": 200,
            "status": "healthy",
            "tables": {"domain_table": 10},
            "secret": PRIVATE_VALUE,
        }

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        evidence = integration.capture(
            project="existing-audit-project", client=client, owner_probe=owner
        )

    assert evidence["passed"] is (not update_fails and not shared_fails)
    assert evidence["shared_home"] == {
        "url": "http://127.0.0.1:5100/",
        "http_status": 503 if shared_fails else 200,
        "content_type": "text/html",
        "title": "PropertyScope",
        "passed": not shared_fails,
    }
    assert deleted == [(5200, SOURCE_AUDIT_ID), (5400, AUDIT_ID)]
    assert all(record_id != EXISTING_ID for _, record_id in deleted)
    assert inspected == [feature.database_service for feature in integration.FEATURES]
    features = evidence["features"]
    assert isinstance(features, list)
    assert features[0]["transient_crud"]["cleanup_passed"] is True
    assert features[3]["transient_crud"]["cleanup_passed"] is True
    exported = json.dumps(evidence)
    assert PRIVATE_VALUE not in exported
    assert "address_display" not in exported
    assert "notes" not in exported


def test_untrusted_created_identity_never_deletes_an_existing_record() -> None:
    methods: list[str] = []

    def respond(request: httpx.Request) -> httpx.Response:
        methods.append(request.method)
        if request.method == "GET":
            return httpx.Response(200, json={"items": [{"id": EXISTING_ID}]})
        body = json.loads(request.content)
        return httpx.Response(201, json={"source": {**body, "id": EXISTING_ID, "version": 1}})

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        outcome = integration._transient_crud(
            client, "http://127.0.0.1:5200", source_definition=True
        )

    assert outcome["passed"] is False
    assert methods == ["GET", "POST"]
    assert "record_id" not in outcome


def test_failed_database_capture_does_not_become_persistence_success() -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/":
            return httpx.Response(
                200, text="<title>PropertyScope</title>", headers={"Content-Type": "text/html"}
            )
        return httpx.Response(200, json={"items": []})

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        evidence = integration.capture(
            project="demo",
            client=client,
            owner_probe=lambda _feature, _project: {"http_status": 503, "error": PRIVATE_VALUE},
        )

    assert evidence["passed"] is False
    assert PRIVATE_VALUE not in json.dumps(evidence)


def test_count_projection_rejects_boolean_negative_and_non_numeric_counts() -> None:
    assert integration._tables(
        {"record": 10, "empty": 0, "invalid": -1, "flag": True, "text": PRIVATE_VALUE}
    ) == {"record": 10, "empty": 0}


@pytest.mark.parametrize("tracked_changes", ["", " M private-filename\n"])
def test_provenance_omits_untracked_files_and_exports_no_status_paths(
    monkeypatch: pytest.MonkeyPatch, tracked_changes: str
) -> None:
    def git_output(command: list[str], **_kwargs: object) -> str:
        if command == ["git", "rev-parse", "HEAD"]:
            return "a" * 40 + "\n"
        assert command == ["git", "status", "--porcelain", "--untracked-files=no"]
        return tracked_changes

    monkeypatch.setattr("scripts.capture_release1_integration.subprocess.check_output", git_output)
    assert integration._software_provenance() == {
        "software_sha": "a" * 40,
        "tracked_worktree_dirty": bool(tracked_changes),
    }
