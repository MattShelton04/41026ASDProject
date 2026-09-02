from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from propertyscope_data_platform.configuration import load_job_profiles
from propertyscope_data_store.configuration import StoreSettings
from propertyscope_data_store.runtime_registry import (
    RuntimeRegistryError,
    load_runtime_registry,
)

FEATURE_ROOT = Path(__file__).resolve().parents[2]


def _profile(
    key: str,
    *,
    adapter_version: str = "1.0.0",
    builder_version: str = "2.0.0",
) -> dict[str, object]:
    return {
        "schema_version": "propertyscope.job-profile.v1",
        "key": key,
        "version": "1.0.0",
        "adapter": {"key": "fixture-snapshot", "version": adapter_version},
        "release_builder": {"key": "property-snapshot", "version": builder_version},
        "import_profile": {"key": "property-fixture", "version": "1.0.0"},
        "quality_policy": "property-fixture.v1",
    }


def test_checked_in_profiles_form_one_stable_runtime_registry() -> None:
    registry = load_runtime_registry(FEATURE_ROOT / "config" / "job-profiles")

    assert registry.keys() == (
        "abs-seifa-2021-sal-nsw",
        "bocsar-crime-quarterly",
        "fixture-property-full",
        "gnaf-nsw-address-registry",
        "nsw-government-schools-master",
        "nsw-psi-sales-year",
    )
    fixture = registry.profile("fixture-property-full")
    assert fixture.adapter.version == "1.0.0"
    assert fixture.release_builder.version == "3.0.0"
    assert fixture.import_profile.version == "1.0.0"
    assert fixture.quality_policy.key == "property-fixture.v1"
    assert fixture.quality_policy.version == "1.0.0"
    assert registry.component_version("release_builder", "property-sales") == "4.0.0"
    assert registry.component_version("release_builder", "seifa-area") == "1.0.0"


def test_backend_and_datastore_project_the_same_declarative_runtime_boundary() -> None:
    profile_root = FEATURE_ROOT / "config" / "job-profiles"
    datastore = load_runtime_registry(profile_root)
    backend = load_job_profiles(profile_root)

    assert datastore.keys() == backend.keys()
    for key in datastore:
        persisted = datastore.profile(key)
        executable = backend.get_profile(key)
        assert (persisted.key, persisted.version) == (executable.key, executable.version)
        assert (persisted.adapter.key, persisted.adapter.version) == (
            executable.adapter.key,
            executable.adapter.version,
        )
        assert (persisted.release_builder.key, persisted.release_builder.version) == (
            executable.release_builder.key,
            executable.release_builder.version,
        )
        assert (persisted.import_profile.key, persisted.import_profile.version) == (
            executable.import_profile.key,
            executable.import_profile.version,
        )
        assert persisted.quality_policy.key == executable.quality_policy
        assert persisted.quality_policy.key.endswith(
            f".v{persisted.quality_policy.version.partition('.')[0]}"
        )


def test_store_settings_exposes_explicit_runtime_profile_boundary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PROPERTYSCOPE_DATABASE_URL", "postgresql://database")
    monkeypatch.setenv("PROPERTYSCOPE_RUNTIME_PROFILE_ROOT", str(tmp_path))

    settings = StoreSettings.from_environment()

    assert settings.runtime_profile_root == tmp_path.resolve()


def test_cross_profile_component_version_conflict_fails_closed(tmp_path: Path) -> None:
    (tmp_path / "one.yaml").write_text(yaml.safe_dump(_profile("profile-one")), encoding="utf-8")
    (tmp_path / "two.yaml").write_text(
        yaml.safe_dump(_profile("profile-two", adapter_version="2.0.0")),
        encoding="utf-8",
    )

    with pytest.raises(
        RuntimeRegistryError,
        match=r"conflicting adapter versions for fixture-snapshot: 1\.0\.0 and 2\.0\.0",
    ):
        load_runtime_registry(tmp_path)


def test_duplicate_profile_key_fails_closed(tmp_path: Path) -> None:
    for filename in ("one.yaml", "two.yaml"):
        (tmp_path / filename).write_text(
            yaml.safe_dump(_profile("duplicate-profile")), encoding="utf-8"
        )

    with pytest.raises(RuntimeRegistryError, match="duplicate runtime profile"):
        load_runtime_registry(tmp_path)


@pytest.mark.parametrize(
    "payload",
    (
        [],
        {"schema_version": "propertyscope.job-profile.v2"},
        _profile("invalid profile key"),
    ),
)
def test_malformed_runtime_profile_fails_closed(tmp_path: Path, payload: object) -> None:
    path = tmp_path / "profile.yaml"
    path.write_text(yaml.safe_dump(payload), encoding="utf-8")

    with pytest.raises(RuntimeRegistryError, match="invalid runtime profile"):
        load_runtime_registry(path)


def test_empty_runtime_profile_directory_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(RuntimeRegistryError, match="no runtime profiles found"):
        load_runtime_registry(tmp_path)


def test_unknown_profile_and_component_fail_closed() -> None:
    registry = load_runtime_registry(FEATURE_ROOT / "config" / "job-profiles")

    with pytest.raises(RuntimeRegistryError, match="unknown runtime profile"):
        registry.profile("not-registered")
    with pytest.raises(RuntimeRegistryError, match="unknown registered adapter"):
        registry.component_version("adapter", "not-registered")
