"""Deterministic unit tests for UI audit selection, classification, and reports."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from scripts.ui_audit.config import AuditSelection, compile_batches, load_config
from scripts.ui_audit.models import AuditBatch, AuditCase, ExpectedFailure, Viewport
from scripts.ui_audit.report import atomic_json, load_completed_batch, summary_for
from scripts.ui_audit.rules import classify_page
from scripts.ui_audit.runner import _expected_failure, _fixture_contract_failure, source_digest


def test_real_config_accounts_for_every_required_route_state() -> None:
    config = load_config()

    assert len(config.routes) == 25
    assert (
        sum(
            len({state for case in route.cases for state in case.states})
            + len(route.deferred_states)
            for route in config.routes
        )
        == 180
    )
    assert sum(len(route.deferred_states) for route in config.routes) == 2
    assert {state for route in config.routes for state in route.deferred_states} == {"long-content"}
    assert len(compile_batches(config, profile="quick")) == 6
    assert {batch.route_id for batch in compile_batches(config, profile="quick")} == {
        "shared-home",
        "property-search",
        "operations-overview",
    }


def test_baseline_artifacts_are_portable_between_contributors() -> None:
    config_path = Path("docs/ui/feature-1-audit-config.json")
    raw = json.loads(config_path.read_text(encoding="utf-8"))
    baseline = Path("docs/ui/feature-1-baseline.md").read_text(encoding="utf-8")

    assert raw["baseline"]["artifactRoot"] == ".propertyscope-runtime/ui-baseline"
    assert "C:\\Users\\" not in baseline
    assert "C:/Users/" not in baseline


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
    config = load_config()
    planned = compile_batches(config, profile="quick")[:1]
    result = summary_for(
        [
            {
                "routeId": planned[0].route_id,
                "case": {"states": list(planned[0].case.states)},
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
        planned_batches=planned,
        config=config,
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
    assert result["controls"]["configuredIntents"] == len(
        next(
            route for route in config.routes if route.id == planned[0].route_id
        ).configured_interactions
    )
    assert result["findings"]["bySeverity"] == {"error": 1}
    assert result["states"] == {
        "configured": 180,
        "executable": 177,
        "deferred": 3,
        "selected": len(planned[0].case.states),
        "captured": len(planned[0].case.states),
    }
    assert json.dumps(result)


def test_artifact_ids_are_safe_and_collision_resistant() -> None:
    config = load_config()
    route = replace(config.routes[0], id="..\\unsafe/route")
    changed = replace(config, routes=(route,))

    batches = compile_batches(changed, profile="full", source_digest="fixed")

    assert batches
    assert len({batch.id for batch in batches}) == len(batches)
    assert all(not {"/", "\\", "."}.intersection(batch.id) for batch in batches)


def test_source_digest_includes_untracked_source() -> None:
    marker = Path(__file__).resolve().parents[1] / ".ui-audit-digest-test"
    before = source_digest()
    try:
        marker.write_text("first", encoding="utf-8")
        first = source_digest()
        marker.write_text("second", encoding="utf-8")
        second = source_digest()
    finally:
        marker.unlink(missing_ok=True)

    assert before != first
    assert first != second


def test_expected_failure_requires_exact_method_target_and_status() -> None:
    batch = AuditBatch(
        id="exact-failure",
        workspace="feature-1",
        route_group="canary",
        route_id="canary",
        path="#canary",
        case=AuditCase(
            id="failure",
            scenario="populated",
            states=("error",),
            expected_request_failures=(
                ExpectedFailure(
                    method="GET",
                    target="/api/data-platform/v1/jobs/one/capabilities",
                    statuses=(503,),
                ),
            ),
        ),
        viewport=Viewport("laptop-wide", 1440, 1000, "release-critical-full-matrix"),
        fingerprint="exact",
    )

    exact = "http://127.0.0.1:5300/api/data-platform/v1/jobs/one/capabilities"
    assert _expected_failure(batch, "GET", exact, status=503)
    assert not _expected_failure(batch, "POST", exact, status=503)
    assert not _expected_failure(batch, "GET", exact, status=500)
    assert not _expected_failure(batch, "GET", f"{exact}/near-miss", status=503)

    scenario_batch = replace(batch, case=replace(batch.case, scenario="error"))
    unrelated = "http://127.0.0.1:5300/api/data-platform/v1/capabilities-near-miss"
    assert not _fixture_contract_failure(scenario_batch, "GET", unrelated, 503)
