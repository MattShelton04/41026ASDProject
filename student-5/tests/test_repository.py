"""Repository behaviour and ownership tests."""

from __future__ import annotations

import sqlite3

import pytest
from propertyscope_buyer_store.repository import BuyerStore, ConcurrentUpdateError

OWNER = "release0-demo-owner"
CASE_1 = "b5000000-0000-4000-8000-000000000001"
CASE_2 = "b5000000-0000-4000-8000-000000000002"
PROPERTY_1 = "c5000000-0000-4000-8000-000000000001"


def test_owner_scope_is_applied_to_cases_and_children(store: BuyerStore) -> None:
    store.create_case(
        "another-owner",
        {
            "name": "Private case",
            "preferences_json": "{}",
            "budget_min_aud": None,
            "budget_max_aud": None,
            "target_suburbs_json": "[]",
            "status": "active",
        },
    )
    assert store.list_cases(OWNER, page=1, page_size=100)["total"] == 10
    assert store.get_case("another-owner", CASE_1) is None
    assert store.get_property("another-owner", CASE_1, PROPERTY_1) is None


def test_case_crud_and_optimistic_version(store: BuyerStore) -> None:
    created = store.create_case(
        OWNER,
        {
            "name": "New buyer workspace",
            "preferences_json": '{"beds":2}',
            "budget_min_aud": 700000,
            "budget_max_aud": 900000,
            "target_suburbs_json": '[{"locality":"SYDNEY","state":"NSW"}]',
            "status": "active",
        },
    )
    updated = store.update_case(
        OWNER,
        created["id"],
        {"status": "paused"},
        expected_version=1,
    )
    assert updated["status"] == "paused"
    assert updated["version"] == 2
    with pytest.raises(ConcurrentUpdateError):
        store.update_case(OWNER, created["id"], {"status": "closed"}, expected_version=1)
    assert store.delete_case(OWNER, created["id"])
    assert not store.delete_case(OWNER, created["id"])


def test_property_can_move_arbitrarily_and_be_reopened(store: BuyerStore) -> None:
    closed = store.update_property(
        OWNER,
        CASE_1,
        PROPERTY_1,
        {"journey_stage": "Closed"},
        expected_version=1,
    )
    reopened = store.update_property(
        OWNER,
        CASE_1,
        PROPERTY_1,
        {"journey_stage": "Shortlisted"},
        expected_version=closed["version"],
    )
    assert reopened["journey_stage"] == "Shortlisted"


def test_property_deletion_preserves_notes_and_tasks_with_null_link(store: BuyerStore) -> None:
    notes_before = store.list_notes(OWNER, CASE_1, page=1, page_size=100)["items"]
    tasks_before = store.list_tasks(OWNER, CASE_1, page=1, page_size=100)["items"]
    linked_before = {
        item["id"]: item
        for item in [*notes_before, *tasks_before]
        if item["case_property_id"] == PROPERTY_1
    }
    assert store.delete_property(OWNER, CASE_1, PROPERTY_1)
    notes_after = store.list_notes(OWNER, CASE_1, page=1, page_size=100)["items"]
    tasks_after = store.list_tasks(OWNER, CASE_1, page=1, page_size=100)["items"]
    after_by_id = {item["id"]: item for item in [*notes_after, *tasks_after]}
    assert len(notes_after) == len(notes_before)
    assert len(tasks_after) == len(tasks_before)
    assert all(item["case_property_id"] is None for item in notes_after)
    assert all(item["case_property_id"] is None for item in tasks_after)
    assert linked_before
    for record_id, before in linked_before.items():
        after = after_by_id[record_id]
        assert after["buyer_case_id"] == before["buyer_case_id"] == CASE_1
        assert after["version"] == before["version"] + 1
        assert after["updated_at"] == "2026-09-03T10:00:00Z"


def test_related_note_or_task_must_use_property_from_same_case(store: BuyerStore) -> None:
    values = {"case_property_id": PROPERTY_1, "content": "Wrong case relationship"}
    with pytest.raises(sqlite3.IntegrityError, match="case_property_case_mismatch"):
        store.create_note(OWNER, CASE_2, values)


def test_case_deletion_cascades_all_children(store: BuyerStore) -> None:
    assert store.delete_case(OWNER, CASE_1)
    connection = store.connect()
    counts = {
        table: connection.execute(
            f"SELECT COUNT(*) FROM {table} WHERE buyer_case_id = ?", (CASE_1,)
        ).fetchone()[0]
        for table in ("case_property", "case_note", "case_task")
    }
    connection.close()
    assert counts == {"case_property": 0, "case_note": 0, "case_task": 0}
