"""Compare current matcher with accepted PSI links without changing application data.

Runs inside the owning PostgreSQL container. Transaction-local address dictionaries
collapse repeated sales, but weighted totals account for every source revision.
The retained source facts and accepted pointers are never updated. A sample is
explicitly labelled and must not be presented as a complete-generation count.
"""

from __future__ import annotations

import argparse
import subprocess

from propertyscope_data_store.source_materialisation import PSI_ADDRESS_RESOLUTION_SQL


def audit_sql(*, sample_percent: float | None = None, explain: bool = False) -> str:
    sample = (
        "" if sample_percent is None else f"TABLESAMPLE SYSTEM ({sample_percent}) REPEATABLE (913)"
    )
    statement = f"""
\\timing on
BEGIN;
SET LOCAL statement_timeout='300s';
SELECT dataset_id,dataset_release_id FROM serving.accepted_generation
WHERE dataset_id IN ('gnaf-nsw','nsw-psi-sales') ORDER BY dataset_id;
CREATE TEMP TABLE propertyscope_psi_import_stage ON COMMIT DROP AS
SELECT row_number() OVER () AS ordinal, grouped.*, NULL::uuid AS property_ref
FROM (
    SELECT postcode,locality,street_name_normalised,street_type,street_number_first,
        street_number_last,street_number_suffix,unit_number,house_number,source_era,
        property_ref AS baseline_property_ref,count(*) AS revision_count
    FROM warehouse.psi_sale {sample}
    WHERE dataset_release_id=(SELECT dataset_release_id FROM serving.accepted_generation
        WHERE dataset_id='nsw-psi-sales')
    GROUP BY 1,2,3,4,5,6,7,8,9,10,11
) grouped;
DO $audit$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM propertyscope_psi_import_stage) THEN
        RAISE EXCEPTION 'No accepted PSI revisions available for the requested audit scope';
    END IF;
END $audit$;
CREATE TEMP TABLE propertyscope_psi_identity_stage ON COMMIT DROP AS
SELECT ordinal AS first_ordinal FROM propertyscope_psi_import_stage;
ANALYZE propertyscope_psi_import_stage;
ANALYZE propertyscope_psi_identity_stage;
{PSI_ADDRESS_RESOLUTION_SQL};
SELECT source.source_era,
    CASE WHEN source.house_number IS NULL THEN 'no_house'
         WHEN source.house_number !~ '^[0-9]+[A-Z]?(-[0-9]+)?$' THEN 'complex_house'
         WHEN source.street_type IS NULL THEN 'unrecognised_type'
         ELSE 'other' END AS original_address_kind,
    sum(source.revision_count) AS revisions,
    sum(source.revision_count) FILTER (WHERE source.baseline_property_ref IS NOT NULL)
        AS old_linked,
    sum(source.revision_count) FILTER (WHERE resolution.exact_property_ref IS NOT NULL)
        AS new_linked,
    sum(source.revision_count) FILTER (WHERE source.baseline_property_ref IS NULL
        AND resolution.exact_property_ref IS NOT NULL) AS gained,
    sum(source.revision_count) FILTER (WHERE source.baseline_property_ref IS NOT NULL
        AND resolution.exact_property_ref IS NULL) AS lost,
    sum(source.revision_count) FILTER (WHERE source.baseline_property_ref IS NOT NULL
        AND resolution.exact_property_ref<>source.baseline_property_ref) AS changed,
    sum(source.revision_count) FILTER (WHERE resolution.match_count>1) AS ambiguous
FROM propertyscope_psi_import_stage source
LEFT JOIN propertyscope_psi_address_resolution resolution
  ON resolution.house_number=source.house_number
 AND resolution.postcode=source.postcode AND resolution.locality=source.locality
 AND resolution.street_name_normalised=source.street_name_normalised
 AND COALESCE(resolution.street_type,'')=COALESCE(source.street_type,'')
 AND resolution.street_number_first=source.street_number_first
 AND COALESCE(resolution.street_number_last,-1)=COALESCE(source.street_number_last,-1)
 AND COALESCE(resolution.street_number_suffix,'')=COALESCE(source.street_number_suffix,'')
 AND COALESCE(resolution.unit_number,'')=COALESCE(source.unit_number,'')
GROUP BY 1,2 ORDER BY 1,2;
ROLLBACK;
"""
    if explain:
        before = statement.split(PSI_ADDRESS_RESOLUTION_SQL)[0]
        query = PSI_ADDRESS_RESOLUTION_SQL.replace(
            "CREATE TEMP TABLE propertyscope_psi_address_resolution ON COMMIT DROP AS",
            "EXPLAIN (COSTS TRUE)",
        )
        return before + query + "; ROLLBACK;"
    return statement


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--container", default="ps-dev-f1-postgres-1")
    parser.add_argument("--sample-percent", type=float)
    parser.add_argument("--sql-only", action="store_true")
    parser.add_argument("--explain", action="store_true")
    args = parser.parse_args()
    if args.sample_percent is not None and not 0 < args.sample_percent <= 100:
        parser.error("sample-percent must be within (0,100]")
    statement = audit_sql(sample_percent=args.sample_percent, explain=args.explain)
    if args.sql_only:
        print(statement)
        return
    coverage = "complete accepted generation" if args.sample_percent is None else "block sample"
    print(f"Coverage: {coverage}", flush=True)
    subprocess.run(
        [
            "docker",
            "exec",
            "-i",
            args.container,
            "psql",
            "-X",
            "-v",
            "ON_ERROR_STOP=1",
            "-U",
            "propertyscope",
            "-d",
            "propertyscope",
        ],
        input=statement,
        text=True,
        check=True,
    )


if __name__ == "__main__":
    main()
