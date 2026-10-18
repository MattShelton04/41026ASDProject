"""Suburb-map routes: the private database API and the public backend relay."""

from __future__ import annotations

from typing import Any, cast
from unittest.mock import MagicMock

import httpx
import orjson
import pytest
from flask import Flask
from flask.testing import FlaskClient

import propertyscope_data_store.api as store_api
from propertyscope_data_platform.app import create_app as create_backend_app
from propertyscope_data_platform.clients import AiModeClient, DataStoreClient
from propertyscope_data_store._suburb_map_reads import build_map_context_request
from propertyscope_data_store.api import create_blueprint, register_error_handlers
from propertyscope_data_store.errors import (
    ResponseLimitExceededError,
    StoreError,
    SuburbBoundariesUnavailableError,
    SuburbNotFoundError,
)
from propertyscope_data_store.repository import PropertyScopeStore
from shared_contracts import PROBLEM_DETAIL_MEDIA_TYPE, REQUEST_ID_HEADER

INTERNAL = "/internal/data-platform/v1"
PUBLIC = "/api/data-platform/v1"
TOKEN = {"X-PropertyScope-Internal-Token": "internal-token"}
DETAIL_ETAG = '"sd1-0123456789abcdef0123456789abcdef01234567"'
CONTEXT_ETAG = '"smc1-0123456789abcdef0123456789abcdef01234567"'


# Private database API ----------------------------------------------------------------------


def _store() -> MagicMock:
    store = MagicMock(spec=PropertyScopeStore)
    store.suburb_search.return_value = {"match": "unique", "items": [{"suburb_id": "108502"}]}
    store.suburb_detail_etag.return_value = DETAIL_ETAG
    store.suburb_detail.return_value = ({"suburb_id": "108502"}, DETAIL_ETAG)
    store.suburb_map_context_etag.return_value = CONTEXT_ETAG
    store.suburb_map_context.return_value = ({"layers": {}}, CONTEXT_ETAG)
    return store


def _db_client(store: MagicMock) -> FlaskClient:
    app = Flask(__name__)
    app.register_blueprint(create_blueprint(cast(Any, store), internal_token="internal-token"))
    register_error_handlers(app)
    return app.test_client()


def test_detail_returns_json_with_validators() -> None:
    store = _store()

    response = _db_client(store).get(f"{INTERNAL}/suburbs/108502", headers=TOKEN)

    assert response.status_code == 200
    assert response.content_type == "application/json"
    assert response.headers["ETag"] == DETAIL_ETAG
    assert response.headers["Cache-Control"] == "no-cache"
    assert response.get_json() == {"suburb_id": "108502"}
    store.suburb_detail_etag.assert_called_once_with("108502")
    store.suburb_detail.assert_called_once_with("108502")


def test_map_context_returns_json_with_validators_for_the_normalised_request() -> None:
    store = _store()

    response = _db_client(store).get(
        f"{INTERNAL}/suburbs/108502/map-context?categories=Library,schools,library&zoom=15",
        headers=TOKEN,
    )

    assert response.status_code == 200
    assert response.headers["ETag"] == CONTEXT_ETAG
    assert response.headers["Cache-Control"] == "no-cache"
    assert orjson.loads(response.data) == {"layers": {}}
    expected = build_map_context_request(
        "108502", {"categories": "library,schools", "detail": "high"}
    )
    store.suburb_map_context_etag.assert_called_once_with(expected)
    store.suburb_map_context.assert_called_once_with(expected)


def test_search_passes_validated_fields_and_disables_caching() -> None:
    store = _store()

    response = _db_client(store).get(
        f"{INTERNAL}/suburbs/search?q=%20Ashfield%20&postcode=2131&limit=5", headers=TOKEN
    )

    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-cache"
    assert response.get_json()["match"] == "unique"
    store.suburb_search.assert_called_once_with("Ashfield", postcode="2131", limit=5)


def test_search_defaults_postcode_and_limit() -> None:
    store = _store()

    _db_client(store).get(f"{INTERNAL}/suburbs/search?q=Ashfield&postcode=", headers=TOKEN)

    store.suburb_search.assert_called_once_with("Ashfield", postcode=None, limit=20)


_MATCHING_VALIDATORS = [
    "{etag}",
    "W/{etag}",
    '"other", {etag}',
    '"other",W/{etag}',
    ' "other" ,  {etag} ',
]
_MATCHING_IDS = ["exact", "weak", "list", "weak-in-list", "spaced-list"]


