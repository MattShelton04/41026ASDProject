# Feature 1 spatial source verification — 13 September 2026

This records actual unauthenticated publisher HTTP reads and source-adapter checks. It
supplements, and does not replace or alter, the preserved
[dataset audit](feature-1-dataset-audit-2026-09-13.md). Counts describe the publisher at
verification time. They do not establish an accepted local release or downstream integration.

## Verified inventory

| Registered profile / layer | Publisher count | Native CRS | Publisher page limit |
|---|---:|---|---:|
| `nsw-cadastre` / Lot | 3,355,160 | EPSG:7844, GDA2020 | Default 100; standard 4,000; adapter selects standard 2,000 |
| `nsw-planning-controls` / Heritage (0) | 40,340 | EPSG:4283, GDA94 | 1,000 |
| Floor Space Ratio (1) | 40,431 | EPSG:4283 | 1,000 |
| Land Zoning (2) | 70,442 | EPSG:4283 | 1,000 |
| Minimum Lot Size (4) | 42,625 | EPSG:4283 | 1,000 |
| Height of Building (5) | 41,512 | EPSG:4283 | 1,000 |
| `nsw-bushfire-prone-land` | 235,550 | EPSG:3857 | 2,000; adapter initially uses 1,000 |
| `nsw-flood-planning` | 622 | EPSG:4283 | 1,000; adapter uses 100 |

Counts were read with `query?where=1%3D1&returnCountOnly=true&f=json`; metadata
with `?f=json`. All layer metadata advertises deterministic ordering and pagination.
The five EPI counts establish that the prototype's exactly 5,000 features per layer
were incomplete extracts, not full coverage.

## Cadastre

