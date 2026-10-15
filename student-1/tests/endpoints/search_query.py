"""Choose the property-search query for the live endpoint test from the stack's own data.

The seeded demonstration address exists only while the seed is the accepted address data. A
stack that published real G-NAF replaces it, so the happy-path test would otherwise fail for a
reason unrelated to the endpoint. See ``student-1/README.md`` (Endpoint tests).
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

from shared_testkit.endpoints import EndpointClient

API = "/api/data-platform/v1"
SEARCH_PATH = f"{API}/properties/search"
SEARCH_QUERY_ENV = "PROPERTYSCOPE_F1_ENDPOINT_SEARCH_QUERY"
# Present in every fresh database through the showcase seed and the fixture-property job.
DEFAULT_SEARCH_QUERY = "11 Example Street"
# Address datasets that property search serves, in the order search itself prefers them.
ADDRESS_DATASETS = ("gnaf-nsw", "fixture-property")
DISCOVERY_SAMPLE = 10


@dataclass(frozen=True)
class SearchQuery:
    """The address the happy-path search uses and how it was chosen (for the JUnit report)."""

    text: str
    origin: str


def _has_match(client: EndpointClient, query: str) -> bool:
    response = client.get(SEARCH_PATH, params={"q": query, "state": "NSW", "limit": 1})
    if response.status_code != 200:
        return False
    items = response.json().get("items")
    return isinstance(items, list) and bool(items)


def _accepted_addresses(client: EndpointClient) -> Iterator[tuple[str, str]]:
    """Yield ``(address, dataset_id)`` from the bounded preview of accepted address releases."""
    for dataset_id in ADDRESS_DATASETS:
        releases = client.get(
            f"{API}/dataset-releases",
            params={
                "status": "accepted",
                "dataset_id": dataset_id,
                "target_feature": "feature-1",
                "view": "summary",
                "limit": 1,
            },
        )
        if releases.status_code != 200:
            continue
        for release in releases.json().get("items", [])[:1]:
            records = client.get(
                f"{API}/dataset-releases/{release['id']}/records",
                params={"limit": DISCOVERY_SAMPLE},
            )
            if records.status_code != 200:
                continue
            for record in records.json().get("items", []):
                display = record.get("address_display") if isinstance(record, dict) else None
                if not isinstance(display, str):
                    continue
                # Search is punctuation-neutral; drop commas so every term is a plain word.
                address = " ".join(display.replace(",", " ").split())
                if 2 <= len(address) <= 200:
                    yield address, dataset_id


def resolve_search_query(
    client: EndpointClient, *, override: str = "", default: str = DEFAULT_SEARCH_QUERY
) -> SearchQuery:
    """Choose an address that the running service's accepted data really contains.

    An explicit override always wins, so a stack can pin a known address. Otherwise the seeded
    demonstration address is used while it still matches. When accepted G-NAF has replaced the
    seed, an address is read from the accepted release's bounded record preview (a different
    endpoint from search) and must itself be found by search. If nothing is found, the default
    is returned so the happy-path test fails with a message naming the query and its origin.
    """
    if override.strip():
        return SearchQuery(override.strip(), f"{SEARCH_QUERY_ENV} override")
    if _has_match(client, default):
        return SearchQuery(default, "seeded demonstration address")
    for address, dataset_id in _accepted_addresses(client):
        if _has_match(client, address):
            return SearchQuery(address, f"accepted {dataset_id} release record")
    return SearchQuery(default, "seeded demonstration address (no accepted address matched)")
