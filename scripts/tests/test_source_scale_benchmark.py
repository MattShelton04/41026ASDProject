"""Deterministic safety and evidence-shape tests for the source-scale benchmark harness."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from scripts import source_scale_benchmark as benchmark


def test_plan_requires_three_reset_runs_for_each_meaningful_variant() -> None:
    specs = benchmark.benchmark_plan("psi", 100_000, 3)

    assert [spec.run_id for spec in specs] == [
        "psi-100000-jsonb-wide-r1",
        "psi-100000-jsonb-wide-r2",
        "psi-100000-jsonb-wide-r3",
        "psi-100000-typed-phases-r1",
        "psi-100000-typed-phases-r2",
        "psi-100000-typed-phases-r3",
    ]
    assert benchmark.planned_suite(specs)["reset_policy"].startswith("fresh disposable schema")


@pytest.mark.parametrize(
    ("dataset", "scale", "repetitions", "variants", "message"),
    [
        ("unknown", 100_000, 3, (), "unknown dataset"),
        ("psi", 10_000, 3, (), "scale must be"),
        ("psi", 100_000, 2, (), "repetitions must be"),
        ("psi", 100_000, 11, (), "repetitions must be"),
        ("bocsar", 100_000, 3, ("typed-phases",), "unknown bocsar"),
        ("psi", 100_000, 3, ("typed-phases", "typed-phases"), "must not be repeated"),
    ],
)
def test_plan_rejects_unbounded_or_unknown_work(
    dataset: str,
    scale: int,
    repetitions: int,
    variants: tuple[str, ...],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        benchmark.benchmark_plan(dataset, scale, repetitions, variants)


def _gate_summary(
    dataset: str, variants: tuple[str, ...], repetitions: int = 3
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "mode": "executed",
        "executed": True,
        "dataset": dataset,
        "scale": 100_000,
        "runs": [
            {
                "variant": variant,
                "repetition": repetition,
                "status": "succeeded",
                "executed": True,
                "cleanup": {"schema_dropped": True},
            }
            for variant in variants
            for repetition in range(1, repetitions + 1)
        ],
    }


def test_million_gate_requires_three_successful_cleaned_100k_runs(tmp_path: Path) -> None:
    evidence = tmp_path / "suite-summary.json"
    evidence.write_text(
        json.dumps(_gate_summary("psi", benchmark.VARIANTS["psi"])), encoding="utf-8"
    )

    benchmark.validate_million_gate(evidence, "psi", benchmark.VARIANTS["psi"])

    evidence.write_text(
        json.dumps(_gate_summary("psi", benchmark.VARIANTS["psi"], repetitions=2)),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="3 successful cleaned"):
        benchmark.validate_million_gate(evidence, "psi", benchmark.VARIANTS["psi"])


def test_million_gate_rejects_plans_mismatches_and_unclean_runs(tmp_path: Path) -> None:
    evidence = tmp_path / "suite-summary.json"
    payload = _gate_summary("bocsar", benchmark.VARIANTS["bocsar"])
    payload["mode"] = "plan"
    evidence.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="executed matching 100k"):
        benchmark.validate_million_gate(evidence, "bocsar", benchmark.VARIANTS["bocsar"])

    payload["mode"] = "executed"
    runs = payload["runs"]
    assert isinstance(runs, list)
    runs[0]["cleanup"]["schema_dropped"] = False
    evidence.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="3 successful cleaned"):
        benchmark.validate_million_gate(evidence, "bocsar", benchmark.VARIANTS["bocsar"])


def test_explain_projection_retains_per_node_temp_block_evidence() -> None:
    plan = [
        {
            "Plan": {
                "Node Type": "Insert",
                "Actual Rows": 1,
                "Actual Loops": 1,
                "Actual Total Time": 12.5,
                "Temp Read Blocks": 4,
                "Temp Written Blocks": 7,
                "Plans": [
                    {
                        "Node Type": "Sort",
                        "Actual Rows": 100_000,
                        "Actual Loops": 1,
                        "Actual Total Time": 10.0,
                        "Temp Read Blocks": 3,
                        "Temp Written Blocks": 5,
                    }
                ],
            }
        }
    ]

    assert benchmark.extract_plan_nodes(plan) == [
        {
            "path": "0",
            "node_type": "Insert",
            "actual_rows": 1,
            "actual_loops": 1,
            "actual_total_time_ms": 12.5,
            "temp_read_blocks": 4,
            "temp_written_blocks": 7,
        },
        {
            "path": "0.0",
            "node_type": "Sort",
            "actual_rows": 100_000,
            "actual_loops": 1,
            "actual_total_time_ms": 10.0,
            "temp_read_blocks": 3,
            "temp_written_blocks": 5,
        },
    ]


def test_real_shape_sql_keeps_comparison_hypotheses_and_semantics() -> None:
    schema = "propertyscope_bench_test_1_abcdef123456"
    psi_baseline = benchmark.RunSpec("psi", 100_000, "jsonb-wide", 1)
    psi_typed = benchmark.RunSpec("psi", 100_000, "typed-phases", 1)
    bocsar_baseline = benchmark.RunSpec("bocsar", 100_000, "jsonb-ordered", 1)
    bocsar_typed = benchmark.RunSpec("bocsar", 100_000, "typed-unordered", 1)

    baseline_setup, baseline_measured, baseline_insert = benchmark.benchmark_sql(
        psi_baseline, schema
    )
    typed_setup, typed_measured, typed_insert = benchmark.benchmark_sql(psi_typed, schema)
    bocsar_setup, bocsar_measured, bocsar_insert = benchmark.benchmark_sql(bocsar_baseline, schema)
    bocsar_typed_setup, bocsar_typed_measured, bocsar_typed_insert = benchmark.benchmark_sql(
        bocsar_typed, schema
    )

    assert "payload jsonb" in " ".join(sql for _phase, sql in baseline_setup).lower()
    assert "distinct on" in baseline_insert.lower()
    assert "row_number()" in baseline_insert.lower()
    assert "having count(*)=1" in baseline_insert.lower()
    assert "order by" in baseline_insert.lower()
    assert baseline_measured == ()
    assert [phase for phase, _sql in typed_setup] == [
        "create_registry",
        "typed_staging",
        "create_target",
    ]
    assert [phase for phase, _sql in typed_measured] == [
        "identity_revision_derivation",
        "address_resolution",
    ]
    assert "group by source_business_key,source_row_sha256" in typed_measured[0][1].lower()
    assert "row_number()" in typed_measured[0][1].lower()
    assert "match_count" in typed_measured[1][1].lower()
    assert "house_number ~" in typed_measured[1][1].lower()
    assert "coalesce(source.property_ref" in typed_insert.lower()
    assert "resolution.postcode=source.postcode" in typed_insert.lower()
    assert "payload jsonb" in " ".join(sql for _phase, sql in bocsar_setup).lower()
    assert "record_kind" in " ".join(sql for _phase, sql in bocsar_setup).lower()
    assert "observed_months" in " ".join(sql for _phase, sql in bocsar_setup).lower()
    assert "1+(record_key%41)" in " ".join(sql for _phase, sql in bocsar_setup).lower()
    assert "bocsar_observation_target" in bocsar_insert
    assert "bocsar_coverage_target" in bocsar_insert
    assert "order by ordinal" in bocsar_insert.lower()
    assert "bocsar_stage_typed" in " ".join(sql for _phase, sql in bocsar_typed_setup)
    assert "min(ordinal)" in bocsar_typed_insert.lower()
    assert "order by ordinal" not in bocsar_typed_insert.lower()
    assert bocsar_measured == bocsar_typed_measured == ()


def test_metric_deltas_report_temp_wal_and_checkpoint_counters() -> None:
    before = {
        "database": {"temp_bytes": 10, "temp_files": 1, "blks_read": 3},
        "wal": {"wal_bytes": 100, "wal_records": 4},
        "checkpoints": {"checkpoints_req": 2, "buffers_checkpoint": 8},
    }
    after = {
        "database": {"temp_bytes": 50, "temp_files": 3, "blks_read": 9},
        "wal": {"wal_bytes": 160, "wal_records": 10},
        "checkpoints": {"checkpoints_req": 3, "buffers_checkpoint": 20},
    }

    assert benchmark.metric_deltas(before, after) == {
        "database": {"temp_bytes": 40.0, "temp_files": 2.0, "blks_read": 6.0},
        "wal": {"wal_bytes": 60.0, "wal_records": 6.0},
        "checkpoints": {"checkpoints_req": 1.0, "buffers_checkpoint": 12.0},
        "io": {
            "totals": {},
            "by_scope": [],
            "scope_count": 0,
            "truncated": False,
            "stats_reset_changed": False,
        },
    }


def test_pg_stat_io_deltas_are_bounded_and_grouped_by_scope() -> None:
    before = [
        {
            "backend_type": "client backend",
            "object": "relation",
            "context": "normal",
            "reads": 2,
            "writes": 3,
            "stats_reset": "2026-08-30T00:00:00Z",
        }
    ]
    after = [
        {
            "backend_type": "client backend",
            "object": "relation",
            "context": "normal",
            "reads": 7,
            "writes": 11,
            "stats_reset": "2026-08-30T00:00:00Z",
        }
    ]

    assert benchmark.io_metric_deltas(before, after) == {
        "totals": {"reads": 5.0, "writes": 8.0},
        "by_scope": [
            {
                "backend_type": "client backend",
                "object": "relation",
                "context": "normal",
                "counters": {"reads": 5.0, "writes": 8.0},
            }
        ],
        "scope_count": 1,
        "truncated": False,
        "stats_reset_changed": False,
    }


def test_relation_growth_separates_heap_and_indexes_per_relation() -> None:
    before = {
        "relations": [{"relation": "stage", "heap_bytes": 10, "index_bytes": 4, "total_bytes": 16}]
    }
    after = {
        "relations": [
            {"relation": "stage", "heap_bytes": 25, "index_bytes": 9, "total_bytes": 38},
            {"relation": "target", "heap_bytes": 30, "index_bytes": 12, "total_bytes": 48},
        ]
    }

    assert benchmark.relation_size_deltas(before, after) == {
        "aggregate": {"heap_bytes": 45, "index_bytes": 17, "total_bytes": 70},
        "relations": [
            {"relation": "stage", "heap_bytes": 15, "index_bytes": 5, "total_bytes": 22},
            {"relation": "target", "heap_bytes": 30, "index_bytes": 12, "total_bytes": 48},
        ],
    }


def test_summary_schema_is_bounded_and_never_infers_claims() -> None:
    suite = benchmark.planned_suite(benchmark.benchmark_plan("bocsar", 100_000, 3))
    benchmark.validate_suite_summary(suite)
    assert suite["executed"] is False
    assert suite["claims"] == []
    assert suite["limits"] == {
        "materialisation_deadline_seconds": 1800,
        "progress_interval_seconds": 300,
        "maximum_plan_nodes": 256,
        "maximum_forced_cancel_seconds": 300,
    }

    run = {
        "schema_version": 1,
        "dataset": "bocsar",
        "scale": 100_000,
        "executed": True,
        "status": "succeeded",
        "progress_snapshots": [{}] * (benchmark.MAX_PROGRESS_SNAPSHOTS + 1),
        "plan_nodes": [],
        "cleanup": {"schema_dropped": True},
    }
    with pytest.raises(ValueError, match="too many progress"):
        benchmark.validate_run_summary(run)


def test_cli_dry_run_needs_no_database_and_one_million_requires_gate(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert (
        benchmark.main(["plan", "--dataset", "bocsar", "--scale", "100000", "--repetitions", "3"])
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["executed"] is False
    assert len(payload["runs"]) == 6

    assert (
        benchmark.main(["plan", "--dataset", "bocsar", "--scale", "1000000", "--repetitions", "3"])
        == 2
    )
    assert "require --gate-evidence" in capsys.readouterr().out


def test_forced_cancellation_cleanup_drill_is_explicitly_gated() -> None:
    benchmark.validate_forced_cancellation(2, mode="run", scale=100_000)
    with pytest.raises(ValueError, match="only in run mode"):
        benchmark.validate_forced_cancellation(2, mode="plan", scale=100_000)
    with pytest.raises(ValueError, match="restricted to the 100k"):
        benchmark.validate_forced_cancellation(2, mode="run", scale=1_000_000)
    with pytest.raises(ValueError, match="between 1 and 300"):
        benchmark.validate_forced_cancellation(301, mode="run", scale=100_000)


def test_generated_schema_is_fixed_and_traversal_safe() -> None:
    assert benchmark._quoted_schema("propertyscope_bench_psi_1_abcdef123456") == (
        '"propertyscope_bench_psi_1_abcdef123456"'
    )
    for unsafe in ("public", "propertyscope_bench_x;drop schema public", "../benchmark"):
        with pytest.raises(ValueError, match="fixed disposable prefix"):
            benchmark._quoted_schema(unsafe)


def test_default_output_is_under_the_ignored_runtime_tree() -> None:
    assert benchmark.DEFAULT_OUTPUT_ROOT.is_relative_to(
        benchmark.REPOSITORY_ROOT / ".propertyscope-runtime"
    )
