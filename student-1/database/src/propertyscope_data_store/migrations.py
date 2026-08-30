"""Small deterministic SQL migration runner."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from hashlib import sha256
from importlib.resources import files
from typing import Any

from psycopg import Connection

MIGRATION_PACKAGE = "propertyscope_data_store.sql"
SCHEMA_FINGERPRINT_POLICY_VERSION = "propertyscope-postgresql-schema.v2"

_OWNED_SCHEMAS = ("ops", "registry", "serving", "stage", "warehouse")
_REQUIRED_EXTENSIONS = ("pg_trgm", "pgcrypto", "postgis")


def migrate(connection: Connection[Any]) -> None:
    """Apply checked, immutable SQL migrations in lexical order."""
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS public.propertyscope_schema_migration (
            version TEXT PRIMARY KEY,
            checksum TEXT NOT NULL,
            applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    root = files(MIGRATION_PACKAGE)
    for resource in sorted(root.iterdir(), key=lambda item: item.name):
        if not resource.name.endswith(".sql"):
            continue
        sql = resource.read_text(encoding="utf-8")
        checksum = sha256(sql.encode()).hexdigest()
        existing = connection.execute(
            "SELECT checksum FROM public.propertyscope_schema_migration WHERE version = %s",
            (resource.name,),
        ).fetchone()
        if existing is not None:
            existing_checksum = existing["checksum"] if isinstance(existing, dict) else existing[0]
            if existing_checksum != checksum:
                raise RuntimeError(f"migration checksum changed: {resource.name}")
            continue
        connection.execute(sql)
        connection.execute(
            "INSERT INTO public.propertyscope_schema_migration(version, checksum) VALUES (%s, %s)",
            (resource.name, checksum),
        )
    connection.commit()


def schema_fingerprint(connection: Connection[Any]) -> str:
    """Return the v2 fingerprint of the owned PostgreSQL schema contract.

    The policy favours structured catalogue values over rendered DDL. PostgreSQL must
    still decompile expressions used by defaults, checks, expression/partial indexes and
    views; those fragments are lexically canonicalised before they enter the manifest.
    """
    relations = connection.execute(
        """
        SELECT namespace.nspname AS schema_name,
               relation.relname AS relation_name,
               relation.relkind AS relation_kind,
               relation.relpersistence AS persistence,
               relation.relispartition AS is_partition
        FROM pg_catalog.pg_class AS relation
        JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = relation.relnamespace
        WHERE namespace.nspname IN ('ops', 'registry', 'warehouse', 'serving', 'stage')
          AND relation.relkind IN ('r', 'p', 'v', 'm')
        ORDER BY namespace.nspname, relation.relname
        """
    ).fetchall()
    schemas = connection.execute(
        """
        SELECT namespace.nspname AS schema_name
        FROM pg_catalog.pg_namespace AS namespace
        WHERE namespace.nspname IN ('ops', 'registry', 'warehouse', 'serving', 'stage')
        ORDER BY namespace.nspname
        """
    ).fetchall()
    columns = connection.execute(
        """
        SELECT table_schema AS schema_name,
               table_name AS relation_name,
               ordinal_position,
               column_name,
               data_type,
               udt_schema AS type_schema,
               udt_name AS type_name,
               domain_schema,
               domain_name,
               character_maximum_length,
               numeric_precision,
               numeric_precision_radix,
               numeric_scale,
               datetime_precision,
               interval_type,
               interval_precision,
               collation_schema,
               collation_name,
               is_nullable,
               column_default,
               is_identity,
               identity_generation,
               identity_start,
               identity_increment,
               identity_minimum,
               identity_maximum,
               identity_cycle,
               is_generated,
               generation_expression,
               CASE WHEN udt_schema = 'public' AND udt_name = 'geometry'
                    THEN postgis_typmod_type(catalog_attribute.atttypmod)
                    ELSE NULL END AS spatial_type,
               CASE WHEN udt_schema = 'public' AND udt_name = 'geometry'
                    THEN postgis_typmod_srid(catalog_attribute.atttypmod)
                    ELSE NULL END AS spatial_srid,
               CASE WHEN udt_schema = 'public' AND udt_name = 'geometry'
                    THEN postgis_typmod_dims(catalog_attribute.atttypmod)
                    ELSE NULL END AS spatial_dimensions
        FROM information_schema.columns
        LEFT JOIN pg_catalog.pg_namespace AS catalog_schema
          ON catalog_schema.nspname = table_schema
        LEFT JOIN pg_catalog.pg_class AS catalog_relation
          ON catalog_relation.relnamespace = catalog_schema.oid
         AND catalog_relation.relname = table_name
        LEFT JOIN pg_catalog.pg_attribute AS catalog_attribute
          ON catalog_attribute.attrelid = catalog_relation.oid
         AND catalog_attribute.attname = column_name
         AND catalog_attribute.attnum > 0
         AND NOT catalog_attribute.attisdropped
        WHERE table_schema IN ('ops', 'registry', 'warehouse', 'serving', 'stage')
        ORDER BY table_schema, table_name, ordinal_position
        """
    ).fetchall()
    indexes = connection.execute(
        """
        SELECT namespace.nspname AS schema_name,
               relation.relname AS relation_name,
               index_relation.relname AS index_name,
               access_method.amname AS access_method,
               index.indisunique AS is_unique,
               index.indisprimary AS is_primary,
               index.indisvalid AS is_valid,
               index.indisready AS is_ready,
               index.indisclustered AS is_clustered,
               index.indisreplident AS is_replica_identity,
               index.indnkeyatts AS key_attribute_count,
               pg_get_expr(index.indpred, index.indrelid, false) AS predicate
        FROM pg_catalog.pg_index AS index
        JOIN pg_catalog.pg_class AS relation ON relation.oid = index.indrelid
        JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = relation.relnamespace
        JOIN pg_catalog.pg_class AS index_relation ON index_relation.oid = index.indexrelid
        JOIN pg_catalog.pg_am AS access_method ON access_method.oid = index_relation.relam
        WHERE namespace.nspname IN ('ops', 'registry', 'warehouse', 'serving', 'stage')
        ORDER BY namespace.nspname, relation.relname, index_relation.relname
        """
    ).fetchall()
    index_attributes = connection.execute(
        """
        SELECT namespace.nspname AS schema_name,
               relation.relname AS relation_name,
               index_relation.relname AS index_name,
               key.ordinality AS ordinal_position,
               key.ordinality > index.indnkeyatts AS is_included,
               attribute.attname AS column_name,
               CASE WHEN key.attribute_number = 0
                    THEN pg_get_indexdef(index.indexrelid, key.ordinality::integer, false)
                    ELSE NULL END AS expression,
               operator_namespace.nspname AS operator_class_schema,
               operator_class.opcname AS operator_class_name,
               collation_namespace.nspname AS collation_schema,
               collation_record.collname AS collation_name,
               CASE WHEN key.ordinality <= index.indnkeyatts
                    THEN (index.indoption[(key.ordinality - 1)::integer] & 1) = 1
                    ELSE false END AS is_descending,
               CASE WHEN key.ordinality <= index.indnkeyatts
                    THEN (index.indoption[(key.ordinality - 1)::integer] & 2) = 2
                    ELSE false END AS nulls_first
        FROM pg_catalog.pg_index AS index
        JOIN pg_catalog.pg_class AS relation ON relation.oid = index.indrelid
        JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = relation.relnamespace
        JOIN pg_catalog.pg_class AS index_relation ON index_relation.oid = index.indexrelid
        CROSS JOIN LATERAL unnest(index.indkey)
            WITH ORDINALITY AS key(attribute_number, ordinality)
        LEFT JOIN pg_catalog.pg_attribute AS attribute
          ON attribute.attrelid = relation.oid
         AND attribute.attnum = key.attribute_number
        LEFT JOIN pg_catalog.pg_opclass AS operator_class
          ON operator_class.oid = index.indclass[(key.ordinality - 1)::integer]
        LEFT JOIN pg_catalog.pg_namespace AS operator_namespace
          ON operator_namespace.oid = operator_class.opcnamespace
        LEFT JOIN pg_catalog.pg_collation AS collation_record
          ON collation_record.oid = index.indcollation[(key.ordinality - 1)::integer]
        LEFT JOIN pg_catalog.pg_namespace AS collation_namespace
          ON collation_namespace.oid = collation_record.collnamespace
        WHERE namespace.nspname IN ('ops', 'registry', 'warehouse', 'serving', 'stage')
        ORDER BY namespace.nspname, relation.relname, index_relation.relname, key.ordinality
        """
    ).fetchall()
    constraints = connection.execute(
        """
        SELECT namespace.nspname AS schema_name,
               relation.relname AS relation_name,
               constraint_record.conname AS constraint_name,
               constraint_record.contype AS constraint_type,
               constraint_record.condeferrable AS is_deferrable,
               constraint_record.condeferred AS initially_deferred,
               constraint_record.convalidated AS is_validated,
               constraint_record.connoinherit AS no_inherit,
               referenced_namespace.nspname AS referenced_schema,
               referenced_relation.relname AS referenced_relation,
               constraint_record.confmatchtype AS foreign_key_match_type,
               constraint_record.confupdtype AS foreign_key_update_action,
               constraint_record.confdeltype AS foreign_key_delete_action,
               CASE WHEN constraint_record.contype = 'c'
                    THEN pg_get_expr(constraint_record.conbin, constraint_record.conrelid, false)
                    ELSE NULL END AS check_expression
        FROM pg_catalog.pg_constraint AS constraint_record
        JOIN pg_catalog.pg_class AS relation ON relation.oid = constraint_record.conrelid
        JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = relation.relnamespace
        LEFT JOIN pg_catalog.pg_class AS referenced_relation
          ON referenced_relation.oid = constraint_record.confrelid
        LEFT JOIN pg_catalog.pg_namespace AS referenced_namespace
          ON referenced_namespace.oid = referenced_relation.relnamespace
        WHERE namespace.nspname IN ('ops', 'registry', 'warehouse', 'serving', 'stage')
        ORDER BY namespace.nspname, relation.relname, constraint_record.conname
        """
    ).fetchall()
    constraint_attributes = connection.execute(
        """
        SELECT namespace.nspname AS schema_name,
               relation.relname AS relation_name,
               constraint_record.conname AS constraint_name,
               key.ordinality AS ordinal_position,
               attribute.attname AS column_name,
               referenced_attribute.attname AS referenced_column_name,
               exclusion_namespace.nspname AS exclusion_operator_schema,
               exclusion_operator.oprname AS exclusion_operator_name
        FROM pg_catalog.pg_constraint AS constraint_record
        JOIN pg_catalog.pg_class AS relation ON relation.oid = constraint_record.conrelid
        JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = relation.relnamespace
        CROSS JOIN LATERAL unnest(constraint_record.conkey)
            WITH ORDINALITY AS key(attribute_number, ordinality)
        JOIN pg_catalog.pg_attribute AS attribute
          ON attribute.attrelid = relation.oid
         AND attribute.attnum = key.attribute_number
        LEFT JOIN pg_catalog.pg_attribute AS referenced_attribute
          ON referenced_attribute.attrelid = constraint_record.confrelid
         AND referenced_attribute.attnum = constraint_record.confkey[key.ordinality::integer]
        LEFT JOIN pg_catalog.pg_operator AS exclusion_operator
          ON exclusion_operator.oid = constraint_record.conexclop[key.ordinality::integer]
        LEFT JOIN pg_catalog.pg_namespace AS exclusion_namespace
          ON exclusion_namespace.oid = exclusion_operator.oprnamespace
        WHERE namespace.nspname IN ('ops', 'registry', 'warehouse', 'serving', 'stage')
        ORDER BY namespace.nspname, relation.relname, constraint_record.conname, key.ordinality
        """
    ).fetchall()
    views = connection.execute(
        """
        SELECT namespace.nspname AS schema_name,
               relation.relname AS relation_name,
               relation.relkind AS relation_kind,
               pg_get_viewdef(relation.oid, false) AS query_expression
        FROM pg_catalog.pg_class AS relation
        JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = relation.relnamespace
        WHERE namespace.nspname IN ('ops', 'registry', 'warehouse', 'serving', 'stage')
          AND relation.relkind IN ('v', 'm')
        ORDER BY namespace.nspname, relation.relname
        """
    ).fetchall()
    extensions = connection.execute(
        """
        SELECT extension.extname AS extension_name,
               extension.extversion AS extension_version,
               namespace.nspname AS installed_schema
        FROM pg_catalog.pg_extension AS extension
        JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = extension.extnamespace
        WHERE extension.extname IN ('postgis', 'pg_trgm', 'pgcrypto')
        ORDER BY extension.extname
        """
    ).fetchall()

    records = [
        *_fingerprint_records("schema", schemas, ("schema_name",)),
        *_fingerprint_records(
            "relation",
            relations,
            ("schema_name", "relation_name", "relation_kind", "persistence", "is_partition"),
        ),
        *_fingerprint_records(
            "column",
            columns,
            (
                "schema_name",
                "relation_name",
                "ordinal_position",
                "column_name",
                "data_type",
                "type_schema",
                "type_name",
                "domain_schema",
                "domain_name",
                "character_maximum_length",
                "numeric_precision",
                "numeric_precision_radix",
                "numeric_scale",
                "datetime_precision",
                "interval_type",
                "interval_precision",
                "collation_schema",
                "collation_name",
                "is_nullable",
                "column_default",
                "is_identity",
                "identity_generation",
                "identity_start",
                "identity_increment",
                "identity_minimum",
                "identity_maximum",
                "identity_cycle",
                "is_generated",
                "generation_expression",
                "spatial_type",
                "spatial_srid",
                "spatial_dimensions",
            ),
            expression_fields=("column_default", "generation_expression"),
        ),
        *_fingerprint_records(
            "index",
            indexes,
            (
                "schema_name",
                "relation_name",
                "index_name",
                "access_method",
                "is_unique",
                "is_primary",
                "is_valid",
                "is_ready",
                "is_clustered",
                "is_replica_identity",
                "key_attribute_count",
                "predicate",
            ),
            expression_fields=("predicate",),
        ),
        *_fingerprint_records(
            "index_attribute",
            index_attributes,
            (
                "schema_name",
                "relation_name",
                "index_name",
                "ordinal_position",
                "is_included",
                "column_name",
                "expression",
                "operator_class_schema",
                "operator_class_name",
                "collation_schema",
                "collation_name",
                "is_descending",
                "nulls_first",
            ),
            expression_fields=("expression",),
        ),
        *_fingerprint_records(
            "constraint",
            constraints,
            (
                "schema_name",
                "relation_name",
                "constraint_name",
                "constraint_type",
                "is_deferrable",
                "initially_deferred",
                "is_validated",
                "no_inherit",
                "referenced_schema",
                "referenced_relation",
                "foreign_key_match_type",
                "foreign_key_update_action",
                "foreign_key_delete_action",
                "check_expression",
            ),
            expression_fields=("check_expression",),
        ),
        *_fingerprint_records(
            "constraint_attribute",
            constraint_attributes,
            (
                "schema_name",
                "relation_name",
                "constraint_name",
                "ordinal_position",
                "column_name",
                "referenced_column_name",
                "exclusion_operator_schema",
                "exclusion_operator_name",
            ),
        ),
        *_fingerprint_records(
            "view",
            views,
            ("schema_name", "relation_name", "relation_kind", "query_expression"),
            expression_fields=("query_expression",),
        ),
        *_fingerprint_records(
            "extension",
            extensions,
            ("extension_name", "extension_version", "installed_schema"),
        ),
    ]
    records.sort(key=_canonical_json)
    payload = _canonical_json(
        {
            "policy_version": SCHEMA_FINGERPRINT_POLICY_VERSION,
            "owned_schemas": _OWNED_SCHEMAS,
            "required_extensions": _REQUIRED_EXTENSIONS,
            "records": records,
        }
    )
    return sha256(payload.encode()).hexdigest()


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        default=str,
        separators=(",", ":"),
        sort_keys=True,
    )


def _fingerprint_records(
    kind: str,
    rows: Sequence[Mapping[str, Any] | Sequence[Any]],
    fields: tuple[str, ...],
    *,
    expression_fields: tuple[str, ...] = (),
) -> list[dict[str, Any]]:
    """Canonicalise tuple rows and the store's real ``dict_row`` results identically."""
    records: list[dict[str, Any]] = []
    for row in rows:
        values = [row[field] for field in fields] if isinstance(row, Mapping) else list(row)
        if len(values) != len(fields):
            raise ValueError(
                f"{kind} fingerprint row has {len(values)} values; expected {len(fields)}"
            )
        records.append(
            {
                "kind": kind,
                "values": [
                    _canonicalise_sql_expression(value) if field in expression_fields else value
                    for field, value in zip(fields, values, strict=True)
                ],
            }
        )
    return records


