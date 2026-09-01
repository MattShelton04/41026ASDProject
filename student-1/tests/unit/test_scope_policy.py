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
    assert "release_scope" not in resolved
    assert defaults["all_history"] is True


def test_psi_year_range_resolves_to_exact_completed_publisher_partitions() -> None:
    profiles = load_job_profiles(ROOT / "config" / "job-profiles")

    resolved = resolve_registered_scope(
        PSI_JOB,
        {"profile": "psi-year-range", "start_year": 2022, "end_year": 2024},
        profiles,
    )
    validated, error = validate_job_scope(
        PSI_JOB,
        resolved,
        run_mode="full_refresh",
        as_of=date(2025, 8, 1),
    )

    assert error is None
    assert validated == {
        "profile": "psi-year-range",
        "start_year": 2022,
        "end_year": 2024,
        "years": [2022, 2023, 2024],
        "all_records": True,
        "all_history": False,
        "include_current_weekly": False,
        "complete": False,
        "coverage_status": "partial",
        "limitations": [
            "This candidate contains only the selected completed PSI annual partitions and "
            "cannot replace the accepted complete sales-history generation."
        ],
    }


@pytest.mark.parametrize(
    "requested",
    (
        {"profile": "psi-year-range", "start_year": 1989, "end_year": 2024},
        {"profile": "psi-year-range", "start_year": 2024, "end_year": 2025},
        {"profile": "psi-year-range", "start_year": 2024, "end_year": 2023},
        {"profile": "psi-year-range", "start_year": True, "end_year": 2024},
    ),
)
def test_psi_year_range_rejects_invalid_or_unfinished_archive_years(
    requested: dict[str, object],
) -> None:
    profiles = load_job_profiles(ROOT / "config" / "job-profiles")
    resolved = resolve_registered_scope(PSI_JOB, requested, profiles)

    value, error = validate_job_scope(
        PSI_JOB,
        resolved,
        run_mode="full_refresh",
        as_of=date(2025, 8, 1),
    )

    assert value is None
    assert error is not None and error.code == "invalid_scope"


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
    }

    unknown_job = {**PSI_JOB, "import_profile_key": "spatial-features"}
    _, transport_error = validate_job_scope(
        unknown_job,
        {"profile": "full-data", "all_records": True},
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


def test_psi_cache_policy_supports_a_partial_archive_year_range() -> None:
    scope = {
        "profile": "psi-year-range",
        "years": [2022, 2023],
        "include_current_weekly": False,
    }

    assert psi_scope_is_cached(
        PSI_JOB,
        scope,
        cached_years=(2022, 2023),
        cached_weeks=(),
        as_of=date(2025, 1, 15),
    )
