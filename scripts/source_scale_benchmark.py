"""Run disposable, bounded real-shape PSI and BOCSAR PostgreSQL benchmarks.

Planning is deterministic and requires no database. Execution is intentionally gated behind an
exact database-name confirmation and creates a fresh ``propertyscope_bench_*`` schema for every
repetition. It never reads production artifacts or Feature 1 tables.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import threading
import time
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_ROOT = REPOSITORY_ROOT / ".propertyscope-runtime" / "source-scale-benchmarks"
SCALES = (100_000, 1_000_000)
MIN_REPETITIONS = 3
MAX_REPETITIONS = 10
MATERIALISATION_DEADLINE_SECONDS = 30 * 60
PROGRESS_INTERVAL_SECONDS = 5 * 60
MAX_PLAN_NODES = 256
MAX_PROGRESS_SNAPSHOTS = 8
MAX_SUMMARY_BYTES = 2 * 1024 * 1024
SCHEMA_PREFIX = "propertyscope_bench_"
SCHEMA_PATTERN = re.compile(r"^propertyscope_bench_[a-z0-9_]{1,48}$")
VARIANTS: Mapping[str, tuple[str, ...]] = {
    "psi": ("jsonb-wide", "typed-phases"),
    "bocsar": ("jsonb-ordered", "typed-unordered"),
}
MAX_SUITE_RUNS = max(len(variants) for variants in VARIANTS.values()) * MAX_REPETITIONS


@dataclass(frozen=True, slots=True)
class RunSpec:
    dataset: str
    scale: int
    variant: str
    repetition: int

    @property
    def run_id(self) -> str:
        return f"{self.dataset}-{self.scale}-{self.variant}-r{self.repetition}"


def benchmark_plan(
    dataset: str,
    scale: int,
    repetitions: int,
    requested_variants: Sequence[str] = (),
) -> tuple[RunSpec, ...]:
    """Return a deterministic reset-run matrix after enforcing benchmark gates."""
    if dataset not in VARIANTS:
        raise ValueError(f"unknown dataset {dataset!r}")
    if scale not in SCALES:
        raise ValueError(f"scale must be one of {SCALES}")
    if not MIN_REPETITIONS <= repetitions <= MAX_REPETITIONS:
        raise ValueError(f"repetitions must be between {MIN_REPETITIONS} and {MAX_REPETITIONS}")
    variants = tuple(requested_variants) or VARIANTS[dataset]
    unknown = sorted(set(variants) - set(VARIANTS[dataset]))
    if unknown:
        raise ValueError(f"unknown {dataset} benchmark variants: {', '.join(unknown)}")
    if len(set(variants)) != len(variants):
        raise ValueError("benchmark variants must not be repeated")
    return tuple(
        RunSpec(dataset, scale, variant, repetition)
        for variant in variants
        for repetition in range(1, repetitions + 1)
    )


def planned_suite(specs: Sequence[RunSpec]) -> dict[str, Any]:
    """Project a bounded dry-run document without claiming executed evidence."""
    if not specs:
        raise ValueError("benchmark plan cannot be empty")
    first = specs[0]
    return {
        "schema_version": 1,
        "mode": "plan",
        "executed": False,
        "dataset": first.dataset,
        "scale": first.scale,
        "variants": list(dict.fromkeys(spec.variant for spec in specs)),
        "repetitions": max(spec.repetition for spec in specs),
        "limits": {
            "materialisation_deadline_seconds": MATERIALISATION_DEADLINE_SECONDS,
            "progress_interval_seconds": PROGRESS_INTERVAL_SECONDS,
            "maximum_plan_nodes": MAX_PLAN_NODES,
        },
        "reset_policy": "fresh disposable schema per repetition; drop attempted in finally",
        "runs": [
            {
                "run_id": spec.run_id,
                "variant": spec.variant,
                "repetition": spec.repetition,
                "status": "planned",
                "executed": False,
            }
            for spec in specs
        ],
        "claims": [],
    }


def validate_million_gate(path: Path, dataset: str, variants: Sequence[str]) -> None:
    """Require three successful reset runs per variant at 100k before a 1m suite."""
    try:
        evidence = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"could not read 100k gate evidence: {exc}") from exc
    if (
        not isinstance(evidence, dict)
        or evidence.get("schema_version") != 1
        or evidence.get("mode") != "executed"
        or evidence.get("executed") is not True
        or evidence.get("dataset") != dataset
        or evidence.get("scale") != 100_000
    ):
        raise ValueError("1m gate requires an executed matching 100k suite summary")
    runs = evidence.get("runs")
    if not isinstance(runs, list):
        raise ValueError("100k gate summary has no bounded run list")
    for variant in variants:
        successful = {
            item.get("repetition")
            for item in runs
            if isinstance(item, dict)
            and item.get("variant") == variant
            and item.get("status") == "succeeded"
            and item.get("executed") is True
            and item.get("cleanup", {}).get("schema_dropped") is True
        }
        if len(successful) < MIN_REPETITIONS:
            raise ValueError(
                f"1m gate requires {MIN_REPETITIONS} successful cleaned 100k runs for {variant}"
            )


def extract_plan_nodes(plan: object) -> list[dict[str, Any]]:
    """Flatten bounded node-level timing and temporary-block evidence from EXPLAIN JSON."""
    if isinstance(plan, list) and plan and isinstance(plan[0], dict):
        root = plan[0].get("Plan")
    elif isinstance(plan, dict):
        root = plan.get("Plan", plan)
    else:
        root = None
    nodes: list[dict[str, Any]] = []

    def visit(node: object, path: str) -> None:
        if not isinstance(node, dict) or len(nodes) >= MAX_PLAN_NODES:
            return
        nodes.append(
            {
                "path": path,
                "node_type": str(node.get("Node Type", "unknown"))[:100],
                "actual_rows": node.get("Actual Rows"),
                "actual_loops": node.get("Actual Loops"),
                "actual_total_time_ms": node.get("Actual Total Time"),
                "temp_read_blocks": int(node.get("Temp Read Blocks", 0) or 0),
                "temp_written_blocks": int(node.get("Temp Written Blocks", 0) or 0),
            }
        )
        children = node.get("Plans", [])
        if isinstance(children, list):
            for index, child in enumerate(children):
                visit(child, f"{path}.{index}")

    visit(root, "0")
    return nodes


def validate_run_summary(summary: object) -> None:
    """Validate the bounded public shape of one executed run summary."""
    if not isinstance(summary, dict) or summary.get("schema_version") != 1:
        raise ValueError("run summary must use schema version 1")
    if summary.get("executed") is not True:
        raise ValueError("run summary must identify executed evidence")
    if summary.get("status") not in {"succeeded", "failed", "cancelled"}:
        raise ValueError("run summary has an invalid status")
    if summary.get("dataset") not in VARIANTS:
        raise ValueError("run summary has an invalid dataset")
    if summary.get("scale") not in SCALES:
        raise ValueError("run summary has an invalid scale")
    progress = summary.get("progress_snapshots", [])
    nodes = summary.get("plan_nodes", [])
    if not isinstance(progress, list) or len(progress) > MAX_PROGRESS_SNAPSHOTS:
        raise ValueError("run summary has too many progress snapshots")
    if not isinstance(nodes, list) or len(nodes) > MAX_PLAN_NODES:
        raise ValueError("run summary has too many plan nodes")
    cleanup = summary.get("cleanup")
    if not isinstance(cleanup, dict) or not isinstance(cleanup.get("schema_dropped"), bool):
        raise ValueError("run summary must include cleanup evidence")


def validate_suite_summary(summary: object) -> None:
    """Validate the bounded plan/execution suite envelope."""
    if not isinstance(summary, dict) or summary.get("schema_version") != 1:
        raise ValueError("suite summary must use schema version 1")
    if summary.get("mode") not in {"plan", "executed"}:
        raise ValueError("suite summary has an invalid mode")
    runs = summary.get("runs")
    if not isinstance(runs, list) or not 1 <= len(runs) <= MAX_SUITE_RUNS:
        raise ValueError("suite summary run list is outside its bound")
    if summary.get("mode") == "executed":
        for run in runs:
            validate_run_summary(run)


def _numeric_delta(after: object, before: object, keys: Sequence[str]) -> dict[str, float]:
    if not isinstance(after, dict) or not isinstance(before, dict):
        return {}
    deltas: dict[str, float] = {}
    for key in keys:
        if key not in after or key not in before:
            continue
        try:
            deltas[key] = float(after[key]) - float(before[key])
        except (TypeError, ValueError):
            continue
    return deltas


def metric_deltas(before: object, after: object) -> dict[str, dict[str, float]]:
    """Calculate explicit database, WAL, checkpoint and temp-byte counter deltas."""
    before_map = before if isinstance(before, dict) else {}
    after_map = after if isinstance(after, dict) else {}
    return {
        "database": _numeric_delta(
            after_map.get("database"),
            before_map.get("database"),
            ("temp_bytes", "temp_files", "blks_read", "blks_hit", "xact_commit", "xact_rollback"),
        ),
        "wal": _numeric_delta(
            after_map.get("wal"),
            before_map.get("wal"),
            ("wal_bytes", "wal_records", "wal_fpi", "wal_buffers_full"),
        ),
        "checkpoints": _numeric_delta(
            after_map.get("checkpoints"),
            before_map.get("checkpoints"),
            (
                "checkpoints_timed",
                "checkpoints_req",
                "buffers_checkpoint",
                "checkpoint_write_time",
                "checkpoint_sync_time",
            ),
        ),
    }


def _schema_name(spec: RunSpec) -> str:
    suffix = uuid.uuid4().hex[:12]
    value = f"{SCHEMA_PREFIX}{spec.dataset}_{spec.repetition}_{suffix}"
    if not SCHEMA_PATTERN.fullmatch(value):
        raise RuntimeError("generated benchmark schema is unsafe")
    return value


def _quoted_schema(schema: str) -> str:
    if not SCHEMA_PATTERN.fullmatch(schema):
        raise ValueError("benchmark schema does not use the fixed disposable prefix")
    return f'"{schema}"'


def _uuid_sql(seed: str) -> str:
    digest = f"md5({seed})"
    return (
        f"(substr({digest},1,8)||'-'||substr({digest},9,4)||'-4'||substr({digest},14,3)||"
        f"'-8'||substr({digest},18,3)||'-'||substr({digest},21,12))::uuid"
    )


def _psi_setup_sql(schema: str, scale: int, variant: str) -> tuple[tuple[str, str], ...]:
    q = _quoted_schema(schema)
    address_key = f"((i - 1) / 3) % greatest(1000, {scale} / 20)"
    registry_uuid = _uuid_sql("'property-'||address_key")
    registry_duplicate_uuid = _uuid_sql("'duplicate-'||address_key")
    registry = f"""
        CREATE TABLE {q}.address_registry (
            property_ref uuid NOT NULL, address_key bigint NOT NULL, postcode text NOT NULL,
            locality text NOT NULL, street_name text NOT NULL, street_type text NOT NULL,
            street_number_first integer NOT NULL, street_number_last integer,
            street_number_suffix text, unit_number text
        );
        INSERT INTO {q}.address_registry
        SELECT {registry_uuid}, address_key, lpad((2000 + address_key % 900)::text, 4, '0'),
               'LOCALITY '||(address_key % 300), 'STREET '||(address_key % 500), 'ST',
               (address_key % 5000)::integer + 1, NULL, NULL, NULL
        FROM generate_series(0, greatest(1000, {scale} / 20) - 1) address_key;
        INSERT INTO {q}.address_registry
        SELECT {registry_duplicate_uuid}, address_key,
               lpad((2000 + address_key % 900)::text, 4, '0'),
               'LOCALITY '||(address_key % 300), 'STREET '||(address_key % 500), 'ST',
               (address_key % 5000)::integer + 1, NULL, NULL, NULL
        FROM generate_series(0, greatest(1000, {scale} / 20) - 1) address_key
        WHERE address_key % 101 = 0;
        CREATE INDEX address_registry_exact_idx ON {q}.address_registry
            (postcode,locality,street_name,street_type,street_number_first,
             coalesce(street_number_last,-1),coalesce(street_number_suffix,''),
             coalesce(unit_number,'')) INCLUDE (property_ref);
        ANALYZE {q}.address_registry
    """
    target = f"""
        CREATE TABLE {q}.psi_target (
            source_business_key text NOT NULL, source_revision integer NOT NULL,
            source_row_sha256 text NOT NULL, source_ordinal bigint NOT NULL,
            property_ref uuid, postcode text, locality text, street_name text,
            street_type text, street_number_first integer, price_aud bigint,
            contract_date date, payload_padding text,
            PRIMARY KEY (source_business_key, source_revision)
        )
    """
    if variant == "jsonb-wide":
        stage = f"""
            CREATE TABLE {q}.psi_stage (ordinal bigint PRIMARY KEY, payload jsonb NOT NULL);
            INSERT INTO {q}.psi_stage
            SELECT i, jsonb_build_object(
                'source_business_key','sale-'||((i-1)/3),
                'source_row_sha256',md5('sale-'||((i-1)/3)||'-revision-'||
                    CASE WHEN i%3=0 THEN 2 ELSE 1 END),
                'property_ref',CASE WHEN i%29=0
                    THEN {_uuid_sql("'supplied-'||((i-1)/3)")}::text ELSE '' END,
                'postcode',lpad((2000 + ({address_key}) % 900)::text,4,'0'),
                'locality','LOCALITY '||(({address_key}) % 300),
                'street_name','STREET '||(({address_key}) % 500), 'street_type','ST',
                'street_number_first',(({address_key}) % 5000 + 1),
                'street_number_last','', 'street_number_suffix','', 'unit_number','',
                'price_aud',500000 + (i % 2000000),
                'contract_date',(date '1990-01-01' + (i % 13000)::integer)::text,
                'payload_padding',repeat('x',160))
            FROM generate_series(1,{scale}) i;
            ANALYZE {q}.psi_stage
        """
        return (("create_registry", registry), ("create_stage", stage), ("create_target", target))
    stage = f"""
        CREATE TABLE {q}.psi_stage_typed (
            ordinal bigint PRIMARY KEY, source_business_key text NOT NULL,
            source_row_sha256 text NOT NULL, property_ref uuid, address_key bigint NOT NULL,
            postcode text NOT NULL, locality text NOT NULL, street_name text NOT NULL,
            street_type text NOT NULL, street_number_first integer NOT NULL,
            street_number_last integer, street_number_suffix text, unit_number text,
            price_aud bigint NOT NULL, contract_date date NOT NULL, payload_padding text NOT NULL
        );
        INSERT INTO {q}.psi_stage_typed
        SELECT i, 'sale-'||((i-1)/3),
               md5('sale-'||((i-1)/3)||'-revision-'||CASE WHEN i%3=0 THEN 2 ELSE 1 END),
               CASE WHEN i%29=0 THEN {_uuid_sql("'supplied-'||((i-1)/3)")} ELSE NULL END,
               {address_key}, lpad((2000 + ({address_key}) % 900)::text,4,'0'),
               'LOCALITY '||(({address_key}) % 300), 'STREET '||(({address_key}) % 500),
               'ST', (({address_key}) % 5000 + 1)::integer, NULL, NULL, NULL,
               500000 + (i % 2000000), date '1990-01-01' + (i % 13000)::integer, repeat('x',160)
        FROM generate_series(1,{scale}) i;
        ANALYZE {q}.psi_stage_typed
    """
    identity = f"""
        CREATE TABLE {q}.psi_identity AS
        SELECT source_business_key,source_row_sha256,min(ordinal) AS first_ordinal
        FROM {q}.psi_stage_typed GROUP BY source_business_key,source_row_sha256;
        CREATE UNIQUE INDEX psi_identity_key_idx ON {q}.psi_identity
            (source_business_key,source_row_sha256);
        ANALYZE {q}.psi_identity
    """
    revisions = f"""
        CREATE TABLE {q}.psi_revisions AS
        SELECT source_business_key,source_row_sha256,first_ordinal,
               row_number() OVER (PARTITION BY source_business_key ORDER BY first_ordinal)::integer
                   AS source_revision
        FROM {q}.psi_identity;
        CREATE UNIQUE INDEX psi_revisions_idx ON {q}.psi_revisions
            (source_business_key,source_revision) INCLUDE (source_row_sha256,first_ordinal);
        ANALYZE {q}.psi_revisions
    """
    addresses = f"""
        CREATE TABLE {q}.psi_address_resolution AS
        SELECT source.address_key,min(registry.property_ref::text)::uuid AS exact_property_ref
        FROM (SELECT DISTINCT address_key,postcode,locality,street_name,street_type,
                     street_number_first,street_number_last,street_number_suffix,unit_number
              FROM {q}.psi_stage_typed WHERE property_ref IS NULL) source
        JOIN {q}.address_registry registry
          ON registry.postcode=source.postcode AND registry.locality=source.locality
         AND registry.street_name=source.street_name AND registry.street_type=source.street_type
         AND registry.street_number_first=source.street_number_first
         AND coalesce(registry.street_number_last,-1)=coalesce(source.street_number_last,-1)
         AND coalesce(registry.street_number_suffix,'')=coalesce(source.street_number_suffix,'')
         AND coalesce(registry.unit_number,'')=coalesce(source.unit_number,'')
        GROUP BY source.address_key HAVING count(*)=1;
        CREATE UNIQUE INDEX psi_address_resolution_idx ON {q}.psi_address_resolution(address_key);
        ANALYZE {q}.psi_address_resolution
    """
    return (
        ("create_registry", registry),
        ("typed_staging", stage),
        ("identity", identity),
        ("revisions", revisions),
        ("address_resolution", addresses),
        ("create_target", target),
    )


def _psi_materialisation_sql(schema: str, variant: str) -> str:
    q = _quoted_schema(schema)
    if variant == "jsonb-wide":
        return f"""
            WITH distinct_source_rows AS MATERIALIZED (
                SELECT DISTINCT ON (payload->>'source_business_key',payload->>'source_row_sha256')
                       payload,ordinal FROM {q}.psi_stage
                ORDER BY payload->>'source_business_key',payload->>'source_row_sha256',ordinal
            ), ranked AS MATERIALIZED (
                SELECT payload,ordinal,row_number() OVER (
                    PARTITION BY payload->>'source_business_key' ORDER BY ordinal)::integer revision
                FROM distinct_source_rows
            ), candidates AS (
                SELECT ranked.payload->>'source_business_key' business_key,ranked.revision,
                       min(registry.property_ref::text)::uuid exact_property_ref
                FROM ranked JOIN {q}.address_registry registry
                  ON registry.postcode=ranked.payload->>'postcode'
                 AND registry.locality=ranked.payload->>'locality'
                 AND registry.street_name=ranked.payload->>'street_name'
                 AND registry.street_type=ranked.payload->>'street_type'
                 AND registry.street_number_first=(ranked.payload->>'street_number_first')::integer
                 AND coalesce(registry.street_number_last,-1)=coalesce(
                     nullif(ranked.payload->>'street_number_last','')::integer,-1)
                 AND coalesce(registry.street_number_suffix,'')=coalesce(
                     ranked.payload->>'street_number_suffix','')
                 AND coalesce(registry.unit_number,'')=coalesce(ranked.payload->>'unit_number','')
                WHERE nullif(ranked.payload->>'property_ref','') IS NULL
                GROUP BY ranked.payload->>'source_business_key',ranked.revision HAVING count(*)=1
            )
            INSERT INTO {q}.psi_target
            SELECT ranked.payload->>'source_business_key',ranked.revision,
                   ranked.payload->>'source_row_sha256',ranked.ordinal,
                   coalesce(nullif(ranked.payload->>'property_ref','')::uuid,
                            candidates.exact_property_ref),
                   ranked.payload->>'postcode',ranked.payload->>'locality',
                   ranked.payload->>'street_name',ranked.payload->>'street_type',
                   (ranked.payload->>'street_number_first')::integer,
                   (ranked.payload->>'price_aud')::bigint,
                   (ranked.payload->>'contract_date')::date,ranked.payload->>'payload_padding'
            FROM ranked LEFT JOIN candidates
              ON candidates.business_key=ranked.payload->>'source_business_key'
             AND candidates.revision=ranked.revision
            ORDER BY ranked.payload->>'source_business_key',ranked.revision
        """
    return f"""
        INSERT INTO {q}.psi_target
        SELECT revision.source_business_key,revision.source_revision,revision.source_row_sha256,
               revision.first_ordinal,coalesce(source.property_ref,resolution.exact_property_ref),
               source.postcode,source.locality,source.street_name,source.street_type,
               source.street_number_first,source.price_aud,source.contract_date,
               source.payload_padding
        FROM {q}.psi_revisions revision
        JOIN {q}.psi_stage_typed source
          ON source.ordinal=revision.first_ordinal
        LEFT JOIN {q}.psi_address_resolution resolution ON resolution.address_key=source.address_key
    """


def _bocsar_setup_sql(schema: str, scale: int, variant: str) -> tuple[tuple[str, str], ...]:
    q = _quoted_schema(schema)
    target = f"""
        CREATE TABLE {q}.bocsar_target (
            geography_kind text NOT NULL,geography_value text NOT NULL,
            source_category_key text NOT NULL,month date NOT NULL,count_value integer,
            source_row_sha256 text NOT NULL,coverage_present boolean NOT NULL,
            payload_padding text NOT NULL,
            PRIMARY KEY (geography_kind,geography_value,source_category_key,month)
        )
    """
    if variant == "jsonb-ordered":
        stage = f"""
            CREATE TABLE {q}.bocsar_stage (ordinal bigint PRIMARY KEY,payload jsonb NOT NULL);
            INSERT INTO {q}.bocsar_stage
            SELECT i,jsonb_build_object(
                'geography_kind',CASE WHEN i%2=0 THEN 'postcode' ELSE 'suburb' END,
                'geography_value',CASE WHEN i%2=0 THEN lpad((2000+i%800)::text,4,'0')
                                             ELSE 'SUBURB '||(i%1200) END,
                'source_category_key','category-'||(i%180),
                'month',(date '1995-01-01'+((i%360)*interval '1 month'))::date::text,
                'count_value',CASE WHEN i%17=0 THEN 0 ELSE i%41 END,
                'source_row_sha256',md5(i::text), 'coverage_present',true,
                'payload_padding',repeat('c',96)) FROM generate_series(1,{scale}) i;
            ANALYZE {q}.bocsar_stage
        """
        return (("jsonb_staging", stage), ("create_target", target))
    stage = f"""
        CREATE TABLE {q}.bocsar_stage_typed (
            ordinal bigint PRIMARY KEY,geography_kind text NOT NULL,geography_value text NOT NULL,
            source_category_key text NOT NULL,month date NOT NULL,count_value integer,
            source_row_sha256 text NOT NULL,coverage_present boolean NOT NULL,
            payload_padding text NOT NULL
        );
        INSERT INTO {q}.bocsar_stage_typed
        SELECT i,CASE WHEN i%2=0 THEN 'postcode' ELSE 'suburb' END,
               CASE WHEN i%2=0 THEN lpad((2000+i%800)::text,4,'0') ELSE 'SUBURB '||(i%1200) END,
               'category-'||(i%180),(date '1995-01-01'+((i%360)*interval '1 month'))::date,
               CASE WHEN i%17=0 THEN 0 ELSE i%41 END,md5(i::text),true,repeat('c',96)
        FROM generate_series(1,{scale}) i;
        ANALYZE {q}.bocsar_stage_typed
    """
    return (("typed_staging", stage), ("create_target", target))


def _bocsar_materialisation_sql(schema: str, variant: str) -> str:
    q = _quoted_schema(schema)
    if variant == "jsonb-ordered":
        return f"""
            INSERT INTO {q}.bocsar_target
            SELECT payload->>'geography_kind',payload->>'geography_value',
                   payload->>'source_category_key',(payload->>'month')::date,
                   (payload->>'count_value')::integer,payload->>'source_row_sha256',
                   (payload->>'coverage_present')::boolean,payload->>'payload_padding'
            FROM {q}.bocsar_stage ORDER BY ordinal
            ON CONFLICT (geography_kind,geography_value,source_category_key,month) DO NOTHING
        """
    return f"""
        INSERT INTO {q}.bocsar_target
        SELECT geography_kind,geography_value,source_category_key,month,count_value,
               source_row_sha256,coverage_present,payload_padding
        FROM {q}.bocsar_stage_typed
        ON CONFLICT (geography_kind,geography_value,source_category_key,month) DO NOTHING
    """


def benchmark_sql(spec: RunSpec, schema: str) -> tuple[tuple[tuple[str, str], ...], str]:
    """Return setup phases and the one measured materialisation statement."""
    if spec.dataset == "psi":
        return _psi_setup_sql(schema, spec.scale, spec.variant), _psi_materialisation_sql(
            schema, spec.variant
        )
    return _bocsar_setup_sql(schema, spec.scale, spec.variant), _bocsar_materialisation_sql(
        schema, spec.variant
    )


def _snapshot(connection: Any, backend_pid: int | None = None) -> dict[str, Any]:
    snapshot: dict[str, Any] = {"captured_at": datetime.now(UTC).isoformat()}
    queries = {
        "database": "SELECT to_jsonb(s) FROM pg_stat_database s WHERE datname=current_database()",
        "wal": "SELECT to_jsonb(s) FROM pg_stat_wal s",
        "checkpoints": "SELECT to_jsonb(s) FROM pg_stat_bgwriter s",
        "io": "SELECT coalesce(jsonb_agg(to_jsonb(s)),'[]'::jsonb) FROM pg_stat_io s",
        "temporary_files": """SELECT jsonb_build_object('count',count(*),'bytes',
            coalesce(sum(size),0)) FROM pg_ls_tmpdir()""",
    }
    with connection.cursor() as cursor:
        for name, query in queries.items():
            try:
                cursor.execute(query)
                snapshot[name] = cursor.fetchone()[0]
            except Exception as exc:
                connection.rollback()
                snapshot[name] = {"unavailable": type(exc).__name__}
        if backend_pid is not None:
            cursor.execute(
                """SELECT jsonb_build_object('state',state,'wait_event_type',wait_event_type,
                   'wait_event',wait_event,'backend_type',backend_type)
                   FROM pg_stat_activity WHERE pid=%s""",
                (backend_pid,),
            )
            row = cursor.fetchone()
            snapshot["activity"] = row[0] if row else {"state": "finished"}
            activity = snapshot["activity"]
            if isinstance(activity, dict):
                snapshot["cpu_or_running"] = (
                    activity.get("state") == "active" and activity.get("wait_event_type") is None
                )
    return snapshot


def _relation_bytes(connection: Any, schema: str) -> int:
    with connection.cursor() as cursor:
        cursor.execute(
            """SELECT coalesce(sum(pg_total_relation_size(
                   format('%%I.%%I',schemaname,tablename))),0)
               FROM pg_tables WHERE schemaname=%s""",
            (schema,),
        )
        return int(cursor.fetchone()[0])


def _target_evidence(connection: Any, schema: str, dataset: str) -> dict[str, Any]:
    q = _quoted_schema(schema)
    table = "psi_target" if dataset == "psi" else "bocsar_target"
    identity = (
        "source_business_key||':'||source_revision"
        if dataset == "psi"
        else "geography_kind||':'||geography_value||':'||source_category_key||':'||month::text"
    )
    with connection.cursor() as cursor:
        cursor.execute(
            f"""SELECT count(*),md5(count(*)::text||':'||
                coalesce(sum(hashtextextended({identity},0))::text,'0')) FROM {q}.{table}"""
        )
        count, fingerprint = cursor.fetchone()
    return {"row_count": int(count), "identity_fingerprint": str(fingerprint)}


def _write_json(path: Path, payload: object) -> None:
    content = json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n"
    if len(content.encode("utf-8")) > MAX_SUMMARY_BYTES:
        raise ValueError("benchmark summary exceeds the bounded schema size")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def execute_run(
    database_url: str,
    spec: RunSpec,
    output: Path,
    *,
    connector: Callable[[str], Any],
    clock: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    """Execute one reset run with server/client deadlines and best-effort cleanup evidence."""
    schema = _schema_name(spec)
    setup_phases, materialisation = benchmark_sql(spec, schema)
    summary: dict[str, Any] = {
        "schema_version": 1,
        "run_id": spec.run_id,
        "dataset": spec.dataset,
        "scale": spec.scale,
        "variant": spec.variant,
        "repetition": spec.repetition,
        "executed": True,
        "status": "failed",
        "phase_timings_seconds": {},
        "progress_snapshots": [],
        "cleanup": {
            "cancel_requested": False,
            "rollback_completed": False,
            "schema_dropped": False,
        },
    }
    control = connector(database_url)
    worker = connector(database_url)
    q = _quoted_schema(schema)
    try:
        control.autocommit = True
        worker.autocommit = False
        with control.cursor() as cursor:
            cursor.execute(f"CREATE SCHEMA {q}")
        before = _snapshot(control)
        summary["before"] = before
        for phase, sql in setup_phases:
            started = clock()
            with worker.cursor() as cursor:
                cursor.execute(sql)
            worker.commit()
            summary["phase_timings_seconds"][phase] = round(clock() - started, 6)
        summary["relation_bytes_before_materialisation"] = _relation_bytes(control, schema)
        backend_pid = int(worker.info.backend_pid)
        result: dict[str, Any] = {}
        failure: list[BaseException] = []

        def materialise() -> None:
            try:
                with worker.cursor() as cursor:
                    cursor.execute(
                        f"SET LOCAL statement_timeout='{MATERIALISATION_DEADLINE_SECONDS}s'"
                    )
                    cursor.execute(
                        "EXPLAIN (ANALYZE, BUFFERS, WAL, SETTINGS, SUMMARY, FORMAT JSON) "
                        + materialisation
                    )
                    result["plan"] = cursor.fetchone()[0]
                worker.commit()
            except BaseException as exc:  # retained for the coordinating thread
                failure.append(exc)

        started = clock()
        thread = threading.Thread(target=materialise, name=spec.run_id, daemon=True)
        thread.start()
        summary["progress_snapshots"].append(_snapshot(control, backend_pid))
        deadline = started + MATERIALISATION_DEADLINE_SECONDS
        next_report = started + PROGRESS_INTERVAL_SECONDS
        while thread.is_alive():
            remaining = max(0.0, min(next_report, deadline) - clock())
            thread.join(timeout=min(1.0, remaining) if remaining else 0.0)
            now = clock()
            if not thread.is_alive():
                break
            if now >= deadline:
                summary["cleanup"]["cancel_requested"] = True
                worker.cancel()
                thread.join(timeout=30)
                if thread.is_alive():
                    raise RuntimeError(
                        "database statement did not stop within 30 seconds of cancel"
                    )
                break
            if now >= next_report:
                snapshot = _snapshot(control, backend_pid)
                summary["progress_snapshots"].append(snapshot)
                print(
                    f"{spec.run_id}: {int(now - started)}s elapsed; "
                    f"wait={snapshot.get('activity', {}).get('wait_event_type')}/"
                    f"{snapshot.get('activity', {}).get('wait_event')}",
                    flush=True,
                )
                next_report += PROGRESS_INTERVAL_SECONDS
        elapsed = clock() - started
        summary["phase_timings_seconds"]["materialisation"] = round(elapsed, 6)
        if failure:
            worker.rollback()
            summary["cleanup"]["rollback_completed"] = True
            if summary["cleanup"]["cancel_requested"]:
                summary["status"] = "cancelled"
                summary["error_type"] = type(failure[0]).__name__
            else:
                raise failure[0]
        elif summary["cleanup"]["cancel_requested"]:
            worker.rollback()
            summary["cleanup"]["rollback_completed"] = True
            summary["status"] = "cancelled"
        else:
            plan = result["plan"]
            _write_json(output / "plans" / f"{spec.run_id}.explain.json", plan)
            summary["plan_nodes"] = extract_plan_nodes(plan)
            summary["plan_temp_blocks"] = {
                "read": sum(node["temp_read_blocks"] for node in summary["plan_nodes"]),
                "written": sum(node["temp_written_blocks"] for node in summary["plan_nodes"]),
            }
            summary["elapsed_seconds"] = round(elapsed, 6)
            summary["rows_per_second"] = round(spec.scale / elapsed, 3) if elapsed > 0 else None
            summary["target"] = _target_evidence(control, schema, spec.dataset)
            summary["relation_bytes_after_materialisation"] = _relation_bytes(control, schema)
            summary["status"] = "succeeded"
    except BaseException as exc:
        try:
            worker.rollback()
            summary["cleanup"]["rollback_completed"] = True
        except Exception:
            pass
        summary["status"] = "failed"
        summary["error_type"] = type(exc).__name__
        summary["error"] = str(exc)[:500]
    finally:
        cleanup_started = clock()
        try:
            after = _snapshot(control)
            summary["after"] = after
            summary["metric_deltas"] = metric_deltas(summary.get("before"), after)
            relation_after = _relation_bytes(control, schema)
            summary["relation_bytes_after_materialisation"] = relation_after
            summary["relation_growth_bytes"] = relation_after - int(
                summary.get("relation_bytes_before_materialisation", 0)
            )
            before_snapshot = summary.get("before")
            before_temp = (
                before_snapshot.get("temporary_files", {})
                if isinstance(before_snapshot, dict)
                else {}
            )
            after_temp = after.get("temporary_files", {})
            summary["cleanup"]["temporary_files_before"] = before_temp
            summary["cleanup"]["temporary_files_after_statement"] = after_temp
            with control.cursor() as cursor:
                cursor.execute(f"DROP SCHEMA IF EXISTS {q} CASCADE")
                cursor.execute(
                    "SELECT count(*) FROM pg_namespace WHERE nspname=%s",
                    (schema,),
                )
                summary["cleanup"]["remaining_schemas"] = int(cursor.fetchone()[0])
            summary["cleanup"]["schema_dropped"] = summary["cleanup"]["remaining_schemas"] == 0
        except Exception as exc:
            summary["cleanup"]["cleanup_error_type"] = type(exc).__name__
        summary["phase_timings_seconds"]["cleanup"] = round(clock() - cleanup_started, 6)
        worker.close()
        control.close()
    validate_run_summary(summary)
    _write_json(output / "runs" / f"{spec.run_id}.summary.json", summary)
    return summary


def _database_name(database_url: str, connector: Callable[[str], Any]) -> str:
    connection = connector(database_url)
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT current_database()")
            return str(cursor.fetchone()[0])
    finally:
        connection.close()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("plan", "run"))
    parser.add_argument("--dataset", required=True, choices=tuple(VARIANTS))
    parser.add_argument("--scale", required=True, type=int, choices=SCALES)
    parser.add_argument("--repetitions", type=int, default=MIN_REPETITIONS)
    parser.add_argument("--variant", action="append", default=[])
    parser.add_argument("--gate-evidence", type=Path)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument(
        "--database-url", default=os.environ.get("PROPERTYSCOPE_BENCHMARK_DATABASE_URL")
    )
    parser.add_argument("--confirm-database")
    parser.add_argument("--confirm-disposable", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        specs = benchmark_plan(
            arguments.dataset, arguments.scale, arguments.repetitions, arguments.variant
        )
        variants = tuple(dict.fromkeys(spec.variant for spec in specs))
        if arguments.scale == 1_000_000:
            if arguments.gate_evidence is None:
                raise ValueError("1m runs require --gate-evidence from the matching 100k suite")
            validate_million_gate(arguments.gate_evidence, arguments.dataset, variants)
        if arguments.mode == "plan":
            suite = planned_suite(specs)
            validate_suite_summary(suite)
            print(json.dumps(suite, indent=2))
            return 0
        if not arguments.database_url:
            raise ValueError(
                "run mode requires --database-url or PROPERTYSCOPE_BENCHMARK_DATABASE_URL"
            )
        if not arguments.confirm_disposable or not arguments.confirm_database:
            raise ValueError(
                "run mode requires --confirm-disposable and the exact --confirm-database name"
            )
        import psycopg

        actual_database = _database_name(arguments.database_url, psycopg.connect)
        if actual_database != arguments.confirm_database:
            raise ValueError(f"database confirmation mismatch: connected to {actual_database!r}")
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        output = arguments.output / f"{arguments.dataset}-{arguments.scale}-{stamp}"
        summaries = [
            execute_run(
                arguments.database_url,
                spec,
                output,
                connector=psycopg.connect,
            )
            for spec in specs
        ]
        suite = {
            **planned_suite(specs),
            "mode": "executed",
            "executed": True,
            "database": actual_database,
            "generated_at": datetime.now(UTC).isoformat(),
            "runs": summaries,
            "claims": [],
        }
        validate_suite_summary(suite)
        _write_json(output / "suite-summary.json", suite)
        print(f"Wrote benchmark evidence to {output}")
        return 0 if all(item["status"] == "succeeded" for item in summaries) else 1
    except ValueError as exc:
        print(f"Benchmark configuration rejected: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
