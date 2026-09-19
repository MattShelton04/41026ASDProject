"""Cover the shared grounded-allowlist expansion feature backends depend on."""

from __future__ import annotations

import pytest

from shared_contracts.grounding import RETRIEVAL_TOOL, grounded_allowlist_variants

BASE = ("feature.read.v1", "feature.inspect.v1")
OLDER = ("feature.read.v1",)


def test_expands_one_allowlist_with_its_grounded_variant() -> None:
    assert grounded_allowlist_variants(BASE) == (BASE, (*BASE, RETRIEVAL_TOOL))


def test_retains_every_historical_allowlist_before_the_grounded_variants() -> None:
    """Persisted runs predate grounding, so their exact tuples must stay approved."""
    assert grounded_allowlist_variants(OLDER, BASE) == (
        OLDER,
        BASE,
        (*OLDER, RETRIEVAL_TOOL),
        (*BASE, RETRIEVAL_TOOL),
    )


def test_accepts_any_sequence_and_normalises_to_tuples() -> None:
    assert grounded_allowlist_variants(list(OLDER)) == (OLDER, (*OLDER, RETRIEVAL_TOOL))


def test_requires_at_least_one_allowlist() -> None:
    with pytest.raises(ValueError, match="at least one tool allowlist"):
        grounded_allowlist_variants()


@pytest.mark.parametrize(
    ("allowlists", "message"),
    [
        (((),), "must not be empty"),
        ((("a.v1", "a.v1"),), "must not contain duplicates"),
        (((BASE, BASE)), "duplicate tool allowlist"),
        ((("a.v1", RETRIEVAL_TOOL),), "added by this helper"),
    ],
)
def test_rejects_allowlists_that_would_produce_an_ambiguous_set(
    allowlists: tuple[tuple[str, ...], ...], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        grounded_allowlist_variants(*allowlists)


def test_grounded_variant_is_appended_not_inserted() -> None:
    """AI-mode appends the retrieval tool, so the approved variant must match that order."""
    variants = grounded_allowlist_variants(BASE)
    assert variants[-1][: len(BASE)] == BASE
    assert variants[-1][-1] == RETRIEVAL_TOOL
