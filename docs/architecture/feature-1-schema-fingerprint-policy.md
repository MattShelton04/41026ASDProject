# Feature 1 PostgreSQL schema fingerprint policy

Feature 1 publishes a deterministic SHA-256 fingerprint for its owned PostgreSQL/PostGIS
schema. The internal fingerprint endpoint returns the digest together with the policy identifier
`propertyscope-postgresql-schema.v2`; evidence and comparisons must use both values. A digest from
a different policy version is not equal or unequal evidence—it is not comparable.

## Version 2 manifest

The digest input is canonical JSON containing the policy version, the fixed owned-schema and
required-extension sets, and sorted tagged records for:

- the presence of every owned schema and each ordinary table, partitioned table, view, and
  materialized view;
- column order, names, PostgreSQL/user-defined/domain types, character length, numeric precision,
  radix and scale, date/time and interval precision, collation, nullability, defaults, generated
  and identity properties, and PostGIS geometry type, SRID and dimensions;
- index identity and access method, uniqueness/primary/validity state, partial predicates, key and
  included-column order, expression keys, operator classes, collations and sort/null ordering;
- primary-key, unique, foreign-key, check and exclusion constraints, including validation and
  deferral state, ordered local/referenced columns, foreign-key actions and exclusion operators;
- view and materialized-view query expressions; and
- the installed version and schema of the required `postgis`, `pg_trgm`, and `pgcrypto`
  extensions.

Records come from structured `information_schema` and `pg_catalog` fields rather than complete
server-rendered `CREATE` statements such as `pg_indexes.indexdef` or
`pg_get_constraintdef(...)`. Defaults, checks, partial/expression indexes, generated columns and
views necessarily contain SQL expressions. For only those bounded fields, PostgreSQL's decompiler
output is used and insignificant whitespace outside quoted literals is collapsed before hashing.
Whitespace inside quoted identifiers, strings and dollar-quoted bodies remains significant.

The runtime pins PostgreSQL 16 and PostGIS 3.4. A PostgreSQL/PostGIS major upgrade must run the
migration-from-empty integration gate and compare the decoded policy inputs before accepting a
new baseline. If a catalogue meaning, expression-decompilation rule, owned schema, required
extension, or manifest field changes, introduce a new policy version; do not silently reinterpret
v2 or special-case an old digest. Adding an ordinary migration that changes a covered schema fact
changes the digest while retaining v2.

## Compatibility and use

The fingerprint detects schema drift; it is not a migration version, data checksum, backup proof,
or authorization token. Migration filenames and immutable checksums remain the source of upgrade
ordering. Operators compare fingerprints only after migrations complete and only when algorithm
and policy version match. Exact extension versions are deliberate inputs, so an extension upgrade
changes the fingerprint even when application-owned relations do not.

Tuple cursor rows and production `dict_row` results are canonicalized to identical records. Record
sorting makes catalogue return order irrelevant, and JSON object keys use lexical order. Missing
owned schemas, relations, constraints, views, indexes, or required extensions therefore change the
digest rather than disappearing behind query-order or cursor-shape differences.
