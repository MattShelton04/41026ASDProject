"""Complete-source acquisition scope invariants shared by config and HTTP policy."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

_COMMON_FIELDS = frozenset({"profile", "all_records"})
_PROFILE_FIELDS = {
    "bocsar-sparse": frozenset({"geography_kinds"}),
    "gnaf-nsw": frozenset({"state"}),
    "psi-sales": frozenset({"all_history", "include_current_weekly"}),
}


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
