"""Canonical-property discovery projections owned by the database service."""

# SQL statements stay line-oriented so accepted-evidence policy remains reviewable.

from __future__ import annotations

import re
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from propertyscope_data_store.errors import NotFoundError, ValidationError

JsonObject = dict[str, Any]
PROPERTY_SEARCH_CANDIDATE_LIMIT = 500
PROPERTY_SEARCH_UNDERSPECIFIED_TERMS = frozenset(
    {
        "australia",
        "nsw",
        "street",
        "st",
        "road",
        "rd",
        "avenue",
        "ave",
        "drive",
        "dr",
        "lane",
        "ln",
        "court",
        "ct",
        "place",
        "pl",
        "highway",
        "hwy",
        "unit",
        "lot",
    }
)


@dataclass(frozen=True)
class PropertySearchResults:
    """A bounded property-search page plus the number of matching properties."""

    items: list[JsonObject]
    total: int
    total_is_lower_bound: bool = False


def _normalise_property_query(query: str) -> str:
    """Align user input with the punctuation-neutral registry search documents."""

    return re.sub(r"[^a-z0-9]+", " ", query.lower()).strip()


def _property_query_is_underspecified(normalised: str) -> bool:
    """Reject common address vocabulary that cannot selectively identify a property."""

    tokens = tuple(normalised.split())
    distinctive = tuple(
        token for token in tokens if token not in PROPERTY_SEARCH_UNDERSPECIFIED_TERMS
    )
    if not distinctive:
        return bool(tokens)
    return len(distinctive) == 1 and distinctive[0].isalpha() and len(distinctive[0]) < 8


class _PropertyReadOwner(Protocol):
    """Narrow persistence surface required by canonical-property projections."""

    def _fetch_one(self, query: str, params: Sequence[Any]) -> JsonObject | None: ...

    def _required(self, query: str, params: Sequence[Any]) -> JsonObject: ...

    def _fetch_all(self, query: str, params: Sequence[Any]) -> list[JsonObject]: ...


