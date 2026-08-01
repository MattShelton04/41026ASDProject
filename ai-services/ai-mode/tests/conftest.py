"""Deterministic AI-mode component test fixtures."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from flask import Flask

from agent_core import ProviderHealth
from ai_mode import create_app
from ai_mode.persistence import SQLiteRunStore
from ai_mode.services import AppServices
from shared_testkit import ScriptedLLMProvider


class FixedClock:
    def now(self) -> datetime:
        return datetime(2026, 8, 1, 0, 0, tzinfo=UTC)


class FixedIds:
    def __init__(self) -> None:
        self.value = uuid4()

    def new(self) -> UUID:
        return self.value


class CapturingQueue:
    def __init__(self) -> None:
        self.run_ids: list[UUID] = []

    def enqueue(self, run_id: UUID) -> None:
        self.run_ids.append(run_id)


@pytest.fixture
def app_services(tmp_path: Path) -> AppServices:
    store = SQLiteRunStore(tmp_path / "agent-state.sqlite3")
    store.initialize()
    return AppServices(
        store=store,
        provider=ScriptedLLMProvider(
            [], health=ProviderHealth(reachable=True, detail="test provider ready")
        ),
        queue=CapturingQueue(),
        clock=FixedClock(),
        ids=FixedIds(),
    )


@pytest.fixture
def app(app_services: AppServices) -> Flask:
    application = create_app(services=app_services)
    application.config.update(TESTING=True)
    return application
