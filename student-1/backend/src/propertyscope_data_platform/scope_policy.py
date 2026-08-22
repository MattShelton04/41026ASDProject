"""Run-scope resolution and validation independent of the HTTP layer."""

from __future__ import annotations

import copy
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from propertyscope_data_platform.release_builders import resolve_release_builder


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
    full_data_enabled: bool = False,
    psi_transport_enabled: bool = False,
) -> tuple[dict[str, Any] | None, ScopeProblem | None]:
    """Bound operator scope overrides and reject unavailable live transports."""
    if not isinstance(raw_scope, dict):
        return None, _invalid("Run scope must be a JSON object")
    if len(raw_scope) > 20:
        return None, _invalid("Run scope has too many fields")
    scope = dict(raw_scope)
    profile = scope.get("profile", "showcase")
    if profile not in {"test", "showcase", "full-data"}:
        return None, _invalid("Scope profile is not registered")
    scope["profile"] = profile
    bounded_scope = scope.get("release_scope", scope)
    if not isinstance(bounded_scope, dict):
        return None, _invalid("release_scope must be a JSON object")
    builder_key = job.get("release_builder_key") or {
        "bocsar-sparse": "crime-series",
        "gnaf-nsw": "property-snapshot",
        "property-fixture": "property-snapshot",
        "psi-sales": "property-sales",
        "schools-master": "school-points",
    }.get(str(job.get("import_profile_key")))
    builder = resolve_release_builder(str(builder_key), "1.0.0")
    maximum_records = bounded_scope.get("maximum_records")
    if (
        not isinstance(maximum_records, int)
        or isinstance(maximum_records, bool)
        or maximum_records < 1
        or maximum_records > builder.spec.max_rows
    ):
        return None, _invalid("maximum_records exceeds the product limit")
    if str(job.get("import_profile_key")) == "psi-sales":
        error = _validate_psi_scope(scope, bounded_scope)
        if error is not None:
            return None, error
    if run_mode == "full_refresh" and profile == "full-data" and not full_data_enabled:
        return None, ScopeProblem(
            422,
            "full_data_runtime_disabled",
            "Start the explicit full-data runtime before launching live acquisition",
        )
    import_profile = str(job.get("import_profile_key"))
    connected = import_profile in {
        "schools-master",
        "bocsar-sparse",
        "gnaf-nsw",
        "property-fixture",
    } or (import_profile == "psi-sales" and psi_transport_enabled)
    if run_mode == "full_refresh" and profile == "full-data" and not connected:
        return None, ScopeProblem(
            422,
            "live_transport_unavailable",
            "This source is catalogued but its live acquisition transport is not connected",
        )
    return scope, None


def resolve_registered_scope(job: Mapping[str, Any], raw_scope: Any, job_profiles: Any) -> Any:
    """Overlay bounded operator fields onto the declarative registered profile."""
    requested = {} if raw_scope is None else raw_scope
    if not isinstance(requested, dict):
        return requested
    profile_name = requested.get("profile")
    if profile_name is None and isinstance(job.get("scope_json"), dict):
        profile_name = job["scope_json"].get("profile")
    profile_name = profile_name or "showcase"
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
        defaults = registered.scope_profiles[str(profile_name)]
    except (KeyError, StopIteration, ValueError):
        return requested
    resolved = copy.deepcopy(defaults)
    for key, value in requested.items():
        if key == "release_scope" and isinstance(value, dict):
            nested = resolved.get(key, {})
            if isinstance(nested, dict):
                nested.update(value)
                resolved[key] = nested
            else:
                resolved[key] = value
        else:
            resolved[key] = value
    if "years" in requested:
        resolved.setdefault("weeks", [])
    if "years" in requested or "weeks" in requested:
        if "all_history" not in requested:
            resolved["all_history"] = False
        if "include_current_weekly" not in requested:
            resolved["include_current_weekly"] = False
    resolved["profile"] = profile_name
    return resolved


def _validate_psi_scope(
    scope: Mapping[str, Any], bounded_scope: Mapping[str, Any]
) -> ScopeProblem | None:
    years = scope.get("years")
    all_history = scope.get("all_history") is True
    weekly_only = isinstance(scope.get("weeks"), list) and bool(scope.get("weeks"))
    if (
        not all_history
        and not weekly_only
        and (not isinstance(years, list) or not years or len(years) > 100)
    ):
        return _invalid("PSI scope requires source years or complete history")
    checked_years: list[Any] = [] if all_history or not isinstance(years, list) else list(years)
    maximum_year = datetime.now(UTC).year + 1
    if any(not _valid_year(year, maximum_year) for year in checked_years):
        return _invalid("PSI source year is outside the range")
    if checked_years != sorted(set(checked_years)):
        return _invalid("PSI source years must be unique and sorted")
    weeks = scope.get("weeks", [])
    if not isinstance(weeks, list) or len(weeks) > 1000:
        return _invalid("PSI weekly partitions are invalid")
    try:
        parsed_weeks = [date.fromisoformat(value) for value in weeks]
    except (TypeError, ValueError):
        return _invalid("PSI weeks must use ISO dates")
    if parsed_weeks != sorted(set(parsed_weeks)):
        return _invalid("PSI weeks must be unique and sorted")
    release_years = bounded_scope.get("years")
    if not isinstance(release_years, list) or not release_years or len(release_years) > 100:
        return _invalid("PSI release scope requires explicit source years")
    invalid_year = any(not _valid_year(year, maximum_year) for year in release_years)
    if invalid_year or release_years != sorted(set(release_years)):
        return _invalid("PSI release years must be unique, sorted, and in range")
    return None


def _valid_year(value: Any, maximum_year: int) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and 1990 <= value <= maximum_year


def _invalid(detail: str) -> ScopeProblem:
    return ScopeProblem(422, "invalid_scope", detail)