class _CanonicalPropertyReads:
    """Generation-aware canonical-property queries behind the repository facade."""

    def __init__(self, owner: _PropertyReadOwner) -> None:
        self._owner = owner

    def search_properties(
        self, query: str, *, state: str, limit: int, offset: int = 0
    ) -> PropertySearchResults:
        normalised = _normalise_property_query(query)
        if not normalised:
            return PropertySearchResults(items=[], total=0)
        if _property_query_is_underspecified(normalised):
            raise ValidationError(
                "q must include a street number, postcode, locality, or distinctive address term"
            )
        numeric_value: int | str | None = None
        if normalised.isdigit() and len(normalised) == 4:
            warehouse_match = "address.postcode=%s"
            legacy_match = "property.postcode=%s"
            alias_match = "FALSE"
            numeric_value = normalised
        elif normalised.isdigit():
            warehouse_match = "address.street_number_first=%s"
            legacy_match = "property.street_number_first=%s"
            alias_match = "FALSE"
            numeric_value = int(normalised)
        else:
            warehouse_match = (
                "trim(regexp_replace(lower(address.address_display), "
                "'[^a-z0-9]+',' ','g')) LIKE '%%' || %s || '%%'"
            )
            legacy_match = "property.address_search LIKE '%%' || %s || '%%'"
            alias_match = "alias.alias_search LIKE '%%' || %s || '%%'"
        search_params: list[Any] = [
            numeric_value if numeric_value is not None else normalised,
            PROPERTY_SEARCH_CANDIDATE_LIMIT + 1,
            numeric_value if numeric_value is not None else normalised,
        ]
        if numeric_value is None:
            search_params.append(normalised)
        search_params.extend(
            [
                PROPERTY_SEARCH_CANDIDATE_LIMIT + 1,
                PROPERTY_SEARCH_CANDIDATE_LIMIT,
                normalised,
                normalised,
                normalised,
                normalised,
                normalised,
                state,
                PROPERTY_SEARCH_CANDIDATE_LIMIT,
                limit,
                offset,
            ]
        )
        rows = self._owner._fetch_all(
            f"""
            WITH accepted_addresses AS MATERIALIZED (
                SELECT COALESCE(address.property_ref,
                           md5('propertyscope-gnaf:' || address.gnaf_pid)::uuid) AS property_ref,
                       address.address_display,address.locality,address.postcode,'NSW' AS state,
                       CASE WHEN address.source_status='CURRENT' THEN 'verified'
                            ELSE 'retired' END AS resolution_status,address.geom,
                       trim(regexp_replace(lower(address.address_display),
                           '[^a-z0-9]+',' ','g')) AS search_text,
                       address.address_display AS matched_address,'canonical' AS match_kind
                FROM warehouse.gnaf_address address
                JOIN serving.accepted_generation accepted
                  ON accepted.dataset_release_id=address.dataset_release_id
                JOIN ops.dataset_release release ON release.id=accepted.dataset_release_id
                WHERE release.dataset_id IN ('gnaf-nsw','fixture-property')
                  AND address.published
                  AND {warehouse_match}
                LIMIT %s
            ), legacy_documents AS (
                SELECT property.property_ref,property.address_display,property.locality,
                       property.postcode,property.state,property.resolution_status,property.geom,
                       property.address_search AS search_text,
                       property.address_display AS matched_address,'canonical' AS match_kind
                FROM registry.property property
                WHERE {legacy_match} AND EXISTS (
                    SELECT 1 FROM registry.property_identifier identifier
                    JOIN serving.accepted_generation accepted
                      ON accepted.dataset_release_id=identifier.source_release_id
                    WHERE identifier.property_ref=property.property_ref AND identifier.is_current
                ) AND NOT EXISTS (
                    SELECT 1 FROM warehouse.gnaf_address accepted_address
                    JOIN serving.accepted_generation accepted
                      ON accepted.dataset_release_id=accepted_address.dataset_release_id
                    WHERE accepted_address.published AND COALESCE(accepted_address.property_ref,
                        md5('propertyscope-gnaf:' || accepted_address.gnaf_pid)::uuid)
                        =property.property_ref
                )
                UNION ALL
                SELECT property.property_ref,property.address_display,property.locality,
                       property.postcode,property.state,property.resolution_status,property.geom,
                       alias.alias_search,alias.alias_display,'alias'
                FROM registry.address_alias alias
                JOIN registry.property property ON property.property_ref=alias.property_ref
                JOIN serving.accepted_generation accepted
                  ON accepted.dataset_release_id=alias.source_release_id
                WHERE alias.is_current
                  AND {alias_match}
                  AND NOT EXISTS (
                      SELECT 1 FROM warehouse.gnaf_address accepted_address
                      JOIN serving.accepted_generation accepted
                        ON accepted.dataset_release_id=accepted_address.dataset_release_id
                      WHERE accepted_address.published AND COALESCE(accepted_address.property_ref,
                          md5('propertyscope-gnaf:' || accepted_address.gnaf_pid)::uuid)
                          =property.property_ref
                  )
            ), search_documents AS MATERIALIZED (
                SELECT * FROM accepted_addresses
                UNION ALL SELECT * FROM legacy_documents
                LIMIT %s
            ), candidate_documents AS (
                SELECT * FROM search_documents LIMIT %s
            ), candidates AS (
                SELECT document.property_ref,document.address_display,document.locality,
                       document.postcode,document.state,document.resolution_status,
                       ST_X(document.geom) AS longitude,ST_Y(document.geom) AS latitude,
                       document.matched_address,document.match_kind,
                       greatest(
                           similarity(document.search_text,%s),
                           word_similarity(%s,document.search_text),
                           CASE WHEN document.search_text=%s THEN 1 ELSE 0 END
                       ) AS score,
                       CASE
                           WHEN document.search_text=%s THEN 0
                           WHEN document.search_text LIKE %s || '%%' THEN 1
                           ELSE 2
                       END AS match_rank
                FROM candidate_documents document
                WHERE document.state=%s
            ), best_matches AS (
                SELECT DISTINCT ON (property_ref) * FROM candidates
                ORDER BY property_ref,match_rank,score DESC,
                         CASE WHEN match_kind='canonical' THEN 0 ELSE 1 END,matched_address
            ), summary AS (
                SELECT count(*)::bigint AS total_count,
                       (SELECT count(*)>%s FROM search_documents) AS total_is_lower_bound
                FROM best_matches
            )
            SELECT page.*,summary.total_count,summary.total_is_lower_bound
            FROM summary LEFT JOIN LATERAL (
                SELECT property_ref,address_display,locality,postcode,state,resolution_status,
                       longitude,latitude,score,matched_address,match_kind,
                       CASE match_rank
                           WHEN 0 THEN 'exact'
                           WHEN 1 THEN 'prefix'
                           ELSE 'contains'
                       END AS match_method
                FROM best_matches
                ORDER BY match_rank,score DESC,address_display LIMIT %s OFFSET %s
            ) page ON true
            """,
            search_params,
        )
        total = int(rows[0].get("total_count", 0)) if rows else 0
        total_is_lower_bound = bool(rows[0].get("total_is_lower_bound", False)) if rows else False
        page: list[JsonObject] = []
        for row in rows:
            row.pop("total_count", None)
            row.pop("total_is_lower_bound", None)
            if row.get("property_ref") is not None:
                page.append(row)
        return PropertySearchResults(
            items=page,
            total=total,
            total_is_lower_bound=total_is_lower_bound,
        )

    def property_snapshot(self, property_ref: uuid.UUID) -> JsonObject:
        accepted_address = self._owner._fetch_one(
            """SELECT jsonb_build_object(
                'property_ref',COALESCE(address.property_ref,
                    md5('propertyscope-gnaf:' || address.gnaf_pid)::uuid),
                'address_display',address.address_display,'flat_type',address.flat_type,
                'unit_number',address.unit_number,
                'street_number_first',address.street_number_first,
                'street_number_suffix',address.street_number_suffix,
                'street_number_last',address.street_number_last,
                'street_name',COALESCE(address.street_name,address.address_display),
                'street_type',address.street_type,'locality',address.locality,
                'postcode',address.postcode,'state','NSW',
                'address_search',trim(regexp_replace(lower(address.address_display),
                    '[^a-z0-9]+',' ','g')),
                'geometry',ST_AsGeoJSON(address.geom)::jsonb,
                'longitude',ST_X(address.geom),'latitude',ST_Y(address.geom),
                'resolution_status',CASE WHEN address.source_status='CURRENT'
                    THEN 'verified' ELSE 'retired' END,
                'created_at',address.created_at,'updated_at',address.created_at,'version',1
            ) AS property,jsonb_build_object(
                'id',md5('propertyscope-' ||
                    CASE WHEN release.dataset_id='gnaf-nsw' THEN 'gnaf_pid'
                         ELSE 'fixture_pid' END || '-identifier:' || release.id::text || ':' ||
                         address.gnaf_pid)::uuid,
                'property_ref',COALESCE(address.property_ref,
                    md5('propertyscope-gnaf:' || address.gnaf_pid)::uuid),
                'scheme',CASE WHEN release.dataset_id='gnaf-nsw' THEN 'gnaf_pid'
                              ELSE 'fixture_pid' END,
                'identifier_value',address.gnaf_pid,'source_release_id',release.id,
                'is_current',true,'valid_from',NULL,'valid_to',NULL,
                'match_method','source-authoritative','match_confidence',1,
                'evidence_json',jsonb_build_object('geocode_type',address.geocode_type,
                    'source_crs',address.source_crs),'created_at',address.created_at
            ) AS identifier
            FROM warehouse.gnaf_address address
            JOIN serving.accepted_generation accepted
              ON accepted.dataset_release_id=address.dataset_release_id
            JOIN ops.dataset_release release ON release.id=accepted.dataset_release_id
            WHERE release.dataset_id IN ('gnaf-nsw','fixture-property')
              AND address.published
              AND COALESCE(address.property_ref,
                  md5('propertyscope-gnaf:' || address.gnaf_pid)::uuid)=%s
            LIMIT 1""",
            (property_ref,),
        )
        if accepted_address is not None:
            return {
                "property": dict(accepted_address["property"]),
                "identifiers": [dict(accepted_address["identifier"])],
                "aliases": [],
                "coverage": self.property_coverage(property_ref),
            }
        property_row = self._owner._required(
            """SELECT *,ST_X(geom) AS longitude,ST_Y(geom) AS latitude,
            ST_AsGeoJSON(geom)::jsonb AS geometry FROM registry.property WHERE property_ref=%s""",
            (property_ref,),
        )
        identifiers = self._owner._fetch_all(
            "SELECT * FROM registry.property_identifier WHERE property_ref=%s ORDER BY created_at",
            (property_ref,),
        )
        aliases = self._owner._fetch_all(
            "SELECT * FROM registry.address_alias WHERE property_ref=%s ORDER BY alias_display",
            (property_ref,),
        )
        coverage = self.property_coverage(property_ref)
        return {
            "property": property_row,
            "identifiers": identifiers,
            "aliases": aliases,
            "coverage": coverage,
        }

    def property_coverage(self, property_ref: uuid.UUID) -> list[JsonObject]:
        exists = self._owner._fetch_one(
            """SELECT 1 AS present FROM warehouse.gnaf_address address
            JOIN serving.accepted_generation accepted
              ON accepted.dataset_release_id=address.dataset_release_id
            WHERE address.published AND COALESCE(address.property_ref,
                md5('propertyscope-gnaf:' || address.gnaf_pid)::uuid)=%s
            UNION ALL SELECT 1 FROM registry.property WHERE property_ref=%s LIMIT 1""",
            (property_ref, property_ref),
        )
        if exists is None:
            raise NotFoundError("record does not exist")
        return self._owner._fetch_all(
            """WITH accepted_identity AS (
                SELECT COALESCE(address.property_ref,
                           md5('propertyscope-gnaf:' || address.gnaf_pid)::uuid) AS property_ref,
                       release.dataset_id,release.target_feature,
                       release.id AS dataset_release_id,'supported' AS coverage_status,
                       release.coverage_json AS coverage_scope,
                       accepted.activated_at AS checked_at,release.release_version,
                       release.schema_version,release.accepted_at
                FROM warehouse.gnaf_address address
                JOIN serving.accepted_generation accepted
                  ON accepted.dataset_release_id=address.dataset_release_id
                JOIN ops.dataset_release release ON release.id=accepted.dataset_release_id
                WHERE address.published AND COALESCE(address.property_ref,
                    md5('propertyscope-gnaf:' || address.gnaf_pid)::uuid)=%s
            ), retained_coverage AS (
                SELECT coverage.*,release.release_version,release.schema_version,
                       release.accepted_at
                FROM serving.property_coverage coverage
                LEFT JOIN ops.dataset_release release ON release.id=coverage.dataset_release_id
                WHERE coverage.property_ref=%s AND NOT EXISTS (
                    SELECT 1 FROM accepted_identity identity
                    WHERE identity.dataset_id=coverage.dataset_id
                      AND identity.target_feature=coverage.target_feature
                )
            )
            SELECT * FROM accepted_identity UNION ALL SELECT * FROM retained_coverage
            ORDER BY target_feature,dataset_id""",
            (property_ref, property_ref),
        )
