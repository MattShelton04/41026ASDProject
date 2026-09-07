"""Evaluation reporting must not mistake source recall for answer truthfulness."""

from pathlib import Path

from rag_server.embeddings import FixtureEmbedder
from scripts.evaluate_release1_retrieval import evaluate

from shared_contracts.retrieval import CorpusDocument, CorpusIngestRequest


def test_report_retains_negative_results_and_distinguishes_fixture_evidence(tmp_path: Path) -> None:
    corpus = CorpusIngestRequest(
        feature_key="example",
        corpus_id="guidance",
        documents=(
            CorpusDocument(
                document_id="publication",
                title="Publication",
                text="publication producer independent consumer",
                source_uri="https://example.com/guidance",
                license="CC0-1.0",
            ),
        ),
    )
    settings = {
        "evaluation_id": "fixture-report",
        "top_k": 5,
        "min_score": 0.0,
        "max_context_chars": 5000,
        "target_expected_source_recall": 0.9,
        "cases": [
            {
                "id": "supported",
                "category": "supported",
                "query": "publication producer",
                "expected_document_ids": ["publication", "missing-document"],
            },
            {
                "id": "absent",
                "category": "absent",
                "query": "planet",
                "expected_document_ids": [],
                "forbidden_claims": ["The planet is described by this corpus."],
            },
        ],
    }
    report = evaluate(corpus, settings, FixtureEmbedder(), tmp_path / "evaluation.sqlite3")
    assert report["mode"] == "fixture_mechanics"
    assert report["expected_source_recall_at_5"] == 0.5
    assert report["retrieval_target_met"] is False
    assert report["identical_replay_preserves_version_and_timestamp"] is True
    assert report["negative_case_count"] == 1
    negative = report["cases"][1]
    assert negative["retrieval"]["status"] == "ready"
    assert negative["answer_claim_validation"] == "not_executed_no_answer_model"
    assert negative["forbidden_claims"]
    assert report["answer_tokens"] is None