@pytest.mark.parametrize("template", _MATCHING_VALIDATORS, ids=_MATCHING_IDS)
def test_detail_revalidation_answers_304_without_the_full_read(template: str) -> None:
    store = _store()

    response = _db_client(store).get(
        f"{INTERNAL}/suburbs/108502",
        headers={**TOKEN, "If-None-Match": template.format(etag=DETAIL_ETAG)},
    )

    assert response.status_code == 304
    assert response.data == b""
    assert response.headers["ETag"] == DETAIL_ETAG
    assert response.headers["Cache-Control"] == "no-cache"
    store.suburb_detail.assert_not_called()


@pytest.mark.parametrize("template", _MATCHING_VALIDATORS, ids=_MATCHING_IDS)
def test_map_context_revalidation_answers_304_without_the_full_read(template: str) -> None:
    store = _store()

    response = _db_client(store).get(
        f"{INTERNAL}/suburbs/108502/map-context?categories=library",
        headers={**TOKEN, "If-None-Match": template.format(etag=CONTEXT_ETAG)},
    )

    assert response.status_code == 304
    assert response.data == b""
    assert response.headers["ETag"] == CONTEXT_ETAG
    store.suburb_map_context.assert_not_called()


@pytest.mark.parametrize(
    "validator",
    ['"other"', CONTEXT_ETAG[1:-1], f'"{"a" * 2050}", {CONTEXT_ETAG}', "", "*"],
    ids=["different", "unquoted", "over-length", "empty", "star-needs-existence-check"],
)
def test_map_context_non_matching_validator_reads_in_full(validator: str) -> None:
    store = _store()

    response = _db_client(store).get(
        f"{INTERNAL}/suburbs/108502/map-context",
        headers={**TOKEN, "If-None-Match": validator},
    )

    assert response.status_code == 200
    store.suburb_map_context.assert_called_once()


@pytest.mark.parametrize(
    ("error", "status", "code"),
    [
        (SuburbNotFoundError("suburb 108502 is not accepted"), 404, "suburb_not_found"),
        (
            SuburbBoundariesUnavailableError("no accepted boundaries"),
            503,
            "suburb_boundaries_unavailable",
        ),
        (ResponseLimitExceededError("too many coordinates"), 422, "response_limit_exceeded"),
    ],
    ids=["not-found", "boundaries-unavailable", "response-limit"],
)
@pytest.mark.parametrize("route", ["detail", "map-context"])
def test_store_failures_map_to_problem_details(
    error: StoreError, status: int, code: str, route: str
) -> None:
    store = _store()
    store.suburb_detail.side_effect = error
    store.suburb_map_context.side_effect = error
    path = f"{INTERNAL}/suburbs/108502" + ("/map-context" if route == "map-context" else "")

    response = _db_client(store).get(path, headers=TOKEN)

    assert response.status_code == status
    assert response.content_type == PROBLEM_DETAIL_MEDIA_TYPE
    body = response.get_json()
    assert body["code"] == code
    assert body["status"] == status
    assert body["detail"] == str(error)


def test_search_boundaries_unavailable_is_a_problem() -> None:
    store = _store()
    store.suburb_search.side_effect = SuburbBoundariesUnavailableError("no boundaries")

    response = _db_client(store).get(f"{INTERNAL}/suburbs/search?q=Ashfield", headers=TOKEN)

    assert response.status_code == 503
    assert response.get_json()["code"] == "suburb_boundaries_unavailable"


@pytest.mark.parametrize("categories", ["parks", "library,cafes"], ids=["declined", "unknown"])
def test_unsupported_category_is_a_422_problem(categories: str) -> None:
    store = _store()

    response = _db_client(store).get(
        f"{INTERNAL}/suburbs/108502/map-context?categories={categories}", headers=TOKEN
    )

    assert response.status_code == 422
    assert response.content_type == PROBLEM_DETAIL_MEDIA_TYPE
    assert response.get_json()["code"] == "unsupported_category"
    store.suburb_map_context_etag.assert_not_called()


