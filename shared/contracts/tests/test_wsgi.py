"""Request-boundary regressions: malformed framing must never cause read(-1)."""

from __future__ import annotations

import io

import pytest

from shared_contracts import read_json_object


@pytest.mark.parametrize("length", ["-1", "-20", "nope", "1.0", " 3", "٣", 3, 0, False])
def test_invalid_length_never_reads(length: object) -> None:
    stream = io.BytesIO(b'{"secret": true}')
    with pytest.raises(ValueError, match="Content-Length"):
        read_json_object({"CONTENT_LENGTH": length, "wsgi.input": stream}, max_bytes=100)
    assert stream.tell() == 0


def test_oversize_never_reads() -> None:
    stream = io.BytesIO(b"{}")
    with pytest.raises(ValueError, match="body_too_large"):
        read_json_object({"CONTENT_LENGTH": "101", "wsgi.input": stream}, max_bytes=100)
    assert stream.tell() == 0


@pytest.mark.parametrize("body", [b"[]", b"null", b"1", b'"string"'])
def test_only_objects_are_accepted(body: bytes) -> None:
    with pytest.raises(ValueError, match="object"):
        read_json_object(
            {"CONTENT_LENGTH": str(len(body)), "wsgi.input": io.BytesIO(body)}, max_bytes=100
        )


def test_exact_length_and_empty_contract() -> None:
    stream = io.BytesIO(b'{"ok":1}ignored')
    assert read_json_object({"CONTENT_LENGTH": "8", "wsgi.input": stream}, max_bytes=8) == {"ok": 1}
    assert stream.tell() == 8
    assert read_json_object({}, max_bytes=100) == {}


def test_truncated_body_is_rejected() -> None:
    with pytest.raises(ValueError, match="incomplete"):
        read_json_object({"CONTENT_LENGTH": "9", "wsgi.input": io.BytesIO(b"{}")}, max_bytes=100)
