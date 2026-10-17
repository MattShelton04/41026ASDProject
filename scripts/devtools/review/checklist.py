"""Deterministic checklist construction shared by the three review collectors.

Owners and prerequisites
------------------------
A group-wide review checks evidence from several owners (``shared``, ``student-1`` ...
``student-5``). When one owner has not submitted evidence, every check that reads it would
fail with the same cause. Instead, a collector declares the dependency and the checklist marks
those checks ``blocked`` with ``blocked_by`` naming the failed root check::

    checklist.add("ci.student-2.evidence", "student-2 submitted CI evidence",
                  passed=text is not None, detail="...", refs=(path,), owner="student-2")
    checklist.add("ci.student-2.green", "student-2 CI run concluded successfully",
                  passed=..., detail="...", refs=(path,),
                  prerequisite="ci.student-2.evidence")      # owner inherited: student-2

* ``owner`` is optional and defaults to the first prerequisite's owner. Reports group checks by
  it in a "Coverage by owner" table; checks without one are reported as ``unassigned``.
* ``prerequisite`` is one check id or several, each already added. If any of them did not
  pass, the new check is recorded as ``blocked`` (its ``passed`` and ``detail`` arguments are
  ignored) and ``blocked_by`` names the *root* failure, following a blocked prerequisite back
  to the check that actually failed. ``add`` then returns ``False``.
* Make a prerequisite a narrow gate, such as "the owner's evidence file was read", so that a
  present-but-wrong file still evaluates every dependent check.
* Verdict: a blocked required check counts like a failed one, so the review cannot pass while a
  required owner has not submitted evidence (``checklist_verdict`` in the shared contract).
  Reports attribute it to the root check and its owner ("evidence not submitted"), not to the
  behaviour the blocked checks would have tested.
"""

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
        self._by_id: dict[str, EvidenceCheck] = {}

    def add(
        self,
        check_id: str,
        title: str,
        *,
        passed: bool,
        detail: str,
        refs: Iterable[str] = (),
        required: bool = True,
        owner: str | None = None,
        prerequisite: str | Iterable[str] | None = None,
    ) -> bool:
        """Record one outcome; returns whether it passed (a blocked check never passes).

        See the module docstring for ``owner`` and ``prerequisite``.
        """
        if check_id in self._by_id:
            raise ValueError(f"check {check_id} was already added")
        prerequisites = self._prerequisites(check_id, prerequisite)
        unmet = next(
            (check for check in prerequisites if check.status is not CheckStatus.PASSED), None
        )
        if owner is None and prerequisites:
            owner = prerequisites[0].owner
        known = self._reader.known_paths()
        cited: list[str] = []
        # A blocked check assessed no evidence; its root check cites what was missing.
        for reference in refs if unmet is None else ():
            if reference.partition("#")[0] in known and reference not in cited:
                cited.append(reference)
        blocked_by: str | None = None
        if unmet is not None:
            blocked_by = unmet.blocked_by or unmet.id
            status = CheckStatus.BLOCKED
            text = f"Not evaluated: blocked by {blocked_by}, which failed."
        else:
            status = CheckStatus.PASSED if passed else CheckStatus.FAILED
            text = " ".join(detail.split()) or ("Passed." if passed else "Failed.")
        check = EvidenceCheck(
            id=check_id,
            title=title,
            status=status,
            required=required,
            detail=text if len(text) <= _MAX_DETAIL else text[: _MAX_DETAIL - 1] + "…",
            evidence_refs=tuple(cited[:_MAX_REFS]),
            owner=owner,
            blocked_by=blocked_by,
        )
        self._checks.append(check)
        self._by_id[check_id] = check
        return status is CheckStatus.PASSED

    def status(self, check_id: str) -> CheckStatus:
        """Return the recorded status of a check that was already added."""
        return self._by_id[check_id].status

    def _prerequisites(
        self, check_id: str, prerequisite: str | Iterable[str] | None
    ) -> list[EvidenceCheck]:
        if prerequisite is None:
            names: list[str] = []
        elif isinstance(prerequisite, str):
            names = [prerequisite]
        else:
            names = list(prerequisite)
        missing = [name for name in names if name not in self._by_id]
        if missing:
            raise ValueError(
                f"prerequisite {', '.join(missing)} must be added before check {check_id}"
            )
        return [self._by_id[name] for name in names]

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