def test_map_context_byte_ceiling_is_a_422_problem(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(store_api, "MAX_RESPONSE_BYTES", 32)
    store = _store()
    store.suburb_map_context.return_value = ({"layers": {"library": "x" * 64}}, CONTEXT_ETAG)

    response = _db_client(store).get(f"{INTERNAL}/suburbs/108502/map-context", headers=TOKEN)

    assert response.status_code == 422
    assert response.content_type == PROBLEM_DETAIL_MEDIA_TYPE
    assert response.get_json()["code"] == "response_limit_exceeded"
    assert "ETag" not in response.headers


@pytest.mark.parametrize(
    "path",
    [
        f"{INTERNAL}/suburbs/108502/map-context?bbox=1",
        f"{INTERNAL}/suburbs/108502/map-context?detail=low&zoom=3",
        f"{INTERNAL}/suburbs/108502/map-context?limit=0",
        f"{INTERNAL}/suburbs/0123/map-context",
        f"{INTERNAL}/suburbs/108502?detail=low",
        f"{INTERNAL}/suburbs/abc",
        f"{INTERNAL}/suburbs/search",
        f"{INTERNAL}/suburbs/search?q=%20%20",
        f"{INTERNAL}/suburbs/search?q=Ashfield&state=NSW",
        f"{INTERNAL}/suburbs/search?q=Ashfield&limit=0",
        f"{INTERNAL}/suburbs/search?q=Ashfield&limit=51",
        f"{INTERNAL}/suburbs/search?q=Ashfield&limit=ten",
    ],
    ids=[
        "map-context-unknown-field",
        "map-context-detail-and-zoom",
        "map-context-limit-zero",
        "map-context-invalid-id",
        "detail-with-query",
        "detail-invalid-id",
        "search-without-q",
        "search-blank-q",
        "search-unknown-field",
        "search-limit-zero",
        "search-limit-over-max",
        "search-limit-text",
    ],
)
def test_invalid_requests_are_422_problems_without_store_reads(path: str) -> None:
    store = _store()

    response = _db_client(store).get(path, headers=TOKEN)

    assert response.status_code == 422
    assert response.content_type == PROBLEM_DETAIL_MEDIA_TYPE
    assert response.get_json()["code"] == "invalid_request"
    store.suburb_search.assert_not_called()
    store.suburb_detail_etag.assert_not_called()
    store.suburb_map_context_etag.assert_not_called()


def test_suburb_routes_require_the_internal_token() -> None:
    store = _store()

    response = _db_client(store).get(f"{INTERNAL}/suburbs/108502")

    assert response.status_code == 401
    store.suburb_detail_etag.assert_not_called()


# Public backend relay ----------------------------------------------------------------------


class Upstream:
    """Records relayed requests and answers each with one scripted response."""

    def __init__(self, response: httpx.Response) -> None:
        self.response = response
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self.response


def _backend(upstream: Upstream) -> FlaskClient:
    app = create_backend_app(
        store_client=DataStoreClient(
            "http://database",
            "secret",
            client=httpx.Client(transport=httpx.MockTransport(upstream)),
        ),
        ai_mode_client=AiModeClient(
            "http://ai",
            client=httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(503))),
        ),
    )
    return app.test_client()


def _json_upstream(body: bytes, **headers: str) -> Upstream:
    return Upstream(
        httpx.Response(
            200,
            content=body,
            headers={
                "Content-Type": "application/json",
                "ETag": CONTEXT_ETAG,
                "Cache-Control": "no-cache",
                **headers,
            },
        )
    )


@pytest.mark.parametrize(
    ("path", "internal_path"),
    [
        (f"{PUBLIC}/suburbs/search?q=Ashfield", f"{INTERNAL}/suburbs/search"),
        (f"{PUBLIC}/suburbs/108502", f"{INTERNAL}/suburbs/108502"),
        (f"{PUBLIC}/suburbs/108502/map-context", f"{INTERNAL}/suburbs/108502/map-context"),
    ],
    ids=["search", "detail", "map-context"],
)
def test_backend_relays_json_bytes_and_validators(path: str, internal_path: str) -> None:
    body = b'{"suburb_id":"108502","name":"Ashfield"}'
    upstream = _json_upstream(body)

    response = _backend(upstream).get(path)

    assert response.status_code == 200
    assert response.data == body
    assert response.content_type == "application/json"
    assert response.headers["ETag"] == CONTEXT_ETAG
    assert response.headers["Cache-Control"] == "no-cache"
    (relayed,) = upstream.requests
    assert relayed.method == "GET"
    assert relayed.url.path == internal_path
    assert relayed.headers["X-PropertyScope-Internal-Token"] == "secret"


def test_backend_relays_a_304_with_validators_and_no_body() -> None:
    upstream = Upstream(
        httpx.Response(
            304,
            headers={
                "ETag": CONTEXT_ETAG,
                "Cache-Control": "no-cache",
                REQUEST_ID_HEADER: "req-304",
            },
        )
    )

    response = _backend(upstream).get(
        f"{PUBLIC}/suburbs/108502/map-context", headers={"If-None-Match": CONTEXT_ETAG}
    )

    assert response.status_code == 304
    assert response.data == b""
    assert response.headers["ETag"] == CONTEXT_ETAG
    assert response.headers["Cache-Control"] == "no-cache"
    assert response.headers[REQUEST_ID_HEADER] == "req-304"


