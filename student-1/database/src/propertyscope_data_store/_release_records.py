"""Release records and bounded immutable-generation projections."""

# SQL statements stay line-oriented so release evidence remains reviewable.

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from contextlib import AbstractContextManager
from datetime import UTC, datetime
from typing import Any, Protocol

from psycopg import Connection, errors

from propertyscope_data_store.errors import ConflictError, NotFoundError, ValidationError
from propertyscope_data_store.persistence_support import json_document as _json
from propertyscope_data_store.persistence_support import normalise_row as _dict
from propertyscope_data_store.query_specs import (
    PREVIEW_SPECS,
    encode_export_cursor,
    normalise_product_rows,
    release_export_query,
    release_product_query,
)

JsonObject = dict[str, Any]
RELEASE_LIFECYCLES = {
    "review": ["validated", "candidate", "review", "review_required", "awaiting_review"],
    "published": ["accepted"],
    "rejected": ["rejected"],
}


class _ReleaseRecordOwner(Protocol):
    """Narrow transaction and query surface owned by the repository facade."""

    def connection(self) -> AbstractContextManager[Connection[Any]]: ...

    def _fetch_all(self, query: str, params: Sequence[Any]) -> list[JsonObject]: ...

    def _required(self, query: str, params: Sequence[Any]) -> JsonObject: ...

    def _delete(self, schema_name: str, table_name: str, aggregate_id: uuid.UUID) -> None: ...

    def get_release(self, release_id: uuid.UUID) -> JsonObject: ...


