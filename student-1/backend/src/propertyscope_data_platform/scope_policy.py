"""Run-scope resolution and validation independent of the HTTP layer."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from propertyscope_data_platform.acquisition_scope import complete_scope_error


@dataclass(frozen=True, slots=True)
class ScopeProblem:
    """A stable validation failure which an HTTP adapter can render."""

    status: int
    code: str
    detail: str


def psi_scope_is_cached(
    job: Mapping[str, Any],
    scope: Mapping[str, Any],
    *,
    cached_years: tuple[int, ...],
    cached_weeks: tuple[str, ...],
    as_of: date | None = None,
) -> bool:
    """Return whether every requested PSI partition is locally cached."""
    if scope.get("profile") != "full-data" or str(job.get("import_profile_key")) != "psi-sales":
        return False
    today = as_of or datetime.now(UTC).date()
    required_years = set(scope.get("years", []))
    if scope.get("all_history") is True:
        required_years.update(range(1990, today.year))
    required_weeks = set(scope.get("weeks", []))
    if scope.get("include_current_weekly") is True:
        cursor = date(today.year, 1, 1)
        cursor += timedelta(days=(7 - cursor.weekday()) % 7)
        while cursor <= today:
            required_weeks.add(cursor.isoformat())
            cursor += timedelta(days=7)
    return (
        bool(required_years or required_weeks)
        and required_years.issubset(cached_years)
        and required_weeks.issubset(cached_weeks)
    )


def validate_job_scope(
    job: Mapping[str, Any],
    raw_scope: Any,
    *,
    run_mode: str,
) -> tuple[dict[str, Any] | None, ScopeProblem | None]:
    """Validate complete-source acquisition and reject unavailable live transports."""
    if not isinstance(raw_scope, dict):
        return None, _invalid("Run scope must be a JSON object")
    if len(raw_scope) > 20:
        return None, _invalid("Run scope has too many fields")
    scope = dict(raw_scope)
    import_profile = str(job.get("import_profile_key"))
    completeness_error = complete_scope_error(import_profile, scope)
    if completeness_error is not None:
        return None, _invalid(completeness_error)
    connected = import_profile in {
        "schools-master",
        "bocsar-sparse",
        "gnaf-nsw",
        "property-fixture",
        "psi-sales",
    }
    if run_mode == "full_refresh" and not connected:
        return None, ScopeProblem(
            422,
            "live_transport_unavailable",
            "This source is catalogued but its live acquisition transport is not connected",
        )
    return scope, None


def resolve_registered_scope(job: Mapping[str, Any], raw_scope: Any, job_profiles: Any) -> Any:
    """Resolve the immutable declarative complete-source scope for a job."""
    requested = {} if raw_scope is None else raw_scope
    if not isinstance(requested, dict):
        return requested
    try:
        profile_key = job.get("profile_key")
        if profile_key is None:
            import_key = str(job.get("import_profile_key"))
            profile_key = next(
                key
                for key in job_profiles
                if job_profiles.get_profile(key).import_profile.key == import_key
            )
        registered = job_profiles.get_profile(str(profile_key))
        defaults = registered.scope
    except (KeyError, StopIteration, ValueError):
        return requested
    resolved = dict(defaults)
    resolved["profile"] = "full-data"
    return resolved


def _invalid(detail: str) -> ScopeProblem:
    return ScopeProblem(422, "invalid_scope", detail)
