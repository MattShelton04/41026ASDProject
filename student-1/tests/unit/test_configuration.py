from __future__ import annotations

from pathlib import Path

import pytest

from propertyscope_data_platform.configuration import (
    ConfigurationError,
    load_adapter_register,
    load_job_profiles,
    load_source_register,
    validate_job_profile,
)

ROOT = Path(__file__).resolve().parents[2]


def test_checked_in_profiles_load_in_stable_order() -> None:
    registry = load_job_profiles(ROOT / "config" / "job-profiles")
    assert registry.keys() == ("bocsar-crime-quarterly", "fixture-property-full")
    fixture = registry.get_profile("fixture-property-full")
    assert fixture.limits.max_parallelism == 1
    assert set(fixture.scope_profiles) == {"test", "showcase"}


def test_unknown_profile_fails_closed() -> None:
    registry = load_job_profiles(ROOT / "config" / "job-profiles")
    with pytest.raises(ConfigurationError, match="unknown registered key"):
        registry.get_profile("arbitrary.module.Class")


def test_checked_in_source_register_is_bounded_and_allowlisted() -> None:
    registry = load_source_register(ROOT / "config" / "source-register.yaml")
    assert len(registry) == 5
    assert registry.get_profile("bocsar-crime").adapter_key == "bocsar-bulk"


def test_job_profiles_fit_registered_adapter_capabilities() -> None:
    profiles = load_job_profiles(ROOT / "config" / "job-profiles")
    sources = load_source_register(ROOT / "config" / "source-register.yaml")
    adapters = load_adapter_register(ROOT / "config" / "adapter-register.yaml")
    for key in profiles:
        validate_job_profile(profiles.get_profile(key), sources=sources, adapters=adapters)
