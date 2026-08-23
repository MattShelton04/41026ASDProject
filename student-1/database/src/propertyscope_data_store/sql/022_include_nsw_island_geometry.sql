-- NSW address coverage includes Lord Howe Island at roughly 159 degrees east.
-- Keep this constraint aligned with the registered source adapters and release builders.
ALTER TABLE registry.property
    DROP CONSTRAINT property_geom_check,
    ADD CONSTRAINT property_geom_check
        CHECK (ST_X(geom) BETWEEN 140 AND 160);
