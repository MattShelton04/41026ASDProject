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
# G-NAF registry rows can anchor foreign keys, but canonical fields are owned by
# the currently accepted warehouse generation, even after an address is withdrawn.
_REGISTRY_COMPATIBILITY_PREDICATE = """NOT EXISTS (
    SELECT 1 FROM registry.property_identifier warehouse_identifier
    WHERE warehouse_identifier.property_ref=property.property_ref
      AND warehouse_identifier.scheme='gnaf_pid'
)"""
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
                WHERE {legacy_match} AND {_REGISTRY_COMPATIBILITY_PREDICATE} AND EXISTS (
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
                  AND {_REGISTRY_COMPATIBILITY_PREDICATE}
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

    def locality_summary(
        self,
        *,
        locality: str | None,
        postcode: str | None,
        include_streets: bool,
    ) -> JsonObject:
        """Aggregate one accepted address generation without fuzzy-search sampling."""

        normalised_locality = locality.strip().upper() if locality else None
        normalised_postcode = postcode.strip() if postcode else None
        if not normalised_locality and not normalised_postcode:
            raise ValidationError("locality or postcode is required")
        if normalised_postcode and not re.fullmatch(r"\d{4}", normalised_postcode):
            raise ValidationError("postcode must contain four digits")
        summary = self._owner._fetch_one(
            """WITH selected_generation AS MATERIALIZED (
                SELECT release.id AS dataset_release_id,release.dataset_id,
                       release.release_version,release.schema_version,release.accepted_at
                FROM serving.accepted_generation accepted
                JOIN ops.dataset_release release ON release.id=accepted.dataset_release_id
                WHERE accepted.target_feature='feature-1'
                  AND release.status='accepted'
                  AND release.dataset_id IN ('gnaf-nsw','fixture-property')
                  AND release.schema_version IN (
                      'propertyscope.property-snapshot.v1',
                      'propertyscope.property-snapshot.v2'
                  )
                ORDER BY CASE WHEN release.dataset_id='gnaf-nsw' THEN 0 ELSE 1 END
                LIMIT 1
            )
            SELECT generation.dataset_release_id,generation.dataset_id,
                   generation.release_version,generation.schema_version,
                   generation.accepted_at,count(address.gnaf_pid)::bigint AS total,
                   count(address.gnaf_pid) FILTER (
                       WHERE NULLIF(address.unit_number,'') IS NOT NULL
                   )::bigint AS with_unit_number,
                   min(ST_Y(address.geom)) AS min_latitude,
                   max(ST_Y(address.geom)) AS max_latitude,
                   min(ST_X(address.geom)) AS min_longitude,
                   max(ST_X(address.geom)) AS max_longitude
            FROM selected_generation generation
            LEFT JOIN warehouse.gnaf_address address
              ON address.dataset_release_id=generation.dataset_release_id
             AND address.published
             AND (%s::text IS NULL OR address.locality=%s)
             AND (%s::text IS NULL OR address.postcode=%s)
            GROUP BY generation.dataset_release_id,generation.dataset_id,
                     generation.release_version,generation.schema_version,
                     generation.accepted_at""",
            (
                normalised_locality,
                normalised_locality,
                normalised_postcode,
                normalised_postcode,
            ),
        )
        if summary is None:
            return {
                "availability": {
                    "status": "dataset_unavailable",
                    "reason": "No compatible accepted NSW address generation is available.",
                    "accepted_release_id": None,
                },
                "scope": {
                    "locality": normalised_locality,
                    "postcode": normalised_postcode,
                    "state": "NSW",
                },
                "total_registered_addresses": 0,
                "unit_number_summary": {"with_unit_number": 0, "without_unit_number": 0},
                "bounding_box": None,
                "top_streets": [],
                "release": None,
            }
        total = int(summary.get("total", 0))
        with_unit_number = int(summary.get("with_unit_number", 0))
        top_streets: list[JsonObject] = []
        if include_streets and total:
            top_streets = self._owner._fetch_all(
                """SELECT street_name,count(*)::bigint AS address_count
                FROM warehouse.gnaf_address
                WHERE dataset_release_id=%s AND published
                  AND (%s::text IS NULL OR locality=%s)
                  AND (%s::text IS NULL OR postcode=%s)
                  AND NULLIF(street_name,'') IS NOT NULL
                GROUP BY street_name
                ORDER BY address_count DESC,street_name
                LIMIT 20""",
                (
                    summary["dataset_release_id"],
                    normalised_locality,
                    normalised_locality,
                    normalised_postcode,
                    normalised_postcode,
                ),
            )
        bounding_box = None
        if total and summary.get("min_latitude") is not None:
            bounding_box = {
                "min_latitude": summary["min_latitude"],
                "max_latitude": summary["max_latitude"],
                "min_longitude": summary["min_longitude"],
                "max_longitude": summary["max_longitude"],
            }
        return {
            "availability": {
                "status": "available",
                "reason": "Counts use one compatible accepted NSW address generation.",
                "accepted_release_id": summary["dataset_release_id"],
            },
            "scope": {
                "locality": normalised_locality,
                "postcode": normalised_postcode,
                "state": "NSW",
            },
            "total_registered_addresses": total,
            "unit_number_summary": {
                "with_unit_number": with_unit_number,
                "without_unit_number": total - with_unit_number,
            },
            "bounding_box": bounding_box,
            "top_streets": top_streets,
            "release": {
                key: summary[key]
                for key in (
                    "dataset_release_id",
                    "dataset_id",
                    "release_version",
                    "schema_version",
                    "accepted_at",
                )
            },
        }

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
            f"""SELECT property.*,ST_X(geom) AS longitude,ST_Y(geom) AS latitude,
            ST_AsGeoJSON(geom)::jsonb AS geometry FROM registry.property property
            WHERE property_ref=%s AND {_REGISTRY_COMPATIBILITY_PREDICATE}""",
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
            f"""SELECT 1 AS present FROM warehouse.gnaf_address address
            JOIN serving.accepted_generation accepted
              ON accepted.dataset_release_id=address.dataset_release_id
            WHERE address.published AND COALESCE(address.property_ref,
                md5('propertyscope-gnaf:' || address.gnaf_pid)::uuid)=%s
            UNION ALL SELECT 1 FROM registry.property property
            WHERE property_ref=%s AND {_REGISTRY_COMPATIBILITY_PREDICATE} LIMIT 1""",
            (property_ref, property_ref),
        )
        if exists is None:
            raise NotFoundError("record does not exist")
        coverage = self._owner._fetch_all(
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
        seifa = self._seifa_coverage(property_ref)
        if seifa is not None and seifa.get("dataset_id") == "abs-seifa-2021":
            coverage.append(seifa)
        return sorted(coverage, key=lambda item: (item["target_feature"], item["dataset_id"]))

    def _seifa_coverage(self, property_ref: uuid.UUID) -> JsonObject | None:
        return self._owner._fetch_one(
            f"""WITH property_locality AS (
                SELECT address.locality
                FROM warehouse.gnaf_address address
                JOIN serving.accepted_generation identity
                  ON identity.dataset_release_id=address.dataset_release_id
                WHERE address.published AND COALESCE(address.property_ref,
                    md5('propertyscope-gnaf:' || address.gnaf_pid)::uuid)=%s
                UNION ALL SELECT property.locality FROM registry.property property
                WHERE property.property_ref=%s AND {_REGISTRY_COMPATIBILITY_PREDICATE} LIMIT 1
            )
            SELECT release.dataset_id,release.target_feature,release.id AS dataset_release_id,
                   'supported' AS coverage_status,
                   release.coverage_json || jsonb_build_object(
                       'matched_sal_code',area.sal_code,'matched_sal_name',area.sal_name,
                       'match_method','exact-normalised-locality-and-state') AS coverage_scope,
                   accepted.activated_at AS checked_at,release.release_version,
                   release.schema_version,release.accepted_at
            FROM property_locality property
            JOIN serving.accepted_generation accepted
              ON accepted.dataset_id='abs-seifa-2021'
             AND accepted.target_feature='feature-1'
            JOIN ops.dataset_release release ON release.id=accepted.dataset_release_id
             AND release.status='accepted' AND release.schema_version='propertyscope.seifa-area.v1'
            JOIN warehouse.seifa_sal area ON area.dataset_release_id=release.id
             AND area.state='NSW'
             AND area.locality_name=upper(regexp_replace(trim(property.locality),'\\s+',' ','g'))
            LIMIT 1""",
            (property_ref, property_ref),
        )

    def property_seifa(self, property_ref: uuid.UUID) -> JsonObject:
        property_item = self._owner._fetch_one(
            f"""SELECT address.locality
            FROM warehouse.gnaf_address address
            JOIN serving.accepted_generation accepted
              ON accepted.dataset_release_id=address.dataset_release_id
            WHERE address.published AND COALESCE(address.property_ref,
                md5('propertyscope-gnaf:' || address.gnaf_pid)::uuid)=%s
            UNION ALL SELECT property.locality FROM registry.property property
            WHERE property.property_ref=%s AND {_REGISTRY_COMPATIBILITY_PREDICATE} LIMIT 1""",
            (property_ref, property_ref),
        )
        if property_item is None:
            raise NotFoundError("record does not exist")
        locality = " ".join(str(property_item["locality"]).upper().split())
        accepted = self._owner._fetch_one(
            """SELECT release.id AS dataset_release_id,release.release_version,
               release.schema_version,release.accepted_at,accepted.activated_at,
               source.name AS source_name,source.publisher,source.source_url,
               source.licence_id,source.licence_url
            FROM serving.accepted_generation accepted
            JOIN ops.dataset_release release ON release.id=accepted.dataset_release_id
            JOIN ops.source_definition source ON source.id=release.source_definition_id
            WHERE accepted.dataset_id='abs-seifa-2021'
              AND accepted.target_feature='feature-1'
              AND release.status='accepted'
              AND release.schema_version='propertyscope.seifa-area.v1'
            LIMIT 1""",
            (),
        )
        if accepted is None:
            return {
                "supported": False,
                "availability": "no_accepted_release",
                "property_ref": str(property_ref),
                "locality": locality,
                "message": "No accepted ABS SEIFA 2021 release is available.",
            }
        matches = self._owner._fetch_all(
            """SELECT sal_code,sal_name,locality_name,state,reference_year,
               irsd_score::text,irsd_australia_decile,irsad_score::text,
               irsad_australia_decile,ier_score::text,ier_australia_decile,
               ieo_score::text,ieo_australia_decile,usual_resident_population
            FROM warehouse.seifa_sal
            WHERE dataset_release_id=%s AND state='NSW' AND locality_name=%s
            ORDER BY usual_resident_population DESC,sal_code LIMIT 2""",
            (accepted["dataset_release_id"], locality),
        )
        if len(matches) != 1:
            availability = "locality_not_matched" if not matches else "ambiguous_locality_match"
            return {
                "supported": False,
                "availability": availability,
                "property_ref": str(property_ref),
                "locality": locality,
                "message": (
                    "The accepted SEIFA release has no exact NSW locality match."
                    if not matches
                    else "The accepted SEIFA release has more than one exact locality match."
                ),
                "release": accepted,
            }
        area = matches[0]
        return {
            "supported": True,
            "availability": "available",
            "property_ref": str(property_ref),
            "locality": locality,
            "match_method": "exact-normalised-locality-and-state",
            "area": area,
            "release": accepted,
            "attribution": "Based on Australian Bureau of Statistics data",
            "limitations": [
                "SEIFA describes the 2021 Suburb and Locality area, not this property, "
                "household, or its residents.",
                "The match uses exact normalised locality name and NSW state, "
                "not a spatial boundary.",
                "Small-population SAL scores and comparisons require caution.",
            ],
        }

    def property_sale_history(self, property_ref: uuid.UUID, *, limit: int) -> JsonObject:
        """Return latest accepted PSI revisions for one canonical property.

        The accepted-generation join keeps a publication pointer switch atomic for readers.
        Corrected retransmissions remain stored, but only the latest source revision is shown as
        a sale event.  ``limit + 1`` supplies bounded truncation evidence without an unbounded
        count over the source-scale PSI generation.
        """

        rows = self._owner._fetch_all(
            f"""WITH property_presence AS MATERIALIZED (
                SELECT true AS present
                FROM warehouse.gnaf_address address
                JOIN serving.accepted_generation accepted
                  ON accepted.dataset_release_id=address.dataset_release_id
                WHERE address.published AND COALESCE(address.property_ref,
                    md5('propertyscope-gnaf:' || address.gnaf_pid)::uuid)=%s
                UNION ALL
                SELECT true FROM registry.property property WHERE property.property_ref=%s
                  AND {_REGISTRY_COMPATIBILITY_PREDICATE}
                LIMIT 1
            ), accepted_pointer AS MATERIALIZED (
                SELECT release.id AS dataset_release_id,release.release_version,
                       release.schema_version,release.accepted_at
                FROM serving.accepted_generation accepted
                JOIN ops.dataset_release release ON release.id=accepted.dataset_release_id
                WHERE accepted.dataset_id='nsw-psi-sales'
                  AND accepted.target_feature='feature-2'
                  AND release.status='accepted'
                LIMIT 1
            ), accepted_sales AS MATERIALIZED (
                SELECT * FROM accepted_pointer
                WHERE schema_version IN (
                    'propertyscope.property-sales.v2',
                    'propertyscope.property-sales.v3'
                )
            ), latest_sales AS (
                SELECT DISTINCT ON (sale.source_business_key)
                       sale.source_business_key,sale.source_revision,sale.contract_date,
                       sale.settlement_date,sale.price_aud,sale.area_original,sale.area_unit,
                       sale.area_square_metres,sale.property_id,sale.dealing_id,
                       sale.match_tier,sale.match_confidence,sale.geographic_precision,
                       sale.nature_code,sale.primary_purpose,sale.sale_code,
                       accepted.dataset_release_id,accepted.release_version,
                       accepted.schema_version,accepted.accepted_at
                FROM accepted_sales accepted
                JOIN warehouse.psi_sale sale
                  ON sale.dataset_release_id=accepted.dataset_release_id
                WHERE sale.property_ref=%s
                ORDER BY sale.source_business_key,sale.source_revision DESC
            ), page AS MATERIALIZED (
                SELECT * FROM latest_sales
                ORDER BY COALESCE(contract_date,settlement_date) DESC NULLS LAST,
                         source_business_key
                LIMIT %s
            )
            SELECT presence.present,pointer.dataset_release_id AS pointer_release_id,
                   pointer.schema_version AS pointer_schema_version,
                   accepted.dataset_release_id,accepted.release_version,
                   accepted.schema_version,accepted.accepted_at,
                   page.source_business_key,page.source_revision,page.contract_date,
                   page.settlement_date,page.price_aud,page.area_original,page.area_unit,
                   page.area_square_metres,page.property_id,page.dealing_id,page.match_tier,
                   page.match_confidence,page.geographic_precision,page.nature_code,
                   page.primary_purpose,page.sale_code
            FROM property_presence presence
            LEFT JOIN accepted_pointer pointer ON true
            LEFT JOIN accepted_sales accepted ON true
            LEFT JOIN page ON true
            ORDER BY COALESCE(page.contract_date,page.settlement_date) DESC NULLS LAST,
                     page.source_business_key""",
            (property_ref, property_ref, property_ref, limit + 1),
        )
        if not rows:
            raise NotFoundError("record does not exist")
        first = rows[0]
        supported = first.get("dataset_release_id") is not None
        pointer_available = first.get("pointer_release_id") is not None
        items = [
            {
                key: value
                for key, value in row.items()
                if key not in {"present", "pointer_release_id", "pointer_schema_version"}
            }
            for row in rows
            if row.get("source_business_key") is not None
        ]
        has_more = len(items) > limit
        return {
            "items": items[:limit],
            "count": min(len(items), limit),
            "limit": limit,
            "has_more": has_more,
            "supported": supported,
            "availability": {
                "status": "available"
                if supported
                else "unsupported_contract"
                if pointer_available
                else "dataset_unavailable",
                "reason": (
                    "Sale history uses the compatible accepted NSW PSI generation."
                    if supported
                    else "The accepted NSW PSI generation uses an unsupported schema."
                    if pointer_available
                    else "No accepted NSW PSI generation is available."
                ),
                "accepted_release_id": first.get("dataset_release_id")
                if supported
                else first.get("pointer_release_id"),
            },
            "release": {
                "dataset_release_id": first["dataset_release_id"],
                "release_version": first["release_version"],
                "schema_version": first["schema_version"],
                "accepted_at": first["accepted_at"],
            }
            if supported
            else None,
        }
