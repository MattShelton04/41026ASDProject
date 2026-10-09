"""Deterministic checklist construction shared by the three review collectors."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from datetime import datetime

from pydantic import JsonValue

from scripts.devtools.review.bounded import EvidenceReader
from shared_contracts.evidence_review import (
    CheckStatus,
    EvidenceCheck,
    EvidenceReviewBundle,
    ReviewMode,
)

_MAX_DETAIL = 500
_MAX_REFS = 10


class Checklist:
    """Accumulate checks in a stable order, citing only inputs the reader recorded."""

    def __init__(self, reader: EvidenceReader) -> None:
        self._reader = reader
        self._checks: list[EvidenceCheck] = []

    def add(
        self,
        check_id: str,
        title: str,
        *,
        passed: bool,
        detail: str,
        refs: Iterable[str] = (),
        required: bool = True,
    ) -> bool:
        """Record one outcome; returns ``passed`` so callers can chain dependent checks."""
        known = self._reader.known_paths()
        cited: list[str] = []
        for reference in refs:
            if reference.partition("#")[0] in known and reference not in cited:
                cited.append(reference)
        text = " ".join(detail.split()) or ("Passed." if passed else "Failed.")
        self._checks.append(
            EvidenceCheck(
                id=check_id,
                title=title,
                status=CheckStatus.PASSED if passed else CheckStatus.FAILED,
                required=required,
                detail=text if len(text) <= _MAX_DETAIL else text[: _MAX_DETAIL - 1] + "…",
                evidence_refs=tuple(cited[:_MAX_REFS]),
            )
        )
        return passed

    def bundle(self, mode: ReviewMode, facts: Mapping[str, JsonValue]) -> EvidenceReviewBundle:
        """Freeze the collected inputs, checks and facts into the shared contract."""
        return EvidenceReviewBundle(
            mode=mode,
            inputs=self._reader.inputs,
            checks=tuple(self._checks),
            facts=dict(facts),
        )


def first_string(record: Mapping[str, JsonValue], *keys: str) -> str | None:
    """Return the first non-empty string value among accepted field-name synonyms."""
    for key in keys:
        value = record.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def parse_timestamp(value: str | None) -> datetime | None:
    """Parse an ISO 8601 timestamp that carries a timezone; naive times are rejected."""
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def summarise(items: Iterable[str], *, limit: int = 4) -> str:
    """Render a short deterministic list, noting how many items were omitted."""
    values = list(items)
    shown = ", ".join(values[:limit])
    if len(values) > limit:
        shown += f" and {len(values) - limit} more"
    return shown


SHA_PATTERN = re.compile(r"\b[0-9a-f]{40}\b")
URL_PATTERN = re.compile(r"https?://[^\s)<>\]|`\"']+")
