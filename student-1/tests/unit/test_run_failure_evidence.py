"""A failed run task records why it failed, safely, and whether resuming can help."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from propertyscope_data_platform.adapters.arcgis import ArcGISPublisherError
from propertyscope_data_platform.runner import (
    AcquisitionRunner,
    RunnerSettings,
    _safe_task_error,
)
from propertyscope_data_store.persistence_support import retry_wait_error

QUERY_URL = (
    "https://portal.spatial.nsw.gov.au/server/rest/services/Hosted/"
    "NSW_BushFire_Prone_Land/FeatureServer/0/query"
)


def _status_error(status: int, url: str) -> httpx.HTTPStatusError:
    request = httpx.Request("GET", url)
    response = httpx.Response(status, request=request)
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        return exc
    raise AssertionError("status must be an error")


def test_acquire_failure_records_type_and_bounded_message() -> None:
    error = _safe_task_error(
        {"stage": "acquire"}, ValueError("ArcGIS acquisition is incomplete or source count changed")
    )

    assert error == {
        "code": "stage_execution_failed",
        "category": "acquisition",
        "message": (
            "Acquire stage failed (ValueError): "
            "ArcGIS acquisition is incomplete or source count changed"
        ),
        "retryable": False,
        "cause": {
            "type": "ValueError",
            "message": "ArcGIS acquisition is incomplete or source count changed",
            "transient": False,
        },
    }


def test_http_failure_evidence_omits_query_strings_and_documentation_hints() -> None:
    exc = _status_error(
        504, QUERY_URL + "?f=json&where=(1%3D1)%20AND%20objectid%3E1234&token=private-token"
    )

    error = _safe_task_error({"stage": "acquire"}, exc, retryable=True)

    cause = error["cause"]
    assert isinstance(cause, dict)
    assert cause["type"] == "HTTPStatusError"
    assert cause["http_status"] == 504
    assert cause["transient"] is True
    assert error["retryable"] is True
    assert "FeatureServer/0/query?[query omitted]" in str(cause["message"])
    assert "504 Gateway Timeout" in str(error["message"])
    serialised = json.dumps(error)
    assert "private-token" not in serialised
    assert "objectid" not in serialised
    assert "developer.mozilla.org" not in serialised


def test_publisher_error_evidence_keeps_the_arcgis_code() -> None:
    exc = ArcGISPublisherError(504, "Your request has timed out.", transient=True)

    error = _safe_task_error({"stage": "acquire"}, exc, retryable=True)

    assert error["message"] == (
        "Acquire stage failed (ArcGISPublisherError): "
        "ArcGIS publisher returned error 504: Your request has timed out."
    )
    assert error["cause"] == {
        "type": "ArcGISPublisherError",
        "message": "ArcGIS publisher returned error 504: Your request has timed out.",
        "transient": True,
        "publisher_code": 504,
    }


@pytest.mark.parametrize(
    "message",
    [
        "login failed for https://user:hunter2@example.test/path",  # pragma: allowlist secret
        "rejected api_key=hunter2 and password: hunter2",
        "Authorization: Bearer hunter2",
        "upstream said secret=hunter2&next=1",
    ],
)
def test_failure_messages_redact_credentials(message: str) -> None:
    error = _safe_task_error({"stage": "discover"}, RuntimeError(message))

    assert "hunter2" not in json.dumps(error)
    assert error["category"] == "acquisition"


def test_failure_messages_are_single_line_and_bounded() -> None:
    error = _safe_task_error({"stage": "build_release"}, RuntimeError("line\x00one\n" + "x" * 900))

    cause = error["cause"]
    assert isinstance(cause, dict)
    assert str(cause["message"]).startswith("line one x")
    assert len(str(cause["message"])) == 300
    assert str(cause["message"]).endswith("...")
    assert len(str(error["message"])) <= 500
    assert "\n" not in str(error["message"])
    assert "category" not in error  # Only source stages are acquisition failures.
    assert str(error["message"]).startswith("Build release stage failed (RuntimeError)")


def test_wrapped_failure_records_the_originating_type() -> None:
    try:
        try:
            raise httpx.ReadTimeout("read timed out")
        except httpx.ReadTimeout as inner:
            raise RuntimeError("reference stream aborted") from inner
    except RuntimeError as exc:
        error = _safe_task_error({"stage": "acquire"}, exc)

    cause = error["cause"]
    assert isinstance(cause, dict)
    assert cause["origin_type"] == "ReadTimeout"
    assert cause["transient"] is False


def test_same_named_transport_origin_is_not_repeated() -> None:
    class ConnectError(Exception):  # Mirrors httpcore's error that httpx re-raises.
        pass

    try:
        try:
            raise ConnectError("[Errno 111] Connection refused")
        except ConnectError as inner:
            raise httpx.ConnectError("[Errno 111] Connection refused") from inner
    except httpx.ConnectError as exc:
        error = _safe_task_error({"stage": "acquire"}, exc, retryable=True)

    assert error["cause"] == {
        "type": "ConnectError",
        "message": "[Errno 111] Connection refused",
        "transient": True,
    }


def test_empty_messages_are_still_explained() -> None:
    error = _safe_task_error({"stage": "acquire"}, KeyError())

    assert error["message"] == "Acquire stage failed (KeyError): no message was recorded"


@pytest.mark.parametrize(
    ("failure", "retryable"),
    [
        (ArcGISPublisherError(504, "Gateway timeout", transient=True), True),
        (ArcGISPublisherError(400, "Invalid query", transient=False), False),
        (ValueError("ArcGIS metadata changed during acquisition"), False),
    ],
    ids=["transient-publisher", "invalid-query", "metadata-changed"],
)
def test_runner_reports_transient_source_failures_as_resumable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: Exception, retryable: bool
) -> None:
    reported: list[dict[str, Any]] = []

    def backend(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/worker/tasks/claim"):
            task = {"id": "task-1", "lease_token": "lease-1", "stage": "acquire"}
            return httpx.Response(200, json={"task": task})
        if path.endswith("/heartbeat"):
            return httpx.Response(200, json={"task": {"status": "running"}})
        if path.endswith("/fail"):
            reported.append(json.loads(request.content))
            return httpx.Response(200, json={"task": {}})
        raise AssertionError(f"unexpected control request {path}")

    runner = AcquisitionRunner(
        RunnerSettings("http://backend", "token", tmp_path, "worker", 0.01, 30),
        client=httpx.Client(transport=httpx.MockTransport(backend)),
    )

    def fail(_: dict[str, Any]) -> tuple[int, int]:
        raise failure

    monkeypatch.setattr(runner, "_execute", fail)

    assert runner.run_once(include_publications=False) is True
    assert len(reported) == 1
    assert reported[0]["retryable"] is retryable
    assert reported[0]["error"]["retryable"] is retryable
    assert reported[0]["error"]["cause"]["type"] == type(failure).__name__
    assert str(failure) in reported[0]["error"]["message"]


def test_resumable_run_error_carries_the_task_cause() -> None:
    task_error = {
        "code": "stage_execution_failed",
        "message": (
            "Acquire stage failed (ArcGISPublisherError): ArcGIS publisher returned error 504"
        ),
        "retryable": True,
        "cause": {"type": "ArcGISPublisherError", "publisher_code": 504, "transient": True},
    }

    error = retry_wait_error(task_error)

    assert error["code"] == "task_retry_wait"
    assert error["retryable"] is True
    assert error["message"] == (
        "Retryable task failed; explicit resume is required. "
        "Acquire stage failed (ArcGISPublisherError): ArcGIS publisher returned error 504"
    )
    assert error["task_error"] == task_error
    assert retry_wait_error(None) == {
        "code": "task_retry_wait",
        "message": "Retryable task failed; explicit resume is required",
        "retryable": True,
    }
