"""Public accepted suburb search, detail and map-context routes.

The database service owns validation, the accepted-generation snapshot and the ETag. This
layer relays bytes, validators and Problem Details unchanged, so a 304 revalidation stays cheap.
"""

from __future__ import annotations

import re

import httpx
from flask import Blueprint, Response, request

from propertyscope_data_platform.clients import DataStoreClient
from propertyscope_data_platform.http_support import forward, forward_json_bytes, problem
from shared_contracts import REQUEST_ID_HEADER, TRACEPARENT_HEADER

_VALIDATOR_HEADERS = ("ETag", "Cache-Control")
# Validated here as well as in the database service: only a publisher cadid may become part of
# an internal path, so dot segments can never leave /suburbs/ with the internal credential.
_SUBURB_ID = re.compile(r"^[1-9][0-9]{0,11}$")


def _invalid_suburb_id() -> Response:
    return problem(422, "invalid_request", "suburb_id must be the publisher cadid: 1 to 12 digits")


def register_suburb_routes(
    api: Blueprint,
    store: DataStoreClient,
    *,
    base: str,
    internal: str,
) -> None:
    """Register the suburb-map spatial projection over the private database API."""

    @api.get(f"{base}/suburbs/search")
    def suburb_search() -> Response:
        return relay_cacheable(
            store.request(
                "GET", f"{internal}/suburbs/search", headers=request.headers, params=request.args
            )
        )

    @api.get(f"{base}/suburbs/<suburb_id>")
    def suburb_detail(suburb_id: str) -> Response:
        if not _SUBURB_ID.fullmatch(suburb_id):
            return _invalid_suburb_id()
        return relay_cacheable(
            store.request(
                "GET",
                f"{internal}/suburbs/{suburb_id}",
                headers=request.headers,
                params=request.args,
            )
        )

    @api.get(f"{base}/suburbs/<suburb_id>/map-context")
    def suburb_map_context(suburb_id: str) -> Response:
        if not _SUBURB_ID.fullmatch(suburb_id):
            return _invalid_suburb_id()
        return relay_cacheable(
            store.request(
                "GET",
                f"{internal}/suburbs/{suburb_id}/map-context",
                headers=request.headers,
                params=request.args,
            )
        )


def relay_cacheable(upstream: httpx.Response) -> Response:
    """Relay a JSON body or a 304 with its validators and correlation headers."""
    if upstream.status_code == 304:
        response = Response(status=304)
        for name in (*_VALIDATOR_HEADERS, REQUEST_ID_HEADER, TRACEPARENT_HEADER):
            if name in upstream.headers:
                response.headers[name] = upstream.headers[name]
        return response
    if upstream.status_code >= 400:
        return forward(upstream)
    response = forward_json_bytes(upstream)
    for name in _VALIDATOR_HEADERS:
        if name in upstream.headers:
            response.headers[name] = upstream.headers[name]
    return response
