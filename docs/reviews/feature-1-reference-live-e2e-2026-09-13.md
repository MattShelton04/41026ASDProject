# Feature 1 complete local reference verification — 13 September 2026

This report records actual application runs and full exported-artifact validation. It is distinct
from [implemented capability](../release-1/reference-data-operations.md) and the earlier
[local-state audit](feature-1-dataset-audit-2026-09-13.md). The new products remain review candidates;
no accepted local pointer has been changed and no downstream integration has been added.

## Completed artifact checks

Every record in the artifacts below was parsed against `ReferenceFeatureRecord`, checked for the
correct dataset/release/generation provenance and strictly increasing `(layer, record_id)` keys.
Whole compressed byte counts and SHA-256 matched the manifest; complete row counts matched the
validated source acquisition. Invalid publisher topology is retained and flagged, not repaired.

| Dataset | Records | Compressed bytes | Geometry: valid / invalid / absent | Local state |
|---|---:|---:|---|---|
| `abs-cpi` | 680 | 47,154 | 0 / 0 / 680 | Awaiting review |
| `abs-geography-2021` | 4,675 | 80,887,860 | 4,668 / 3 / 4 | Awaiting review |
| `nsw-amenities` | 9,866 | 27,961,787 | 9,857 / 9 / 0 | Awaiting review |
| `nsw-flood-planning` | 622 | 13,898,811 | 611 / 11 / 0 | Awaiting review |
| `nsw-planning-controls` | 235,350 | 551,891,331 | 234,783 / 567 / 0 | Awaiting review |
| `nsw-school-catchments` | 2,191 | 12,240,226 | 2,191 / 0 / 0 | Awaiting review |
| `nsw-strata-schemes` | 88,926 | 31,908,471 | 88,922 / 4 / 0 | Awaiting review |
| `nsw-suburb-boundaries` | 4,607 | 89,495,228 | 4,606 / 1 / 0 | Awaiting review |

## Measured task durations

These are elapsed worker-task seconds on this retained local environment, not portable completion
estimates. Import tasks include loader queue/recovery time. The final column separates observed
loader-start to task-finish time where exposed, including final coordinator polling. Flood includes
an initial loader integration correction. Resumed tasks show their final recorded attempt; failed
acquisitions and service interruptions are retained in run history, not clean throughput benchmarks.
Resumed operations can retain earlier attempt timestamps; their loader interval is not reported
as continuous active runtime.

| Dataset | Discovery | Acquisition | Import task | Complete export | Loader-start to import-task finish |
|---|---:|---:|---:|---:|---:|
| `abs-cpi` | 1.69 | 0.21 | 1.07 | 0.21 | 0.87 |
| `abs-geography-2021` | 0.11 | 36.07 | 58.35 | 37.34 | 57.31 |
| `nsw-amenities` | 6.77 | 65.50 | 1437.71 | 32.86 | 36.69 |
| `nsw-flood-planning` | 0.51 | 17.13 | 163.03 | 6.54 | 11.87 |
| `nsw-planning-controls` | Cached | Cached | 504.76 | 441.36 | 503.99 |
| `nsw-school-catchments` | 2.63 | 8.58 | 9.26 | 4.38 | 8.36 |
| `nsw-strata-schemes` | 0.57 | 76.57 | 1485.82 | 89.78 | 52.12 |
| `nsw-suburb-boundaries` | 0.23 | 100.48 | 0.51 | 96.65 | Recovered operation |

## Immutable artifact references

- `abs-cpi`: release `e9df11fb-5221-4746-ad0d-d8066405855e`; SHA-256 `b5166fee9b28c147b2591e2f8a67236fc42381ecfd92ce58b6ec2cd8e02e563d`.
- `abs-geography-2021`: release `d91279f1-5628-44ea-a037-f8de0a0ad4ff`; SHA-256 `26a6429d9431136a76165c58678baaf74a4f6284abbbd706f43dfa8fd3fe9410`.
- `nsw-amenities`: release `36460dde-c3fe-4ca4-8e5e-f3c12c645bcd`; SHA-256 `f9f371f007291c9319dbc02253d3aabb6f4a5ded2c8aee1ae7241e499596734b`.
- `nsw-flood-planning`: release `3949d345-2310-4205-b2d6-f3c350cbaf9d`; SHA-256 `01a2ef6caeb852e2f7c4cad49ffa996fa41339c49d2db030645665a3127fa785`.
- `nsw-planning-controls`: release `b42dd939-de0a-4b6c-8eee-cdac7ccc68a7`; SHA-256 `a442cf43d3db3a6c10dc9055b62ae06e32579b1e15dc27e6fa8e0b6cd67f1625`.
- `nsw-school-catchments`: release `ab41d18a-fa19-4cdd-aae7-312052da814c`; SHA-256 `80cd3dc2ee54b323f0e0567d52933eae6a088c4f4b83c0bbc6cc87f660e05d12`.
- `nsw-strata-schemes`: release `1b4b88b0-07f3-4e8d-a8f2-90e588b1d52a`; SHA-256 `efbed2a1ce002f734ad6feee62d2a961b69c71dc17b78a874b7946e6b4841656`.
- `nsw-suburb-boundaries`: release `a5a79703-da08-47e0-b281-c37d531263c5`; SHA-256 `c5eba794d619fc7074b83e0269d4a6fb4996ef1344d4af9d502933dba245ed9c`.

## Validation and limits

The canonical `uv run python scripts/check.py` completed successfully: 943 shared/script,
857 Feature 1, 24 Feature 2, 105 Feature 3, 83 Feature 4 and 136 Feature 5 Python tests passed,
plus 222 frontend tests. Default-run skips cover platform-dependent cases and opt-in PostgreSQL
tests. Separately, 29 reference/resume integration tests passed against disposable PostGIS
databases; independent final BFPL/reference review passed 82 focused tests. Two additional BFPL
streaming regressions and the synthetic BFPL lifecycle with migration 063 passed afterward.

The actual ten-record BFPL neighborhood containing a 47,393,221-byte feature also passed the
complete isolated HTTP/PostGIS/import/export path. All ten canonical records, 1,178,661 coordinate
positions and source hashes matched the export; nine geometries were valid and one invalid.
Its gzip export was 17,678,682 bytes. Test-body time was 54.76 seconds, with about 564 MiB peak
Python working set for the combined in-process harness, excluding PostgreSQL. It was submitted
for review only in the disposable database and is not a complete BFPL dataset.

The [PSI report](feature-1-psi-matching-2026-09-13.md) records the separate full-data matching
comparison and export. The reference-source reports explain scope, coverage, edition and licence
limits, including flood-planning controls that cannot establish absence of flood risk.

The remaining source-scale runs are still being validated. A publisher count or partial acquisition
is not presented as a completed local dataset; this report is updated only after full artifact checks.
