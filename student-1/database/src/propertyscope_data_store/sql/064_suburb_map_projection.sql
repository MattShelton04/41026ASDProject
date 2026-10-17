-- Accepted suburb-map projection (docs/reviews/feature-1-suburb-map-api-review-2026-10-17.md).
-- Precise source geometry stays in warehouse.reference_feature and answers spatial predicates.
-- This release-scoped projection holds lookup fields and precomputed display geometry only.
CREATE EXTENSION IF NOT EXISTS btree_gist;

CREATE TABLE serving.suburb_boundary_display (
    dataset_release_id UUID NOT NULL REFERENCES ops.dataset_release(id) ON DELETE RESTRICT,
    suburb_id TEXT NOT NULL CHECK (suburb_id ~ '^[1-9][0-9]{0,11}$'),
    record_id TEXT NOT NULL,
    name TEXT NOT NULL,
    name_normalised TEXT NOT NULL,
    postcode TEXT CHECK (postcode IS NULL OR postcode ~ '^[0-9]{4}$'),
    geometry_status TEXT NOT NULL CHECK (geometry_status IN ('valid','invalid','not_provided')),
    centroid geometry(Point,4326),
    label_point geometry(Point,4326),
    min_longitude DOUBLE PRECISION,
    min_latitude DOUBLE PRECISION,
    max_longitude DOUBLE PRECISION,
    max_latitude DOUBLE PRECISION,
    source_vertex_count INTEGER NOT NULL CHECK (source_vertex_count >= 0),
    display_low geometry(Geometry,4326),
    display_medium geometry(Geometry,4326),
    display_high geometry(Geometry,4326),
    display_low_vertices INTEGER,
    display_medium_vertices INTEGER,
    display_high_vertices INTEGER,
    source_updated_at TEXT,
    valid_from TEXT,
    built_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (dataset_release_id, suburb_id),
    CHECK ((geometry_status = 'valid') = (display_medium IS NOT NULL))
);
CREATE INDEX suburb_boundary_display_name_idx
    ON serving.suburb_boundary_display (dataset_release_id, name_normalised, postcode);

-- Idempotent and release-scoped: publication calls it before the pointer switch, and the
-- tolerances match suburb_map_catalog.DETAIL_TOLERANCES. Invalid source geometry is never
-- simplified or repaired; it keeps only its envelope for camera fitting.
CREATE FUNCTION serving.build_suburb_boundary_display(p_release_id UUID)
RETURNS INTEGER LANGUAGE plpgsql AS $$
DECLARE
    built INTEGER;
BEGIN
    DELETE FROM serving.suburb_boundary_display WHERE dataset_release_id = p_release_id;
    INSERT INTO serving.suburb_boundary_display (
        dataset_release_id,suburb_id,record_id,name,name_normalised,postcode,geometry_status,
        centroid,label_point,min_longitude,min_latitude,max_longitude,max_latitude,
        source_vertex_count,display_low,display_medium,display_high,display_low_vertices,
        display_medium_vertices,display_high_vertices,source_updated_at,valid_from
    )
    SELECT feature.dataset_release_id,
           COALESCE(feature.attributes->>'cadid', split_part(feature.record_id, ':', 2)),
           feature.record_id,feature.name,
           trim(regexp_replace(upper(feature.name), '[^A-Z0-9]+', ' ', 'g')),
           CASE WHEN feature.attributes->>'postcode' ~ '^[0-9]{1,4}$'
                THEN lpad(feature.attributes->>'postcode', 4, '0') END,
           feature.geometry_status,
           CASE WHEN feature.geometry_status = 'valid' THEN ST_Centroid(feature.geom) END,
           CASE WHEN feature.geometry_status = 'valid' THEN ST_PointOnSurface(feature.geom) END,
           ST_XMin(feature.geom),ST_YMin(feature.geom),ST_XMax(feature.geom),ST_YMax(feature.geom),
           COALESCE(ST_NPoints(feature.geom), 0),
           display.low,display.medium,display.high,
           ST_NPoints(display.low),ST_NPoints(display.medium),ST_NPoints(display.high),
           feature.source_updated_at,feature.valid_from
    FROM warehouse.reference_feature feature
    LEFT JOIN LATERAL (
        SELECT CASE WHEN ST_IsValid(simplified.low) THEN simplified.low ELSE feature.geom END AS low,
               CASE WHEN ST_IsValid(simplified.medium) THEN simplified.medium
                    ELSE feature.geom END AS medium,
               CASE WHEN ST_IsValid(simplified.high) THEN simplified.high
                    ELSE feature.geom END AS high
        FROM (SELECT ST_SimplifyPreserveTopology(feature.geom, 0.0005) AS low,
                     ST_SimplifyPreserveTopology(feature.geom, 0.0001) AS medium,
                     ST_SimplifyPreserveTopology(feature.geom, 0.00002) AS high) simplified
        WHERE feature.geometry_status = 'valid'
    ) display ON true
    WHERE feature.dataset_release_id = p_release_id AND feature.layer = 'nsw-gazetted-suburb';
    GET DIAGNOSTICS built = ROW_COUNT;
    RETURN built;
END
$$;

-- Generation-scoped spatial probes: the leading release column keeps retained historical
-- generations (and unrelated cadastre/planning layers) out of every interactive search.
CREATE INDEX reference_feature_map_amenity_geom_idx
    ON warehouse.reference_feature USING gist (dataset_release_id, layer, geom)
    WHERE geometry_status = 'valid' AND layer IN (
        'train-station','bus-station','airport','library','hospital','ambulance-station',
        'police-station','fire-and-rescue-station','rural-fire-station','ses-headquarters',
        'preschool','primary-school','high-school','combined-school','technical-college',
        'university','protected-reserve'
    );
CREATE INDEX school_release_geom_idx ON warehouse.school USING gist (dataset_release_id, geom);

SELECT serving.build_suburb_boundary_display(release.id)
FROM ops.dataset_release release
WHERE release.dataset_id = 'nsw-suburb-boundaries' AND release.status = 'accepted';
