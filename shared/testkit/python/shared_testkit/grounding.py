"""Assertions every feature owner needs when adopting the shared MCP/RAG runtime.

These cover the checks `docs/release-1/feature-adoption.md` asks each owner to retain, so the
five slices produce comparable evidence instead of five hand-rolled suites. Nothing here starts
a service, reads an index or downloads a model: these are offline manifest and shape checks.
"""

import json
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from shared_contracts.grounding import RETRIEVAL_TOOL
from shared_contracts.retrieval import CorpusIngestRequest

# Mirrors the rag-server ingest loader: explicit local text confined to the manifest directory.
_ALLOWED_DOCUMENT_SUFFIXES = frozenset({".md", ".txt"})
_MAX_DOCUMENT_BYTES = 240_000


def load_corpus_manifest(manifest_path: Path) -> CorpusIngestRequest:
    """Resolve a manifest's declared document paths and validate the ingest contract.

    Applies the same rules the ``rag-server ingest`` loader applies, so a manifest that passes
    here is one the running server will accept. Returns the validated request rather than
    sending it; nothing is ingested.
    """
    base = manifest_path.resolve().parent
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise AssertionError(f"{manifest_path} must contain a JSON object")
    for document in payload.get("documents", []):
        if not isinstance(document, dict):
            raise AssertionError("every corpus document must be a JSON object")
        source = document.pop("path", None)
        if source is None:
            continue
        if "text" in document:
            raise AssertionError(
                f"{document.get('document_id')} declares both path and text; use one"
            )
        resolved = (base / str(source)).resolve()
        if not resolved.is_relative_to(base):
            raise AssertionError(f"{document.get('document_id')} escapes the manifest directory")
        if resolved.suffix.lower() not in _ALLOWED_DOCUMENT_SUFFIXES:
            raise AssertionError(f"{document.get('document_id')} must be a .md or .txt file")
        if not resolved.is_file():
            raise AssertionError(f"{document.get('document_id')} references a missing file")
        if resolved.stat().st_size > _MAX_DOCUMENT_BYTES:
            raise AssertionError(f"{document.get('document_id')} is too large to ingest")
        document["text"] = resolved.read_text(encoding="utf-8")
    return CorpusIngestRequest.model_validate(payload)


def assert_corpus_manifest(
    manifest_path: Path, *, feature_key: str, corpus_id: str, max_document_chars: int = 1200
) -> CorpusIngestRequest:
    """Validate an owned corpus manifest and return it for further feature-specific checks.

    Verifies the identity the host launcher scopes RAG with, that documents resolve and are
    unique, and that each passage is short enough to survive chunking intact. Documents longer
    than ``max_document_chars`` are reported because a split can separate a policy assertion
    from the qualification that bounds it.
    """
    request = load_corpus_manifest(manifest_path)
    assert request.feature_key == feature_key, (
        f"corpus manifest feature_key {request.feature_key!r} must match {feature_key!r}"
    )
    assert request.corpus_id == corpus_id, (
        f"corpus manifest corpus_id {request.corpus_id!r} must match {corpus_id!r}"
    )
    assert request.documents, "a corpus manifest must declare at least one document"
    oversized = sorted(
        document.document_id
        for document in request.documents
        if len(document.text) > max_document_chars
    )
    assert not oversized, (
        f"these documents exceed {max_document_chars} characters and may split a claim from "
        f"its qualification: {', '.join(oversized)}"
    )
    return request


def assert_grounded_allowlist_accepted(
    approved: Iterable[Sequence[str]], base_allowlist: Sequence[str]
) -> None:
    """Fail if a backend would reject its own run once a corpus is registered.

    AI-mode appends the shared retrieval tool to a grounded run's allowlist. A backend that
    validates an exact historical tuple must approve that variant too, or it stops being able
    to read the runs it just created. ``grounded_allowlist_variants`` builds both.
    """
    base = tuple(base_allowlist)
    approved_tuples = {tuple(item) for item in approved}
    assert base in approved_tuples, (
        "the pre-grounding allowlist must remain approved so persisted runs stay readable"
    )
    assert (*base, RETRIEVAL_TOOL) in approved_tuples, (
        f"approve the grounded variant ending in {RETRIEVAL_TOOL}; AI-mode adds it to every "
        "run whose feature has a registered corpus"
    )


def assert_grounded_answer(answer: Mapping[str, object], *, expect_citations: bool) -> None:
    """Check the answer shape the rubric marks: citations, confidence and a stated boundary.

    Pass ``expect_citations=False`` for the insufficient-context case, which must report
    ``insufficient`` confidence and cite nothing rather than inventing support.
    """
    confidence = answer.get("confidence")
    assert confidence in {"high", "moderate", "low", "insufficient"}, (
        f"unexpected confidence category: {confidence!r}"
    )
    assert answer.get("confidence_reason"), "a confidence category needs a stated reason"
    assert answer.get("safety_boundary"), "a grounded answer must state its safety boundary"
    citation_ids = [
        citation_id for finding in _findings(answer) for citation_id in _citation_ids(finding)
    ]
    if expect_citations:
        assert citation_ids, "a supported grounded answer must cite retrieved documents"
        assert confidence != "insufficient", (
            "an answer citing retrieved guidance must not report insufficient context"
        )
    else:
        assert not citation_ids, "an insufficient-context answer must not cite sources"
        assert confidence == "insufficient", (
            f"expected insufficient confidence without context, got {confidence!r}"
        )


def _findings(answer: Mapping[str, object]) -> list[Mapping[str, Any]]:
    findings = answer.get("findings", ())
    if isinstance(findings, str | bytes) or not isinstance(findings, Iterable):
        return []
    return [finding for finding in findings if isinstance(finding, Mapping)]


def _citation_ids(finding: Mapping[str, Any]) -> list[Any]:
    citation_ids = finding.get("citation_ids", ())
    if isinstance(citation_ids, str | bytes) or not isinstance(citation_ids, Iterable):
        return []
    return list(citation_ids)