The active source is the official [GDA2020 Lot layer](https://portal.spatial.nsw.gov.au/server/rest/services/NSW_Land_Parcel_Property_Theme_multiCRS/FeatureServer/8).
Its [publisher item](https://portal.spatial.nsw.gov.au/portal/home/item.html?id=079705a7798742e6b13b6da2171e5991)
identifies the replacement for the old GDA94 service. The old
`NSW_Land_Parcel_Property_Theme/FeatureServer` is explicitly marked for retirement.
The adapter follows the replacement, with native EPSG:7844 and `OBJECTID` as its
paging identifier. The old service used EPSG:3857 and lowercase `objectid`.

Lot records retain `cadid`, `lotidstring`, `lotnumber`, `sectionnumber`, `planlabel`,
`plannumber`, `itstitlestatus`, `stratumlevel`, `hasstratum`, area and units,
`shapeuuid`, and source dates. A lot can represent standard lots, part lots,
strata or stratum. These facts do not establish a one-to-one property/address link.
The Property layer (12) was inspected: 4,224,294 records, identifiers including
`propid`, `gurasid` and `principaladdresssiteoid`. It is deliberately excluded from
the initial Lot integration; no unvalidated crosswalk is manufactured.

The publisher describes statewide coverage and daily refresh, with changes possibly
taking two days to appear. Its displayed data-currency value `01/01/3000` is not a
current edition date. Discovery retains a metadata fingerprint and the publisher's
edition marker only when present; row dates remain explicit source fields.

The item declares open access and Creative Commons terms, with attribution to the
State of NSW / Spatial Services, Department of Customer Service. Its licence links
point to [portal terms](https://portal.spatial.nsw.gov.au/portal/apps/sites/#/homepage/pages/terms-of-service)
and [Spatial Services copyright](https://www.spatial.nsw.gov.au/copyright).
The copyright page initially returned HTTP 403 to the verification client. A
subsequent official-page verification by the coordinating reviewer resolved the
terms: Spatial Services material on its own sites is licensed under Creative
Commons Attribution 4.0 unless otherwise stated, with exclusions for third-party
material, logos and images. The current Lot item declares Creative Commons and
does not state additional restrictions. Section 3 of the official
[web-services terms](https://www.spatial.nsw.gov.au/products_and_services/web_services)
also requires attribution with the source date. The source register therefore
uses `cc-by-4-0` and permits attributed derived releases; the initial HTTP 403 is
an access observation, not an unresolved licence restriction.

## EPI planning controls

The five layers use the [EPI Primary Planning Layers service](https://mapprod1.environment.nsw.gov.au/arcgis/rest/services/Planning/EPI_Primary_Planning_Layers/MapServer).
The adapter retains the whole attribute dictionary, including instrument name,
LGA, publication/commencement/currency dates, amendment, legislative references,
and control-specific fields. In particular:

* zoning preserves `SYM_CODE`, `LAY_CLASS` and `PURPOSE`;
* FSR preserves `FSR` and legislative exceptions;
* minimum lot size preserves `LOT_SIZE` and `UNITS`;
* height preserves `MAX_B_H`, `UNITS`, `MAX_B_H_M` and `MAX_B_H_RL`, without
  confusing metres above ground with reduced levels;
* heritage preserves `H_ID`, `H_NAME`, `SIG` and `LAY_CLASS`.

The publisher catalog API returned `license_id=cc-by` and Creative Commons
Attribution, without an explicit version, for the exact
[zoning](https://www.planningportal.nsw.gov.au/opendata/dataset/environment-planning-instrument-local-environmental-plan-land-zoning),
[FSR](https://www.planningportal.nsw.gov.au/opendata/dataset/environmental-planning-instrument-floor-space-ratio),
[minimum lot size](https://www.planningportal.nsw.gov.au/opendata/dataset/environmental-planning-instrument-minimum-lot-size-lsz),
[height](https://www.planningportal.nsw.gov.au/opendata/dataset/environmental-planning-instrument-height-of-buildings-hob),
and [heritage](https://www.planningportal.nsw.gov.au/opendata/dataset/environmental-planning-instrument-heritage-her)
datasets. Retain the catalog's attribution to NSW Government and the Department
of Planning, Housing and Infrastructure. These are source controls, not a computed
development entitlement, legal opinion, or automated parcel applicability result.

## Bushfire and flood semantics

[Current hosted BFPL](https://portal.spatial.nsw.gov.au/server/rest/services/Hosted/NSW_BushFire_Prone_Land/FeatureServer/0)
uses `fid` identifiers and retains `category`, `d_category`, `guideline`,
`d_guidelin`, `startdate`, `enddate`, `lastupdate`, `area` and `shape_leng`.
The [publisher item](https://portal.spatial.nsw.gov.au/portal/home/item.html?id=84c338fe2e8c49a9836751ed49c9c581)
is public, owned by `nswrfs`, and specifies Creative Commons attribution with
the text **NSW Rural Fire Service 2026**. The item does not specify a licence
version; the [SEED dataset](https://datasets.seed.nsw.gov.au/dataset/bush-fire-prone-land)
API explicitly returned Creative Commons Attribution 4.0 and its licence URL.
BFPL is development-control mapping. Being outside it does not establish freedom
from bushfire risk; categories and guideline versions must remain distinguishable.

The hosted service replaces the initially inspected legacy BFPL MapServer in this
adapter. The legacy service advertised 235,537 rows but repeatedly failed to
serialize the geometry of `OBJECTID=189377`, even in native-CRS Esri JSON and
direct-ID queries. The current hosted service advertises 235,550 rows. Its
`fid=189388` has the same category, area, retained length and source dates as that
legacy feature, and successfully returns its complete geometry: 739 rings and
1,176,284 positions. Fetching that one polygon in EPSG:4326 took 36.416 seconds;
ring conversion took 0.935 seconds and produced a 47,392,889-byte GeoJSON feature.
These bounded checks establish a working serialization alternative; they do not
establish whole-layer acquisition, matching identity across editions, or an
accepted local release. No polygon is omitted or simplified. The source's year-3000
end-date sentinel remains in raw attributes and maps to an open normalized end.

[Flood planning](https://mapprod1.environment.nsw.gov.au/arcgis/rest/services/Planning/EPI_Protection_Layers/MapServer/1)
is a published EPI planning-control layer, not modelled inundation or an SES study
extent. Its [official catalog](https://www.planningportal.nsw.gov.au/opendata/dataset/epi-flood)
declares Creative Commons Attribution, identifies edition 22/05/2019, and warns
that councils became responsible for flood mapping on 14 July 2021 and that this
dataset may not be current. Each normalized record explicitly retains:

* `evidence_kind=flood-planning-control`;
* `aep_percent=null`, `flood_scenario=null`, `study_extent=null`;
* `absence_interpretation=unknown`.

The SES [Flood Data Portal catalog](https://flooddata.ses.nsw.gov.au/api/3/action/package_search?rows=1)
reported 4,433 packages. The inspected current package, `1-bbay-frmsp-reports`,
had third-party licence terms and a **Point** spatial catalog location, not a
study boundary or inundation polygon. This confirms why catalog geometry must
not be recast as hazard coverage. The old prototype's 93,809 polygons across a
few studies, including unknown AEP and empty geometries, are not promoted.
SES resource ingestion remains outside these four profiles until resource-specific
licences, accessible files, study boundaries and scenario metadata are validated.

## Reader behavior and validation evidence

`adapters/arcgis.py` reads bounded pages with increasing OIDs. Cadastre discovery
reads minimum/maximum OIDs (1 and 4,136,008 in the verified service) and partitions
that interval across four workers. Each worker has one page in flight; deterministic
round-robin consumption retains reproducible ordering without buffering a whole
partition. Other sources default to serial reads. Fixed publisher filters, when
specified by a registered source, are preserved in discovery, pages and final
count checks. Short pages do not
end acquisition. Missing/repeated IDs, invalid responses, duplicate inventory,
count mismatch, changed count and changed metadata fail the run. Every stream
must finish before the caller treats the acquisition as complete. No operator
row cap or prototype cache enters the reader. HTTPS hosts are explicitly allowed,
redirects are disabled, reads have a 120-second timeout and transient transport /
429 / 5xx errors receive at most three attempts. Each response is limited to 64 MiB.

Geometry is requested as EPSG:4326 while native CRS is recorded separately. The
NSW Spatial portal advertised GeoJSON but repeatedly returned HTTP 503 for even
two features in that format. Projected Esri JSON works; the adapter uses the
existing `pyshp` ring organizer to preserve holes and disconnected polygons,
rejecting ambiguous ring topology instead of silently filling holes.

The flood endpoint returned HTTP 200 with a 7,058-byte HTML error for a 1,000-row
request (13.27 seconds). A 100-row request returned 7,030,886 bytes of valid GeoJSON
in 2.19 seconds. The profile therefore uses 100-record pages. A complete adapter
run read and reconciled all **622** features in **16.58 seconds**.

Live first-page validation succeeded for all five EPI layers and BFPL. Three
complete GDA2020 cadastre pages normalized **3,000** rows in **13.41 seconds**,
ending at OID 3,812. A subsequent four-worker smoke check consumed **8,000** rows
across all four OID ranges in **35.50 seconds**, including discovery and clean
worker shutdown. The samples cover different polygons and cannot establish a
speedup ratio. These are small transport/normalization benchmarks, not a
statewide load or publication timing. No full cadastre/EPI/BFPL acquisition is
claimed by these adapter checks. Root task runtime evidence records any subsequent
full application imports independently.

Seventeen deterministic adapter tests passed, covering capped/short pages, changed
counts, duplicate IDs, profile inventories, forbidden endpoints, CRS, polygon
holes, multipolygons, flood semantics, serial/parallel record parity, deterministic
parallel ordering, incomplete parallel runs and fixed-filter continuity. Targeted
Ruff and mypy checks passed. Combined targeted branch coverage was 79% across the
two adapter modules.
The parent task owns the canonical repository-wide check and application lifecycle
validation; this source-adapter evidence does not substitute for them.

ArcGIS services do not supply transactional snapshot isolation here. Count and
metadata reconciliation detect many changes, but same-count feature edits without
an updated publisher edition marker can evade those guards. Immutable acquired
artifacts and per-record dates preserve what was actually read; a metadata digest
must never be labelled a publisher-issued dataset edition.

## Final paging improvements

A subsequent live metadata check confirmed `maxRecordCount=100`,
`standardMaxRecordCount=4000` and `supportsQueryWithResultType=true` on the current Lot
service. Cadastre alone opts into `resultType=standard`, capped at 2,000 and the advertised
standard limit. Unsupported services retain the ordinary advertised limit. This follows the
[official Esri query documentation](https://developers.arcgis.com/rest/services-reference/enterprise/query-feature-service-layer/).

A controlled benchmark read the same 8,000 records over four fixed OID ranges. Full-feature
hashes matched across all three modes:

| Mode | Requests | Wall seconds | Client CPU seconds | Decoded response bytes | Largest response |
|---|---:|---:|---:|---:|---:|
| Default / 100 | 80 | 14.177 | 0.375 | 11,620,660 | 593,830 |
| Standard / 1,000 | 8 | 4.039 | 0.625 | 11,442,100 | 2,156,515 |
| Standard / 2,000 | 4 | 3.415 | 0.219 | 11,432,180 | 3,818,424 |

Response envelope repetition explains the byte differences; feature hashes were identical.
This bounded sample establishes a transport improvement, not a statewide runtime estimate.
The original slower application attempt was cancelled through the supported API and retained
for audit before starting a new discovery with this mode.

Actual EPI pages also returned recognizable HTTP-200 HTML error pages, while complex geometry
can exceed the 64 MiB response bound. The reader now halves the page size at the unchanged
OID cursor for these two specific size-related failures, remembers the smaller size for that
stream/range, and fails if even one feature cannot be read. It does not suppress malformed
JSON, publisher error objects, bad CRS or invalid feature structure. Flood remains capped at
100 and NPWS reserve pages at 25. Thirty-six spatial tests cover these final changes.

The full BFPL application read exposed a second publisher size failure at `OBJECTID>96000`: a
1,000-feature GeoJSON request returned HTTP 500 and 618 bytes of ArcGIS HTML stating
`Error performing query operation`. A 500-feature request at that same cursor succeeded with
28,739,763 bytes. The reader now recognizes only this HTML error on a bounded feature query
after three ordinary HTTP retries, then halves the unchanged page. A live adapter test returned
all IDs 96001–96500 in 53.166 seconds including failed retries; 48 spatial tests and independent
review confirmed unchanged handling for generic 500, 503, authentication, JSON and discovery errors.

The later legacy BFPL failure at `OBJECTID=189377` was not recoverable by smaller
JSON pages; the current hosted-source replacement and exact polygon check are
recorded above. A ten-feature hosted query for `fid=189388..189397` returned
47,493,075 decoded response bytes in 27.979 seconds. Canonical conversion and gzip
writing completed in 41.591 seconds. Its largest canonical record was 47,393,221
bytes; the nine adjacent records were 2,043–36,317 bytes each. This is a complete
ten-ID verification filter, not a whole-layer release.

Page sizing now recovers after isolated large features: eight full successful pages
using no more than one sixteenth of the response-byte ceiling permit doubling the
page size, up to the original discovered/profile limit. Three failed growth probes
require 64 such small pages before each subsequent probe; successful growth resets
that cooldown. Failures still retry the unchanged cursor and retain all features.
The policy is independent for each parallel OID range and never raises the byte cap.

A bounded live check read identical full-feature hashes for hosted IDs
189389–189420. Fixed one-record pages required 32 requests, 683,904 decoded bytes,
2.769 seconds wall time and 0.094 seconds client CPU. Recovery used eight pages of
one, eight of two and two of four: 18 requests, 660,104 bytes, 1.257 seconds wall
time and 0.016 seconds CPU. This small sequential comparison establishes record
parity and working recovery; it is not a whole-source speed estimate. All 52 spatial
tests, targeted Ruff checks and both adapter-module mypy checks passed after the
hosted-source and recovery changes.

## Exact large-polygon database and export validation

The retained ten-ID publisher sample, including the 47,393,221-byte canonical
record, subsequently passed the real acquisition/import/export HTTP pipeline
against a uniquely named disposable PostGIS database with all migrations through
`063_bfpl_current_hosted_source.sql`. The external publisher boundary read the
exact cached sample; database, loader, backend, runner and artifact paths were real.
The test never accessed the retained development database.

All ten records and 1,178,661 geometry positions were imported. PostGIS classified
nine geometries valid and one invalid; the invalid geometry was retained without
repair. The exported gzip contained 17,678,682 bytes. Every exported canonical
field, complete geometry hash and provenance source-record hash matched the input.
The sample was submitted to review for download verification, but was not
published, and no accepted-generation pointer was created. The fixture dropped
its isolated database afterward.

The verification body took 54.76 seconds; the full pytest invocation took 62.44
seconds. Windows reported a peak Python working set of 591,245,312 bytes (about
564 MiB) for this combined in-process backend, database API, runner and loader
harness; that measurement excludes the PostgreSQL container and is not a
production deployment memory estimate. The exact sample and local-only harness
remain in ignored `tmp/bfpl_hosted_189388_189397.ndjson.gz` and
`tmp/test_bfpl_large_e2e.py` respectively.

Two deterministic regressions confirm that serial BFPL export projects a row
before requesting the next row, avoiding accumulation of another 255 large
polygons. The existing synthetic BFPL HTTP lifecycle also passed with migration
063 (8.42 seconds), and the edited regression file passed Ruff lint and formatting.
These checks are producer-side evidence; they do not establish a complete hosted
BFPL acquisition or authorize a live publication.

## Publisher projection of thin BFPL polygons

A later full hosted-source attempt exposed `fid=21` in the first page: the
publisher returns `rings=[]` in EPSG:4326, including direct GeoJSON requests, but
its native EPSG:3857 geometry is a closed four-position triangle. Two vertices
are 3.4 mm apart; retained publisher measurements report area 0.17031858 square
metres and perimeter 239.53067536105303 metres. It is therefore not missing source
geometry. Setting precision 15, zero allowable offset, or a smaller requested
geographic tolerance did not prevent the publisher from returning empty rings.

Only the verified hosted BFPL source now enables a fallback for this exact
projected-empty representation. It reads that same ID in native EPSG:3857,
requires identical attributes and a matching source CRS, and transforms every
position using the already installed pyproj with explicit longitude/latitude
ordering. It neither closes nor repairs rings. Missing, empty, unclosed or
malformed native geometry, changed identity/attributes and unsupported sources
still fail. Native coordinates and the publisher's empty projected representation
remain in the explicitly named `_propertyscope_geometry_provenance` attribute;
reserved-field collisions fail. The original page plus fallback responses retain
the combined 64 MiB byte ceiling.

The corrected first 1,000 records normalized in 2.37 seconds. A separate paired
check of the same 1,000 IDs read 7,565,971 native bytes and 7,476,855 projected bytes
in 2.185 and 2.590 seconds respectively. All attributes matched. Feature 21 was
the only ring/position-count difference (one ring/four positions to zero/zero);
the other 999 features retained matching counts. This bounded comparison does
not establish the absence of partial projection losses across the whole layer.
All 63 focused spatial tests, targeted Ruff checks and both adapter-module mypy
checks passed. Independent review also exercised provenance collisions, the
combined response limit and malformed projected rings without identifying an
outstanding code issue.

The exact recovered feature also passed the isolated real HTTP/PostGIS
acquisition/import/export harness: one valid polygon with four positions, an
823-byte gzip export, and matching canonical, geometry and native-provenance
hashes. The verification body took 1.924 seconds (11.97 seconds including the full
pytest fixture lifecycle). It remained awaiting review without publication or an
accepted pointer, and the disposable database was dropped afterward. The small
exact sample is retained in ignored `tmp/bfpl_hosted_fid21.ndjson.gz`.

### Further complete-run boundary cases

The complete 235,350-record planning artifact contains exactly one canonical record larger
than 16 MiB: `land-zoning:890585`, at 19,615,386 bytes. A full artifact scan established that
maximum, so planning now has a separate 32 MiB allowance. Its corrected import reuses the
verified 1,694,382,363-byte canonical artifact rather than repeating the 19m41s acquisition.
The failed attempt remains recorded; other source profiles retain their existing bounds.

The full BFPL run also exposed native feature `fid=169866`: its supplied thin triangle
changes apparent winding when its four vertices are transformed to geographic coordinates.
Ring membership is now determined in the validated native CRS and retained through projection,
instead of reclassifying the exterior as a hole. No positions are added, removed or repaired.
The local conversion marker cannot originate in publisher JSON, and ambiguous native topology
still fails explicitly. Both publisher representations remain in provenance.

The exact feature passed isolated HTTP/PostGIS/export validation as one valid polygon with
four positions, matching all canonical and native-provenance hashes; its gzip export was
844 bytes. Test-body time was 1.697 seconds (11.91 seconds including fixtures). All 96 spatial
and reference unit tests passed, and independent review found no outstanding issue in these
two corrections. The disposable sample remained awaiting review and was never published.