_DOLLAR_QUOTE_START = re.compile(r"\$[A-Za-z_][A-Za-z0-9_]*\$|\$\$")


def _canonicalise_sql_expression(value: Any) -> Any:
    """Collapse insignificant expression whitespace without changing quoted values."""
    if not isinstance(value, str):
        return value
    result: list[str] = []
    whitespace_pending = False
    quote: str | None = None
    index = 0
    while index < len(value):
        if quote is not None:
            if quote.startswith("$") and value.startswith(quote, index):
                result.append(quote)
                index += len(quote)
                quote = None
                continue
            character = value[index]
            result.append(character)
            index += 1
            if quote in {"'", '"'} and character == quote:
                if index < len(value) and value[index] == quote:
                    result.append(value[index])
                    index += 1
                else:
                    quote = None
            continue

        character = value[index]
        dollar_quote = _DOLLAR_QUOTE_START.match(value, index)
        if dollar_quote is not None:
            if whitespace_pending and result:
                result.append(" ")
            whitespace_pending = False
            quote = dollar_quote.group(0)
            result.append(quote)
            index = dollar_quote.end()
        elif character in {"'", '"'}:
            if whitespace_pending and result:
                result.append(" ")
            whitespace_pending = False
            quote = character
            result.append(character)
            index += 1
        elif character.isspace():
            whitespace_pending = True
            index += 1
        else:
            if whitespace_pending and result:
                result.append(" ")
            whitespace_pending = False
            result.append(character)
            index += 1
    return "".join(result).strip()
