"""Production databases purge the seeded demonstration baseline; local stacks keep it."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import pytest

from propertyscope_data_store.app import create_app
from propertyscope_data_store.configuration import StoreSettings
from propertyscope_data_store.demonstration_data import purge_script
from propertyscope_data_store.repository import PropertyScopeStore


class _RecordingStore:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def initialize(self, **options: Any) -> str:
        self.calls.append(options)
        return "fingerprint"


def _settings(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, value: str | None) -> StoreSettings:
    monkeypatch.setenv("PROPERTYSCOPE_DATABASE_URL", "postgresql://database")
    monkeypatch.setenv("PROPERTYSCOPE_ARTIFACT_ROOT", str(tmp_path))
    if value is None:
        monkeypatch.delenv("PROPERTYSCOPE_DEMONSTRATION_DATA", raising=False)
    else:
        monkeypatch.setenv("PROPERTYSCOPE_DEMONSTRATION_DATA", value)
    return StoreSettings.from_environment()


@pytest.mark.parametrize(("value", "expected"), [(None, True), ("true", True), ("false", False)])
def test_demonstration_data_defaults_on_and_production_turns_it_off(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, value: str | None, expected: bool
) -> None:
    assert _settings(monkeypatch, tmp_path, value).demonstration_data is expected


@pytest.mark.parametrize("value", ["true", "false"])
def test_the_app_passes_the_setting_to_the_migration_pass(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, value: str
) -> None:
    store = _RecordingStore()

    create_app(_settings(monkeypatch, tmp_path, value), store=cast(PropertyScopeStore, store))

    assert store.calls == [{"demonstration_data": value == "true"}]


def test_the_operator_script_is_one_transaction_that_never_touches_the_job_catalogue() -> None:
    script = purge_script()

    assert script.startswith("BEGIN;\n") and script.endswith("COMMIT;\n")
    assert "DELETE FROM ops.ingestion_run" in script
    assert "ops.source_definition" not in script
    assert "DELETE FROM ops.job_definition" not in script
