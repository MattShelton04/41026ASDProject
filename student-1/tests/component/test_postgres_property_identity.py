"""Accepted-generation visibility using an isolated, fully migrated PostgreSQL database.

Requires PROPERTYSCOPE_TEST_POSTGRES_URL for a disposable administrator server.
Never point it at the retained application database.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator, Sequence
from typing import Any

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import make_conninfo
from psycopg.rows import dict_row

from propertyscope_data_store._property_reads import _CanonicalPropertyReads
from propertyscope_data_store.errors import NotFoundError
from propertyscope_data_store.migrations import migrate

ADMIN_URL = os.getenv("PROPERTYSCOPE_TEST_POSTGRES_URL", "").strip()
pytestmark = pytest.mark.skipif(not ADMIN_URL, reason="requires disposable PostgreSQL test URL")


class ReadOwner:
    def __init__(self, connection: psycopg.Connection[dict[str, Any]]) -> None:
        self.connection = connection

    def _fetch_one(self, query: str, params: Sequence[Any]) -> dict[str, Any] | None:
        return self.connection.execute(query, params).fetchone()

    def _fetch_all(self, query: str, params: Sequence[Any]) -> list[dict[str, Any]]:
        return self.connection.execute(query, params).fetchall()

    def _required(self, query: str, params: Sequence[Any]) -> dict[str, Any]:
        row = self._fetch_one(query, params)
        if row is None:
            raise NotFoundError("record does not exist")
        return row


@pytest.fixture
def identity_database() -> Iterator[psycopg.Connection[dict[str, Any]]]:
    database = f"propertyscope_identity_{uuid.uuid4().hex}"
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database)))
    try:
        with psycopg.connect(
            make_conninfo(ADMIN_URL, dbname=database), row_factory=dict_row
        ) as conn:
            migrate(conn)
            yield conn
    finally:
        with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
            admin.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(database)))


def test_gnaf_anchor_cannot_outlive_accepted_identity(
    identity_database: psycopg.Connection[dict[str, Any]],
) -> None:
    connection = identity_database
    reads = _CanonicalPropertyReads(ReadOwner(connection))
    property_ref = uuid.UUID("a0000000-0000-0000-0000-000000000001")
    release_id = uuid.UUID("60000000-0000-0000-0000-000000000001")
    connection.execute(
        "UPDATE registry.property_identifier SET scheme='gnaf_pid' WHERE property_ref=%s",
        (property_ref,),
    )
    connection.execute(
        """UPDATE registry.property SET address_display='999 Stale Anchor Street',
        address_search='999 stale anchor street',locality='STALE LOCALITY'
        WHERE property_ref=%s""",
        (property_ref,),
    )
    connection.execute(
        """UPDATE warehouse.gnaf_address SET address_display='123 Current Lane, Sydney NSW 2000',
        locality='SYDNEY',published=true WHERE property_ref=%s""",
        (property_ref,),
    )
    assert reads.property_snapshot(property_ref)["property"]["locality"] == "SYDNEY"
    assert reads.property_seifa(property_ref)["locality"] == "SYDNEY"
    assert reads.property_coverage(property_ref)
    assert reads.property_sale_history(property_ref, limit=10)["count"] >= 0
    assert not reads.search_properties("999 stale anchor", state="NSW", limit=25).items
    assert any(
        item["property_ref"] == property_ref
        for item in reads.search_properties("123 current lane", state="NSW", limit=25).items
    )

    # Keep the anchor's source and aliases accepted under the existing pointer. A
    # withdrawn warehouse identity must still never fall back to its stored snapshot.
    connection.execute(
        "UPDATE warehouse.gnaf_address SET published=false WHERE property_ref=%s",
        (property_ref,),
    )
    assert not reads.search_properties("11 example st", state="NSW", limit=25).items
    for read in (
        reads.property_snapshot,
        reads.property_coverage,
        reads.property_seifa,
        lambda ref: reads.property_sale_history(ref, limit=10),
    ):
        with pytest.raises(NotFoundError):
            read(property_ref)
    assert reads._seifa_coverage(property_ref) is None

    # A later accepted generation can reintroduce the same stable reference with
    # changed fields; its canonical data wins over the unchanged registry anchor.
    next_release = uuid.uuid4()
    connection.execute(
        "UPDATE ops.dataset_release SET status='superseded' WHERE id=%s", (release_id,)
    )
    connection.execute(
        """INSERT INTO ops.dataset_release SELECT (jsonb_populate_record(
            NULL::ops.dataset_release,to_jsonb(release) || jsonb_build_object(
                'id',%s::text,'release_version','identity-switch-test','status','accepted'
            ))).* FROM ops.dataset_release release WHERE id=%s""",
        (next_release, release_id),
    )
    connection.execute(
        """INSERT INTO warehouse.gnaf_address SELECT (jsonb_populate_record(
            NULL::warehouse.gnaf_address,to_jsonb(address) || jsonb_build_object(
                'dataset_release_id',%s::text,'locality','PARRAMATTA',
                'address_display','456 Replacement Road, Parramatta NSW 2150','published',true
            ))).* FROM warehouse.gnaf_address address WHERE property_ref=%s""",
        (next_release, property_ref),
    )
    connection.execute(
        "UPDATE serving.accepted_generation SET dataset_release_id=%s WHERE dataset_release_id=%s",
        (next_release, release_id),
    )
    assert reads.property_snapshot(property_ref)["property"]["locality"] == "PARRAMATTA"
    assert reads.property_seifa(property_ref)["locality"] == "PARRAMATTA"
    assert not reads.search_properties("123 current lane", state="NSW", limit=25).items
    assert not reads.search_properties("999 stale anchor", state="NSW", limit=25).items


def test_non_gnaf_registry_identity_keeps_compatibility_reads(
    identity_database: psycopg.Connection[dict[str, Any]],
) -> None:
    property_ref = uuid.UUID("a0000000-0000-0000-0000-000000000011")
    identity_database.execute(
        "UPDATE registry.property_identifier SET scheme='fixture_pid' WHERE property_ref=%s",
        (property_ref,),
    )
    reads = _CanonicalPropertyReads(ReadOwner(identity_database))
    assert reads.property_snapshot(property_ref)["property"]["property_ref"] == property_ref
    assert reads.property_seifa(property_ref)["locality"] == "SYDNEY"
    assert reads.property_coverage(property_ref)
    assert reads.property_sale_history(property_ref, limit=10)["count"] >= 0
    assert any(
        item["property_ref"] == property_ref
        for item in reads.search_properties("21 example", state="NSW", limit=25).items
    )
