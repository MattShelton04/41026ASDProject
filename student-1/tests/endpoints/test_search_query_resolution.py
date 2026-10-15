"""Offline checks for how the live search test picks its query (no running service needed).

These tests are not marked ``endpoint``: they drive the resolver through an in-memory
transport, so they run in every ``pytest`` and ``check.py`` invocation.
"""

from __future__ import annotations

from collections.abc import Callable

import httpx

from shared_testkit.endpoints import EndpointClient

from .search_query import DEFAULT_SEARCH_QUERY, resolve_search_query

GNAF_RELEASE = "60000000-0000-0000-0000-000000000101"
Handler = Callable[[httpx.Request], httpx.Response]


def _client(handler: Handler, calls: list[str]) -> EndpointClient:
    def recording(request: httpx.Request) -> httpx.Response:
        calls.append(f"{request.url.path}?{request.url.query.decode()}")
        return handler(request)

    return EndpointClient(
        "http://feature-1.test", transport=httpx.MockTransport(recording), connect_retries=0
    )


def _page(*items: dict[str, object]) -> httpx.Response:
    return httpx.Response(200, json={"items": list(items), "count": len(items)})


def _real_gnaf_stack(searchable: set[str]) -> Handler:
    """A stack whose accepted G-NAF replaced the seed: only ``searchable`` addresses match."""

    def handler(request: httpx.Request) -> httpx.Response:
        path, params = request.url.path, request.url.params
        if path.endswith("/properties/search"):
            query = params["q"]
            return _page({"matched_address": query}) if query in searchable else _page()
        if path.endswith("/dataset-releases"):
            if params["dataset_id"] == "gnaf-nsw":
                assert (params["status"], params["target_feature"]) == ("accepted", "feature-1")
                return _page({"id": GNAF_RELEASE})
            return _page()
        if path.endswith(f"/dataset-releases/{GNAF_RELEASE}/records"):
            assert params["limit"] == "10"
            return _page(
                {"address_display": None},
                {"address_display": "UNIT 3, 10 BOYCE STREET, GLEBE NSW 2037"},
                {"address_display": "12 BOYCE STREET, GLEBE NSW 2037"},
            )
        return httpx.Response(404, json={"code": "route_not_found"})

    return handler


def test_override_wins_without_touching_the_service() -> None:
    calls: list[str] = []

    chosen = resolve_search_query(
        _client(_real_gnaf_stack(set()), calls), override="  10 Boyce Street Glebe "
    )

    assert chosen.text == "10 Boyce Street Glebe"
    assert "override" in chosen.origin
    assert calls == []


def test_seeded_address_is_kept_while_it_still_matches() -> None:
    calls: list[str] = []

    chosen = resolve_search_query(_client(_real_gnaf_stack({DEFAULT_SEARCH_QUERY}), calls))

    assert chosen.text == DEFAULT_SEARCH_QUERY
    assert chosen.origin == "seeded demonstration address"
    assert len(calls) == 1


def test_real_gnaf_stack_uses_the_first_accepted_address_that_search_finds() -> None:
    calls: list[str] = []
    searchable = {"12 BOYCE STREET GLEBE NSW 2037"}

    chosen = resolve_search_query(_client(_real_gnaf_stack(searchable), calls))

    assert chosen.text == "12 BOYCE STREET GLEBE NSW 2037"
    assert chosen.origin == "accepted gnaf-nsw release record"
    # The unit address was tried first and rejected because search did not return it.
    tried = [call for call in calls if "/properties/search" in call]
    assert len(tried) == 3


def test_falls_back_to_the_default_when_no_accepted_address_matches() -> None:
    calls: list[str] = []

    chosen = resolve_search_query(_client(_real_gnaf_stack(set()), calls))

    assert chosen.text == DEFAULT_SEARCH_QUERY
    assert "no accepted address matched" in chosen.origin


def test_unavailable_release_listing_is_tolerated() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/properties/search"):
            return _page()
        return httpx.Response(503, json={"code": "dependency_unavailable"})

    chosen = resolve_search_query(_client(handler, calls))

    assert chosen.text == DEFAULT_SEARCH_QUERY
    assert any("dataset_id=fixture-property" in call for call in calls)
