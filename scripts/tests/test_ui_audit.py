"""Deterministic unit tests for UI audit selection, classification, and reports."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.ui_audit.config import AuditSelection, compile_batches, load_config
from scripts.ui_audit.models import Viewport
from scripts.ui_audit.report import atomic_json, load_completed_batch, summary_for
from scripts.ui_audit.rules import classify_page


def test_real_config_accounts_for_every_required_route_state() -> None:
    config = load_config()

    assert len(config.routes) == 25
    assert sum(len(route.deferred_states) for route in config.routes) == 3
    assert {state for route in config.routes for state in route.deferred_states} == {
        "long-content",
        "partial",
    }
    assert len(compile_batches(config, profile="quick")) == 6
    assert {batch.route_id for batch in compile_batches(config, profile="quick")} == {
        "shared-home",
        "property-search",
        "operations-overview",
    }


def test_shards_are_stable_disjoint_and_complete() -> None:
    config = load_config()
    complete = compile_batches(config, profile="full", source_digest="fixed")
    shards = [
        compile_batches(
            config,
            profile="full",
            source_digest="fixed",
            selection=AuditSelection(shard_index=index, shard_total=4),
        )
        for index in range(4)
    ]
    ids = [{batch.id for batch in shard} for shard in shards]

    assert set.union(*ids) == {batch.id for batch in complete}
    assert sum(len(values) for values in ids) == len(complete)
    assert all(
        left.isdisjoint(right) for index, left in enumerate(ids) for right in ids[index + 1 :]
    )


def test_laptop_overflow_and_console_are_gating_findings() -> None:
    viewport = Viewport(
        id="laptop-wide",
        width=1440,
        height=1000,
        gate="release-critical-full-matrix",
    )
    findings = classify_page(
        viewport,
        {"document": {"horizontalOverflow": True}},
        console=({"type": "error", "text": "canary", "expected": False},),
    )

    assert {(finding.code, finding.severity) for finding in findings} == {
        ("page-horizontal-overflow", "error"),
        ("unexpected-console-error", "error"),
    }


def test_narrow_touch_target_is_warning_unless_core() -> None:
    viewport = Viewport(
        id="mobile",
        width=390,
        height=844,
        gate="required-capture-bounded-resilience",
    )
    findings = classify_page(
        viewport,
        {
            "document": {"horizontalOverflow": False},
            "tinyTargets": [{"tag": "button", "core": False}, {"tag": "button", "core": True}],
        },
    )

    assert [finding.severity for finding in findings] == ["warning", "error"]


def test_atomic_batch_resume_requires_matching_complete_fingerprint(tmp_path: Path) -> None:
    path = tmp_path / "batches" / "one.json"
    atomic_json(path, {"fingerprint": "match", "status": "passed", "value": 1})

    assert load_completed_batch(path, "match") == {
        "fingerprint": "match",
        "status": "passed",
        "value": 1,
    }
    assert load_completed_batch(path, "different") is None
    path.write_text("{", encoding="utf-8")
    assert load_completed_batch(path, "match") is None


def test_summary_counts_controls_findings_and_resume() -> None:
    result = summary_for(
        [
            {
                "status": "failed",
                "resumed": True,
                "durationMs": 25,
                "baseline": {"screenshot": "baseline.png"},
                "inventory": {"count": 2},
                "interactions": [
                    {"status": "exercised"},
                    {"status": "skipped-destructive"},
                ],
                "findings": [{"code": "overflow", "severity": "error"}],
            }
        ],
        total_planned=1,
        deferred_states=3,
    )

    assert result["batches"] == {
        "planned": 1,
        "completed": 1,
        "passed": 0,
        "failed": 1,
        "resumed": 1,
    }
    assert result["controls"]["inventoried"] == 2
    assert result["findings"]["bySeverity"] == {"error": 1}
    assert json.dumps(result)