@pytest.mark.parametrize(
    ("status", "code"),
    [
        (404, "suburb_not_found"),
        (503, "suburb_boundaries_unavailable"),
        (422, "unsupported_category"),
        (422, "response_limit_exceeded"),
    ],
)
def test_backend_passes_problem_details_through(status: int, code: str) -> None:
    problem = {
        "type": f"https://propertyscope.local/problems/{code}",
        "title": code.replace("_", " ").title(),
        "status": status,
        "detail": "upstream detail",
        "code": code,
        "request_id": "req-1",
    }
    upstream = Upstream(
        httpx.Response(
            status,
            content=orjson.dumps(problem),
            headers={"Content-Type": PROBLEM_DETAIL_MEDIA_TYPE},
        )
    )

    response = _backend(upstream).get(f"{PUBLIC}/suburbs/108502/map-context")

    assert response.status_code == status
    assert response.content_type == PROBLEM_DETAIL_MEDIA_TYPE
    assert response.get_json() == problem
    assert "ETag" not in response.headers


@pytest.mark.parametrize(
    ("validator", "forwarded"),
    [
        (CONTEXT_ETAG, True),
        (f'W/"{"a" * 2044}"', True),
        (f'W/"{"a" * 2045}"', False),
        (f'"{"a" * 4096}"', False),
    ],
    ids=["normal", "exactly-2048", "2049", "4098"],
)
def test_backend_forwards_bounded_if_none_match(validator: str, forwarded: bool) -> None:
    upstream = _json_upstream(b"{}")

    _backend(upstream).get(
        f"{PUBLIC}/suburbs/108502/map-context", headers={"If-None-Match": validator}
    )

    (relayed,) = upstream.requests
    if forwarded:
        assert relayed.headers["If-None-Match"] == validator
    else:
        assert "If-None-Match" not in relayed.headers


def test_backend_does_not_forward_unlisted_conditional_headers() -> None:
    upstream = _json_upstream(b"{}")

    _backend(upstream).get(
        f"{PUBLIC}/suburbs/108502",
        headers={"If-Modified-Since": "Sat, 17 Oct 2026 00:00:00 GMT", "Cookie": "a=b"},
    )

    (relayed,) = upstream.requests
    assert "If-Modified-Since" not in relayed.headers
    assert "Cookie" not in relayed.headers


@pytest.mark.parametrize(
    "public_suffix",
    [
        "a%20b",
        "a%20b/map-context",
        "a%3Fx=1",
        "a%23frag",
        "%25zz",
        "0123",
        "1234567890123",
        "%2E%2E/map-context",
        "%2E%2E",
        "%2E/map-context",
    ],
    ids=[
        "space",
        "space-map-context",
        "question-mark",
        "hash",
        "percent",
        "leading-zero",
        "thirteen-digits",
        "dot-dot-map-context",
        "dot-dot-detail",
        "dot-map-context",
    ],
)
def test_backend_rejects_non_cadid_suburb_ids_before_relaying(public_suffix: str) -> None:
    """Only a publisher cadid may enter an internal path carrying the service credential."""
    upstream = _json_upstream(b"{}")

    response = _backend(upstream).get(f"{PUBLIC}/suburbs/{public_suffix}")

    assert response.status_code == 422
    assert response.get_json()["code"] == "invalid_request"
    assert upstream.requests == []


def test_backend_does_not_route_an_encoded_slash_upstream() -> None:
    upstream = _json_upstream(b"{}")

    response = _backend(upstream).get(f"{PUBLIC}/suburbs/a%2Fb/map-context")

    assert response.status_code == 404
    assert upstream.requests == []


@pytest.mark.parametrize(
    ("path", "params"),
    [
        (
            f"{PUBLIC}/suburbs/108502/map-context?categories=library,schools&zoom=13&limit=25",
            {"categories": "library,schools", "zoom": "13", "limit": "25"},
        ),
        (
            f"{PUBLIC}/suburbs/search?q=St%20Ives&postcode=2075&limit=5",
            {"q": "St Ives", "postcode": "2075", "limit": "5"},
        ),
        (f"{PUBLIC}/suburbs/108502?unexpected=1", {"unexpected": "1"}),
    ],
    ids=["map-context", "search", "detail"],
)
def test_backend_forwards_query_parameters(path: str, params: dict[str, str]) -> None:
    upstream = _json_upstream(b"{}")

    _backend(upstream).get(path)

    (relayed,) = upstream.requests
    assert dict(relayed.url.params) == params
