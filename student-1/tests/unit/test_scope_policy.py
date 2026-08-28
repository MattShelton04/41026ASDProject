from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from propertyscope_data_platform.configuration import load_job_profiles
from propertyscope_data_platform.scope_policy import (
    psi_scope_is_cached,
    resolve_registered_scope,
    validate_job_scope,
)

ROOT = Path(__file__).resolve().parents[2]
PSI_JOB = {
    "profile_key": "nsw-psi-sales-year",
    "import_profile_key": "psi-sales",
    "release_builder_key": "property-sales",
    "scope_json": {"profile": "full-data", "all_records": True},
}


def test_registered_scope_ignores_operator_attempts_to_reduce_the_import() -> None:
    profiles = load_job_profiles(ROOT / "config" / "job-profiles")

    resolved = resolve_registered_scope(
        PSI_JOB,
        {
            "profile": "full-data",
            "all_records": True,
            "years": [2025],
            "release_scope": {"years": [2025], "maximum_records": 500},
        },
        profiles,
    )
    defaults = profiles.get_profile("nsw-psi-sales-year").scope

    assert "years" not in resolved
    assert resolved["all_history"] is True
    assert resolved["include_current_weekly"] is True
    assert resolved["release_scope"]["maximum_records"] == 250000
    assert defaults["all_history"] is True


@pytest.mark.parametrize(
    ("scope", "detail"),
    [
        (None, "JSON object"),
        ({"profile": "unknown"}, "all records"),
        (
            {
                "profile": "full-data",
                "all_records": True,
                "maximum_records": 1,
                "release_scope": {"maximum_records": 10, "years": [2025]},
            },
            "subset selector",
        ),
        (
            {
                "profile": "full-data",
                "all_records": True,
                "years": [2025, 2024],
                "release_scope": {"years": [2024, 2025], "maximum_records": 10},
            },
            "subset selector",
        ),
        (
            {
                "profile": "full-data",
                "all_records": True,
                "weeks": ["not-a-date"],
                "release_scope": {"years": [2025], "maximum_records": 10},
            },
            "subset selector",
        ),
    ],
)
def test_scope_validation_returns_stable_structured_problems(scope: object, detail: str) -> None:
    result, error = validate_job_scope(PSI_JOB, scope, run_mode="full_refresh")

    assert result is None
    assert error is not None
    assert error.status == 422
    assert error.code == "invalid_scope"
    assert detail in error.detail


def test_live_scope_policy_connects_registered_sources_and_rejects_unknown_transport() -> None:
    scope = {
        "profile": "full-data",
        "all_records": True,
        "all_history": True,
        "include_current_weekly": True,
        "release_scope": {"years": [2025], "maximum_records": 10},
    }

    unknown_job = {**PSI_JOB, "import_profile_key": "spatial-features"}
    _, transport_error = validate_job_scope(
        unknown_job,
        {"profile": "full-data", "all_records": True, "release_scope": {"maximum_records": 10}},
        run_mode="full_refresh",
    )
    resolved, error = validate_job_scope(
        PSI_JOB,
        scope,
        run_mode="full_refresh",
    )

    assert transport_error is not None and transport_error.code == "live_transport_unavailable"
    assert error is None
    assert resolved == scope


def test_psi_cache_policy_accounts_for_current_weekly_partitions() -> None:
    scope = {
        "profile": "full-data",
        "years": [2024],
        "include_current_weekly": True,
    }

    assert psi_scope_is_cached(
        PSI_JOB,
        scope,
        cached_years=(2024,),
        cached_weeks=("2025-01-06", "2025-01-13"),
        as_of=date(2025, 1, 15),
    )
    assert not psi_scope_is_cached(
        PSI_JOB,
        scope,
        cached_years=(2024,),
        cached_weeks=("2025-01-06",),
        as_of=date(2025, 1, 15),
    )
