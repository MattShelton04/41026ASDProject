"""Tests for bounded Release 0 Compose verification."""

from __future__ import annotations

import json
from pathlib import Path
from urllib.error import HTTPError

import pytest
from scripts import verify_release0_stack as verifier


class _Response:
    def __init__(self, status: int, body: bytes = b"{}", headers: dict[str, str] | None = None):
        self.status = status
        self._body = body
        self.headers = headers or {}

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self) -> bytes:
        return self._body


class _Opener:
    def __init__(self, responses: list[object]):
        self.responses = responses

    def open(self, *_args: object, **_kwargs: object) -> _Response:
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        assert isinstance(response, _Response)
        return response


def test_request_retries_transient_status_and_records_attempts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    opener = _Opener([_Response(503), _Response(200)])
    monkeypatch.setattr(verifier, "build_opener", lambda *_args: opener)
    monkeypatch.setattr(verifier.time, "sleep", lambda _seconds: None)

    result = verifier._request(
        verifier.HttpCheck("ready", "https://example.test"), deadline_seconds=5
    )

    assert result["status"] == "passed"
    assert result["attempts"] == 2


def test_request_validates_non_followed_redirect(monkeypatch: pytest.MonkeyPatch) -> None:
    error = HTTPError(
        "https://example.test/planned",
        307,
        "Temporary Redirect",
        {"Location": "/#features"},
        None,
    )
    monkeypatch.setattr(verifier, "build_opener", lambda *_args: _Opener([error]))

    result = verifier._request(
        verifier.HttpCheck(
            "redirect",
            "https://example.test/planned",
            expected_status=307,
            follow_redirects=False,
            validator=verifier._validate_redirect,
        ),
        deadline_seconds=5,
    )

    assert result["http_status"] == 307


def test_verify_retains_failure_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    evidence = tmp_path / "evidence.json"
    monkeypatch.setattr(verifier, "_checks", lambda *_args: (verifier.HttpCheck("bad", "x"),))
    monkeypatch.setattr(
        verifier,
        "_request",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(verifier.VerificationError("broken")),
    )

    with pytest.raises(verifier.VerificationError, match="broken"):
        verifier.verify(
            shared_origin="http://shared",
            feature_origin="http://feature",
            deadline_seconds=1,
            evidence_path=evidence,
        )

    payload = json.loads(evidence.read_text(encoding="utf-8"))
    assert payload["status"] == "failed"
    assert payload["checks"][-1]["error"] == "broken"


def test_verify_records_public_internal_and_fingerprint_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    evidence = tmp_path / "evidence.json"
    monkeypatch.setattr(verifier, "_checks", lambda *_args: (verifier.HttpCheck("public", "x"),))
    monkeypatch.setattr(
        verifier,
        "_request",
        lambda check, **_kwargs: {"name": check.name, "status": "passed"},
    )
    monkeypatch.setattr(
        verifier,
        "_verify_internal_services",
        lambda: [
            {"name": "internal", "status": "passed"},
            {"name": "fingerprint", "status": "passed", "fingerprint": "a" * 64},
        ],
    )

    verifier.verify(
        shared_origin="http://shared/",
        feature_origin="http://feature/",
        deadline_seconds=1,
        evidence_path=evidence,
    )

    payload = json.loads(evidence.read_text(encoding="utf-8"))
    assert payload["status"] == "passed"
    assert [check["name"] for check in payload["checks"]] == [
        "public",
        "internal",
        "fingerprint",
    ]
