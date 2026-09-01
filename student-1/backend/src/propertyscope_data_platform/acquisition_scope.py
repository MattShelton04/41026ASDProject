"""Complete-source acquisition scope invariants shared by config and HTTP policy."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

_COMMON_FIELDS = frozenset({"profile", "all_records"})
_PROFILE_FIELDS = {
    "bocsar-sparse": frozenset({"geography_kinds"}),
    "gnaf-nsw": frozenset({"state"}),
    "psi-sales": frozenset({"all_history", "include_current_weekly"}),
}
_PSI_YEAR_RANGE_FIELDS = frozenset(
    {
        "profile",
        "all_records",
        "start_year",
        "end_year",
        "years",
        "all_history",
        "include_current_weekly",
        "complete",
        "coverage_status",
        "limitations",
    }
)
PSI_YEAR_RANGE_PROFILE = "psi-year-range"
PSI_MINIMUM_YEAR = 1990
PSI_PARTIAL_LIMITATION = (
    "This candidate contains only the selected completed PSI annual partitions and cannot "
    "replace the accepted complete sales-history generation."
)


def complete_scope_error(import_profile: str, scope: Mapping[str, Any]) -> str | None:
    """Return why a registered acquisition scope is not a complete-source scope."""
    if scope.get("profile") != "full-data" or scope.get("all_records") is not True:
        return "acquisition scope must request all records from the complete registered source"
    unexpected = set(scope) - _COMMON_FIELDS - _PROFILE_FIELDS.get(import_profile, frozenset())
    if unexpected:
        fields = ", ".join(sorted(unexpected))
        return f"acquisition scope contains subset selector fields: {fields}"
    if import_profile == "bocsar-sparse" and tuple(scope.get("geography_kinds", ())) != (
        "postcode",
        "suburb",
    ):
        return "BOCSAR complete acquisition must include postcode and suburb geography series"
    if import_profile == "gnaf-nsw" and scope.get("state") != "NSW":
        return "G-NAF complete acquisition must select the registered NSW source"
    if import_profile == "psi-sales" and (
        scope.get("all_history") is not True or scope.get("include_current_weekly") is not True
    ):
        return "PSI complete acquisition must include all history and current weekly partitions"
    return None


def acquisition_scope_error(
    import_profile: str,
    scope: Mapping[str, Any],
    *,
    current_year: int | None = None,
) -> str | None:
    """Validate a complete scope or the one registered bounded PSI scope."""
    if scope.get("profile") != PSI_YEAR_RANGE_PROFILE:
        return complete_scope_error(import_profile, scope)
    if import_profile != "psi-sales":
        return "the bounded year-range scope is supported only for PSI sales"
    unexpected = set(scope) - _PSI_YEAR_RANGE_FIELDS
    if unexpected:
        return f"acquisition scope contains unsupported fields: {', '.join(sorted(unexpected))}"
    start_year = scope.get("start_year")
    end_year = scope.get("end_year")
    if (
        not isinstance(start_year, int)
        or isinstance(start_year, bool)
        or not isinstance(end_year, int)
        or isinstance(end_year, bool)
    ):
        return "PSI year range requires integer start_year and end_year values"
    latest_completed_year = (current_year or datetime.now(UTC).year) - 1
    if start_year < PSI_MINIMUM_YEAR or end_year > latest_completed_year or start_year > end_year:
        return (
            f"PSI year range must run from {PSI_MINIMUM_YEAR} to "
            f"{latest_completed_year}, with start_year no later than end_year"
        )
    expected_years = list(range(start_year, end_year + 1))
    if scope.get("years") != expected_years:
        return "PSI year-range partitions must exactly match start_year through end_year"
    if (
        scope.get("all_records") is not True
        or scope.get("all_history") is not False
        or scope.get("include_current_weekly") is not False
        or scope.get("complete") is not False
        or scope.get("coverage_status") != "partial"
        or scope.get("limitations") != [PSI_PARTIAL_LIMITATION]
    ):
        return "PSI year-range evidence must explicitly identify partial annual-partition coverage"
    return None
