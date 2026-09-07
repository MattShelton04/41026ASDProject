"""Evaluate frozen Feature 1 retrieval cases using prepared local semantic assets only.

This opt-in local evaluation does not call a language model or assert answer entailment.
The temporary index never opens or changes the running RAG service's database.
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from time import perf_counter
from typing import Any

from rag_server.cli import load_manifest
from rag_server.embeddings import Embedder, LocalEmbedder
from rag_server.index import CorpusIndex

from shared_contracts.retrieval import CorpusDocument, CorpusIngestRequest, RetrievalRequest

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "student-1/config/rag/corpus.json"
CASES = ROOT / "student-1/config/rag/evaluation-v1.json"


def evaluate(
    corpus: CorpusIngestRequest, cases: dict[str, Any], embedder: Embedder, database: Path
) -> dict[str, Any]:
    """Capture every ranked excerpt and source recall without judging generated answers."""
    index = CorpusIndex(database, embedder, frozenset({(corpus.feature_key, corpus.corpus_id)}))
    try:
        started = perf_counter()
        version = index.ingest(corpus)
        ingest_seconds = perf_counter() - started
        replay = index.ingest(corpus)
        results = []
        for case in cases["cases"]:
            # Adversarial fixtures enter only this disposable evaluation index, never the
            # production manifest. Pin the actual searched version on every recorded case.
            additions = tuple(
                CorpusDocument.model_validate(document)
                for document in case.get("additional_documents", [])
            )
            searched_version = index.ingest(corpus.evolve(documents=corpus.documents + additions))
            started = perf_counter()
            response = index.retrieve(
                RetrievalRequest(
                    feature_key=corpus.feature_key,
                    corpus_id=corpus.corpus_id,
                    query=case["query"],
                    top_k=cases["top_k"],
                    min_score=cases["min_score"],
                    max_context_chars=cases["max_context_chars"],
                )
            )
            actual = {citation.document_id for citation in response.citations}
            expected = set(case["expected_document_ids"])
            results.append(
                {
                    **case,
                    "searched_corpus": searched_version.model_dump(mode="json"),
                    "retrieval_seconds": round(perf_counter() - started, 6),
                    "expected_source_recall": len(actual & expected) / len(expected)
                    if expected
                    else None,
                    "retrieval": response.model_dump(mode="json"),
                    "answer_claim_validation": "not_executed_no_answer_model",
                }
            )
        answerable = [row for row in results if row["category"] == "supported"]
        recall = sum(row["expected_source_recall"] for row in answerable) / len(answerable)
        return {
            "schema_version": "1.0",
            "evaluation_id": cases["evaluation_id"],
            "executed_at": datetime.now(UTC).isoformat(),
            "mode": "semantic" if isinstance(embedder, LocalEmbedder) else "fixture_mechanics",
            "corpus": version.model_dump(mode="json"),
            "settings": {key: cases[key] for key in ("top_k", "min_score", "max_context_chars")},
            "ingest_seconds": round(ingest_seconds, 6),
            "identical_replay_preserves_version_and_timestamp": replay == version,
            "supported_cases": len(answerable),
            "expected_source_recall_at_5": recall,
            "retrieval_target_met": recall >= cases["target_expected_source_recall"],
            "negative_case_count": len(results) - len(answerable),
            "answer_model": None,
            "prompt_version": None,
            "answer_tokens": None,
            "limitations": [
                "Small authored corpus and development case set; not a held-out benchmark.",
                "Similarity and source recall do not establish claim support or answer safety.",
                "Negative cases may retrieve related guidance; current facts require owning tools.",
                "Forbidden claims require separate generated-answer/harness evaluation.",
            ],
            "cases": results,
        }
    finally:
        index.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, default=CORPUS)
    parser.add_argument("--cases", type=Path, default=CASES)
    parser.add_argument(
        "--model-cache", type=Path, default=ROOT / ".propertyscope-runtime/host/rag/models"
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    # Model preparation is a separate explicit operator action, never an evaluation side effect.
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    embedder = LocalEmbedder(args.model_cache)
    corpus = load_manifest(args.corpus)
    cases = json.loads(args.cases.read_text(encoding="utf-8"))
    with TemporaryDirectory(prefix="propertyscope-retrieval-evaluation-") as directory:
        report = evaluate(corpus, cases, embedder, Path(directory) / "evaluation.sqlite3")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "report": str(args.output),
                "expected_source_recall_at_5": report["expected_source_recall_at_5"],
                "retrieval_target_met": report["retrieval_target_met"],
                "embedding_model": report["corpus"]["embedding_model"],
                "answer_claim_validation": "not_executed_no_answer_model",
            }
        )
    )
    if not report["retrieval_target_met"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