class _ReleaseRecords:
    """Release metadata CRUD and bounded generation projections."""

    def __init__(self, owner: _ReleaseRecordOwner) -> None:
        self._owner = owner

    # Release lifecycle and evidence.
    def list_releases(
        self,
        *,
        status: str | None,
        dataset_id: str | None = None,
        target_feature: str | None = None,
        schema_version: str | None = None,
        ingestion_run_id: str | None = None,
        query_text: str | None = None,
        lifecycle: str | None = None,
        limit: int,
        offset: int,
    ) -> list[JsonObject]:
        query = """SELECT release.*,
        CASE WHEN release.status='accepted' THEN 'completed'
          WHEN EXISTS (SELECT 1 FROM ops.release_activation activation
            WHERE activation.dataset_release_id=release.id
            AND activation.status IN ('queued','claimed','running','interrupted'))
          THEN 'pending'
          WHEN release.status='awaiting_review' AND (
            EXISTS (SELECT 1 FROM ops.release_activation activation
              WHERE activation.dataset_release_id=release.id AND activation.status='failed')
          ) THEN 'failed' ELSE NULL END AS publication_status
        FROM ops.dataset_release release
        JOIN ops.source_definition source ON source.id=release.source_definition_id"""
        params: list[Any] = []
        predicates: list[str] = ["source.status<>'retired'"]
        if status:
            predicates.append("release.status=%s")
            params.append(status)
        elif not ingestion_run_id:
            predicates.append("release.status<>'abandoned'")
        if lifecycle and lifecycle != "all":
            if lifecycle not in RELEASE_LIFECYCLES:
                raise ValidationError("lifecycle must be all, review, published or rejected")
            predicates.append("release.status=ANY(%s)")
            params.append(RELEASE_LIFECYCLES[lifecycle])
        if query_text:
            predicates.append(
                "POSITION(lower(%s) IN lower(concat_ws(' ',release.dataset_id,"
                "release.release_version,release.target_feature))) > 0"
            )
            params.append(query_text)
        for column, value in (
            ("dataset_id", dataset_id),
            ("target_feature", target_feature),
            ("schema_version", schema_version),
            ("ingestion_run_id", ingestion_run_id),
        ):
            if value:
                predicates.append(f"release.{column}=%s")
                params.append(value)
        query += " WHERE " + " AND ".join(predicates)
        query += " ORDER BY release.created_at DESC,release.id DESC LIMIT %s OFFSET %s"
        params.extend((limit, offset))
        return self._owner._fetch_all(query, params)

    def get_release(self, release_id: uuid.UUID) -> JsonObject:
        return self._owner._required("SELECT * FROM ops.dataset_release WHERE id=%s", (release_id,))

    def release_artifact(self, release_id: uuid.UUID) -> JsonObject:
        return self._owner._required(
            """SELECT artifact.*,
            release.manifest_json->>'redistribution_decision' AS redistribution_policy,
            release.manifest_json->>'content_encoding' AS content_encoding,
            release.status AS release_status
            FROM ops.dataset_release release
            JOIN ops.artifact_record artifact ON artifact.id=release.artifact_record_id
            WHERE release.id=%s""",
            (release_id,),
        )

    def create_release(self, values: Mapping[str, Any]) -> JsonObject:
        if values.get("status", "draft") != "draft":
            raise ConflictError("new releases must begin as drafts")
        now = datetime.now(UTC)
        try:
            with self._owner.connection() as connection:
                row = connection.execute(
                    """INSERT INTO ops.dataset_release (
                    id,dataset_id,source_definition_id,ingestion_run_id,target_feature,
                    release_version,schema_version,coverage_json,record_count,content_sha256,
                    artifact_record_id,manifest_json,status,review_comment,created_at,updated_at,version
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,1) RETURNING *""",
                    (
                        uuid.UUID(str(values.get("id", uuid.uuid4()))),
                        values["dataset_id"],
                        uuid.UUID(str(values["source_definition_id"])),
                        uuid.UUID(str(values["ingestion_run_id"])),
                        values["target_feature"],
                        values["release_version"],
                        values["schema_version"],
                        _json(values.get("coverage", {})),
                        int(values.get("record_count", 0)),
                        values["content_sha256"],
                        uuid.UUID(str(values["artifact_record_id"])),
                        _json(values.get("manifest", {})),
                        values.get("status", "draft"),
                        values.get("review_comment"),
                        now,
                        now,
                    ),
                ).fetchone()
                connection.commit()
        except errors.UniqueViolation as exc:
            raise ConflictError("release version already exists for this dataset") from exc
        except errors.ForeignKeyViolation as exc:
            raise NotFoundError("source, run, or artifact does not exist") from exc
        return _dict(row)

    def update_release(self, release_id: uuid.UUID, values: Mapping[str, Any]) -> JsonObject:
        current = self._owner.get_release(release_id)
        if current["status"] != "draft":
            raise ConflictError("bound candidate and terminal release evidence is immutable")
        with self._owner.connection() as connection:
            row = connection.execute(
                """UPDATE ops.dataset_release SET release_version=%s,schema_version=%s,
                coverage_json=%s,record_count=%s,content_sha256=%s,manifest_json=%s,
                review_comment=%s,updated_at=%s,version=version+1 WHERE id=%s AND version=%s
                AND status='draft' RETURNING *""",
                (
                    values.get("release_version", current["release_version"]),
                    values.get("schema_version", current["schema_version"]),
                    _json(values.get("coverage", current["coverage_json"])),
                    int(values.get("record_count", current["record_count"])),
                    values.get("content_sha256", current["content_sha256"]),
                    _json(values.get("manifest", current["manifest_json"])),
                    values.get("review_comment", current["review_comment"]),
                    datetime.now(UTC),
                    release_id,
                    int(values["version"]),
                ),
            ).fetchone()
            connection.commit()
        if row is None:
            raise ConflictError("release version does not match")
        return _dict(row)

    def delete_release(self, release_id: uuid.UUID) -> None:
        release = self._owner.get_release(release_id)
        if release["status"] not in {"draft", "rejected"}:
            raise ConflictError("only draft or rejected local releases can be deleted")
        try:
            self._owner._delete("ops", "dataset_release", release_id)
        except errors.ForeignKeyViolation as exc:
            raise ConflictError(
                "release has retained quality, receipt, or registry evidence"
            ) from exc

    def release_receipts(self, release_id: uuid.UUID) -> list[JsonObject]:
        self._owner.get_release(release_id)
        return self._owner._fetch_all(
            "SELECT * FROM ops.publication_receipt WHERE dataset_release_id=%s ORDER BY created_at",
            (release_id,),
        )

    def preview_release_records(
        self, release_id: uuid.UUID, *, limit: int, offset: int
    ) -> JsonObject:
        """Return a bounded, allowlisted projection of one isolated release generation."""
        context = self._owner._required(
            """SELECT release.id,release.dataset_id,release.release_version,release.status,
            release.record_count,release.coverage_json,job.import_profile_key
            FROM ops.dataset_release release
            JOIN ops.ingestion_run run ON run.id=release.ingestion_run_id
            JOIN ops.job_definition job ON job.id=run.job_definition_id
            WHERE release.id=%s""",
            (release_id,),
        )
        profile = str(context["import_profile_key"])
        spec = PREVIEW_SPECS.get(profile)
        if spec is None:
            raise ConflictError("release import profile does not support bounded preview")
        coverage = context.get("coverage_json")
        release_scope = (
            coverage.get("release_scope", coverage) if isinstance(coverage, Mapping) else None
        )
        has_registered_bound = (
            isinstance(release_scope, Mapping)
            and isinstance(release_scope.get("maximum_records"), int)
            and not isinstance(release_scope.get("maximum_records"), bool)
        )
        if profile != "bocsar-sparse" and has_registered_bound and isinstance(coverage, Mapping):
            query = release_product_query(profile, release_id, coverage, limit=limit, offset=offset)
            projected = self._owner._fetch_all(query.select_sql, query.select_params)
            items = [
                {column: row[column] for column in spec.columns if column in row}
                for row in projected
            ]
            total_row = self._owner._required(query.count_sql, query.count_params)
        else:
            # Historical seed releases predate explicit product scopes. BOCSAR's
            # preview intentionally remains observation-oriented while its export
            # aggregates those observations into coverage-aware series.
            items = self._owner._fetch_all(spec.select_sql, (release_id, limit, offset))
            total_row = self._owner._required(spec.count_sql, (release_id,))
        return {
            "release": {
                key: context[key]
                for key in ("id", "dataset_id", "release_version", "status", "record_count")
            },
            "profile": profile,
            "columns": list(spec.columns),
            "items": items,
            "count": len(items),
            "total": int(total_row["count"]),
            "limit": limit,
            "offset": offset,
            "next_offset": offset + len(items)
            if offset + len(items) < int(total_row["count"])
            else None,
        }

    def release_build_context(self, run_id: uuid.UUID) -> JsonObject:
        """Return one persistence-neutral build context bound to an imported generation."""
        return self._owner._required(
            """SELECT release.id AS release_id,release.release_version,release.dataset_id,
            release.target_feature,release.id AS candidate_generation_id,release.coverage_json,
            COALESCE(release.supersedes_release_id,(
                SELECT prior.id FROM ops.dataset_release prior
                WHERE prior.dataset_id=release.dataset_id
                  AND prior.target_feature=release.target_feature
                  AND prior.status='accepted' ORDER BY prior.accepted_at DESC LIMIT 1
            )) AS supersedes_release_id,
            COALESCE(run.source_snapshot_json->>'source_release',run.profile_key) AS source_release,
            run.normalisation_version,run.release_builder_version,
            job.release_builder_key,job.import_profile_key,source.name AS source_name,
            source.publisher,source.licence_id,source.licence_url,
            source.redistribution_policy,source_artifact.created_at AS source_retrieved_at
            FROM ops.ingestion_run run JOIN ops.job_definition job
              ON job.id=run.job_definition_id
            JOIN ops.source_definition source ON source.id=run.source_definition_id
            JOIN ops.dataset_release release ON release.ingestion_run_id=run.id
            LEFT JOIN LATERAL (
                SELECT artifact.created_at FROM ops.artifact_record artifact
                WHERE artifact.ingestion_run_id=run.id
                  AND artifact.artifact_kind IN ('source_snapshot','source_raw')
                ORDER BY artifact.created_at DESC LIMIT 1
            ) source_artifact ON true
            WHERE run.id=%s AND release.status IN ('draft','candidate')""",
            (run_id,),
        )

    def release_product_records(
        self, release_id: uuid.UUID, *, limit: int, cursor: str | None
    ) -> JsonObject:
        """Keyset-page the complete immutable candidate projection."""
        context = self._owner._required(
            """SELECT release.id,release.coverage_json,job.import_profile_key
            FROM ops.dataset_release release JOIN ops.ingestion_run run
              ON run.id=release.ingestion_run_id
            JOIN ops.job_definition job ON job.id=run.job_definition_id
            WHERE release.id=%s AND release.status IN ('draft','candidate')""",
            (release_id,),
        )
        profile = str(context["import_profile_key"])
        query = release_export_query(profile, release_id, limit=limit, cursor=cursor)
        rows = normalise_product_rows(
            profile, self._owner._fetch_all(query.select_sql, query.select_params)
        )
        total = (
            int(self._owner._required(query.count_sql, query.count_params)["count"])
            if cursor is None
            else None
        )
        next_cursor = (
            encode_export_cursor(rows[-1], query.cursor_columns) if len(rows) == limit else None
        )
        return {
            "release_id": str(release_id),
            "candidate_generation_id": str(release_id),
            "items": rows,
            "count": len(rows),
            "total": total,
            "limit": limit,
            "cursor": cursor,
            "next_cursor": next_cursor,
        }

    def release_sales_source_records(
        self, release_id: uuid.UUID, *, year: int, limit: int, offset: int
    ) -> JsonObject:
        """Page complete PSI facts from an immutable accepted generation by source year."""
        context = self._owner._required(
            """SELECT release.id,release.dataset_id,release.release_version,release.status,
            release.schema_version,job.import_profile_key
            FROM ops.dataset_release release JOIN ops.ingestion_run run
              ON run.id=release.ingestion_run_id
            JOIN ops.job_definition job ON job.id=run.job_definition_id
            WHERE release.id=%s""",
            (release_id,),
        )
        if context["dataset_id"] != "nsw-psi-sales" or context["import_profile_key"] != "psi-sales":
            raise ConflictError("release does not contain PSI sales source records")
        if context["schema_version"] not in {
            "propertyscope.property-sales.v2",
            "propertyscope.property-sales.v3",
        }:
            raise ConflictError("sales source records require a supported complete sales contract")
        if context["status"] not in {"accepted", "superseded"}:
            raise ConflictError("sales source records require an accepted immutable generation")
        select_sql = """SELECT source_business_key,source_revision,source_era,
            source_partition_year,district_code,property_id AS source_property_id,dealing_id,
            source_system,valuation_number,source_downloaded_at::text,property_name,
            unit_number,house_number,street_number_first,street_number_last,
            street_number_suffix,street_name,street_name_normalised,street_type,locality,
            postcode,land_description,dimensions,zoning_code,nature_code,primary_purpose,
            strata_lot_number,component_code,sale_code,interest_of_sale,contract_date::text,
            settlement_date::text,price_aud,area_original::text,area_unit,
            area_square_metres::text,property_ref,match_tier,match_confidence::text,
            geographic_precision,source_row_sha256,normalisation_version
            FROM warehouse.psi_sale WHERE dataset_release_id=%s AND source_partition_year=%s
            ORDER BY source_business_key,source_revision LIMIT %s OFFSET %s"""
        items = self._owner._fetch_all(select_sql, (release_id, year, limit, offset))
        total_row = self._owner._required(
            """SELECT count(*) AS count FROM warehouse.psi_sale
            WHERE dataset_release_id=%s AND source_partition_year=%s""",
            (release_id, year),
        )
        total = int(total_row["count"])
        return {
            "schema_version": "propertyscope.psi-source-records.v1",
            "release": {
                key: context[key]
                for key in ("id", "dataset_id", "release_version", "status", "schema_version")
            },
            "source_partition_year": year,
            "items": items,
            "count": len(items),
            "total": total,
            "limit": limit,
            "offset": offset,
            "next_offset": offset + len(items) if offset + len(items) < total else None,
        }
