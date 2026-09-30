"""Bounded projection of the public published-locality context contract."""

from __future__ import annotations

import json
from typing import Any


def normalise_locality(value: str) -> str:
    """Match the documented exact uppercase/whitespace normalisation, not geography."""
    return " ".join(value.upper().split())


def project_context(value: dict[str, Any], locality: str) -> dict[str, Any]:
    """Keep source records and provenance intact; never infer missing observations."""
    if (
        not isinstance(value.get("locality"), str)
        or normalise_locality(value["locality"]) != locality
    ):
        raise ValueError("Mismatched locality context")
    for key in ("population", "schools", "crime", "sources", "limitations"):
        if not isinstance(value.get(key), list):
            raise ValueError("Invalid locality context")
    if not all(isinstance(item, str) for item in value["limitations"]):
        raise ValueError("Invalid locality limitations")
    sources = value["sources"]
    if len(sources) > 3 or any(
        not isinstance(source, dict)
        or not isinstance(source.get("release_id"), str)
        or source.get("dataset_id")
        not in {"abs-seifa-2021", "nsw-government-schools", "bocsar-crime"}
        for source in sources
    ):
        raise ValueError("Invalid locality provenance")
    releases = {source["dataset_id"]: source["release_id"] for source in sources}
    if len(releases) != len(sources):
        raise ValueError("Ambiguous source releases")
    datasets = {
        "population": "abs-seifa-2021",
        "schools": "nsw-government-schools",
        "crime": "bocsar-crime",
    }
    fields = {
        "population": "locality_name",
        "schools": "locality_normalised",
        "crime": "geography_value",
    }
    limitations = list(value["limitations"][:20])
    evidence: dict[str, Any] = {"locality": locality, "sources": sources}
    for key, dataset in datasets.items():
        records = value[key]
        if len(records) > 500:
            raise ValueError("Oversized locality context")
        for record in records:
            if (
                not isinstance(record, dict)
                or record.get("state") != "NSW"
                or not isinstance(record.get(fields[key]), str)
                or normalise_locality(record[fields[key]]) != locality
                or not isinstance(record.get("provenance"), dict)
                or dataset not in releases
                or record["provenance"].get("release_id") != releases[dataset]
                or (key == "crime" and record.get("geography_kind") != "suburb")
            ):
                raise ValueError("Invalid locality record or provenance")
        # Preserve reporting periods/coverage within retained records, not a made-up rate.
        retained = records[:25]
        if len(records) > 25:
            limitations.append(f"Suburb analytics {key} records are limited to the first 25.")
        if len(json.dumps(retained).encode()) > 65536:
            retained = []
            limitations.append(
                f"Suburb analytics {key} exceeds the response budget; records omitted."
            )
        evidence[key] = retained
    counts = {key: len(evidence[key]) for key in datasets}
    if not any(counts.values()):
        state = "unavailable"
        limitations.append(
            "No published suburb evidence matched this exact locality; missing is not zero."
        )
    elif len(value["population"]) > 1:
        state = "needs_verification"
        limitations.append(
            "Multiple population localities match; no boundary match is established."
        )
    else:
        # This API supplies source-locality context, not a completeness guarantee.
        state = "partial"
        limitations.append(
            "Published locality context is partial research context, "
            "not a complete locality assessment."
        )
    return {
        "state": state,
        "evidence": evidence,
        "record_counts": counts,
        "limitations": limitations,
    }
