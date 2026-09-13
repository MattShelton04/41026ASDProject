# Feature 1 dataset audit — 13 September 2026

Improve delivery, freshness and identity matching before expanding the source catalogue. Keep the
five existing official sources. The strongest additions are NSW cadastre and planning controls for
Feature 4, and geography boundaries, school catchments, amenities and public transport for Feature 3.
Feature 5 benefits through those features' evidence APIs and does not need its own bulk acquisition.

This is a recommendation and read-only runtime audit, not an implementation or publication record.
The failed consumer imports, synthetic accepted school release and cached address edition below
describe this local environment at the time of inspection. They do not mean the application lacks
official school acquisition, SEIFA delivery, or publisher discovery support. Application capability
is established by its registered implementations and tests; local readiness is established by the
specific run, release and consumer evidence.
It compares the current repository at `aabbac0`, the running `ps-dev` environment, and the earlier
project at `C:\git\prototype\property`. The [Release 0 report](../reports/release-0-technical-report.md)
explains feature intent; current code and live accepted releases establish today's behaviour.

## What the other features need

| Feature | Actual purpose | Most useful data improvement |
| --- | --- | --- |
| 2 — Property Sales Explorer and Market Cases | Property-linked recorded sales, date/match filters, deterministic counts/medians/volume, saved cases and evidence explanations. | Better PSI identity linkage and quality flags first; optional CPI for explicitly requested inflation-adjusted historical comparisons. |
| 3 — Suburb Crime and Liveability Analytics | Suburb search, maps, filters, amenity context, saved comparisons and explanations; separate consumer for official crime, schools and SEIFA. | Activate existing school/SEIFA evidence, then boundaries, catchments, amenity points and transport timetables. Add selected Census context where a comparison uses it. |
| 4 — Site Planning and Building Due Diligence | Site reviews, planning/environment/building/strata evidence, checklists and questions for professional verification. | Parcel identity and boundaries, EPI planning layers, bushfire/flood evidence, strata schemes and published building actions. It currently has no registered Feature 1 planning/hazard/building product. |
| 5 — Buyer Journey and Agent Workspace | Buyer cases, shortlists, stages, notes and tasks; composes evidence from Features 1–4. | Reliable, dated evidence and clear availability states from the other features. No separate bulk dataset is necessary for the existing workflow. |

Feature 1 should publish versioned source facts, identity links, spatial evidence and provenance.
Feature 2 owns statistical exclusions and calculations; Features 3 and 4 own their comparisons and
due-diligence interpretation. A new producer adapter alone will not make a dataset usable: the
consuming owner needs a contract, import/query path and presentation. This follows the current
[consumer guide](../../student-1/DATA_PRODUCT_CONSUMER_GUIDE.md) and
[shared architecture](../architecture/shared-platform-design.md).

## Existing datasets: live findings

Counts below refer to the accepted product, unless explicitly marked as a candidate. They are not
counts of unique physical properties or independent transactions.

| Dataset | Live state | Decision |
| --- | --- | --- |
| G-NAF NSW | 5,190,134 accepted address records; accepted 5 September. The configured ZIP is the **February 2026** edition. | Keep; refresh the source edition and enrich its identity/quality fields. |
| NSW PSI sales | 7,402,643 accepted source records/revisions, with annual archives from 1990 and weekly files through 31 August 2026. Feature 2 delivery succeeded. | Keep history and source detail; improve matching, date checks and transaction interpretation. |
| BOCSAR crime | 318,122 accepted geography/category series; Feature 3 has activated the full release. | Keep; distinguish geography-specific coverage and reduce repeated transport metadata. |
| ABS SEIFA 2021 | 4,320 accepted NSW SAL records. Feature 3's attempted import failed and remains inactive, although the artifact now downloads successfully. | Keep; reconcile the consumer import and add matching boundaries. |
| NSW government schools | Accepted release is still **10 synthetic showcase records**, and its artifact returns HTTP 503. A real **2,210-school candidate** exists with both recorded quality checks passing. | Review/publish the real candidate and verify Feature 3 activation before adding more school sources. |

The separate three-record `fixture-property` product remains useful for deterministic demonstrations
and tests. Keep its synthetic identity explicit. The obsolete synthetic school release should remain
historical demonstration evidence after a real replacement is accepted.

### G-NAF: useful fields are being discarded

A complete streaming scan of the cached NSW `ADDRESS_DETAIL` member found exactly 5,190,134 rows,
matching the accepted count. It found no populated `DATE_RETIRED` values in that member. The current
[G-NAF projection](../../student-1/backend/src/propertyscope_data_platform/adapters/gnaf.py) retains
core address components, coordinates and geocode type, but omits several useful source fields:

| Source field or relationship | Evidence in the complete cached NSW address-detail file | Proposed use |
| --- | ---: | --- |
| `LEGAL_PARCEL_ID` | 4,716,170 populated, about 90.9% | Starting point for a validated address-to-parcel/lot-plan bridge. |
| `GNAF_PROPERTY_PID` | 4,109,615 populated, about 79.2% | Preserve the jurisdiction's property identifier; investigate a validated PSI/cadastre crosswalk. |
| `ADDRESS_SITE_PID` | All 5,190,134 populated | Group addresses belonging to a source address site without equating a site with a legal parcel. |
| Alias/principal and primary/secondary relationships | 301,742 alias address records; 1,865,378 marked secondary | Resolve alternate addresses and unit/building relationships; retain the corresponding relationship-table links, not just flags. |
| Building, level and lot components | 221,381 building names; 48,933 level numbers; 2,280,649 lot numbers | Improve address display and matching of apartments, named buildings and rural/lot addresses. Preserve remaining number/street prefixes and suffixes where supplied. |
| Source confidence | All rows populated: 3,147,670 at 2; 776,559 at 1; 988,189 at 0; 277,716 at -1 | Preserve source quality independently from PropertyScope's identity-match confidence. |
| Address-to-2021 Mesh Block mapping | Mapping member exists in the ZIP; currently unused | Support a geography bridge with an explicit ABS vintage and mapping quality. |

Geoscape describes the parcel and jurisdiction-property fields in its
[data dictionary](https://docs.geoscape.com.au/projects/gnaf_desc/en/stable/appendix_c.html).
Their population does not prove a unique, correct join to PSI or a parcel polygon. Validate match
cardinality, jurisdiction, edition and exceptions before using those links. In contrast,
`PROPERTY_PID`—a different field—was empty in every scanned row, so it has no immediate value as a
materialised column for this edition.

There are two further issues:

* **Source freshness:** the ZIP member explicitly names `G-NAF FEBRUARY 2026`. The current
  [runner](../../student-1/backend/src/propertyscope_data_platform/runner.py) selects a configured
  cached ZIP before publisher discovery, so a new ingestion date can still represent old source
  data. Record/display publisher edition, effective date, retrieval date and cache origin separately.
  Geoscape has published [August 2026 release documentation](https://docs.geoscape.com.au/projects/gnaf_release/en/aug-2026/future_considerations.html).
* **Spatial precision:** a reproducible database block sample contained 872 `STL` and 80 `LOC`
  geocodes among 25,210 current rows, about 3.8% of this sample. These are street/locality locations,
  unsuitable as exact parcel positions. A public map-context check confirmed that such a record
  returns coordinates without its geocode type. Carry precision into downstream map/intersection
  contracts and preserve an unknown result when precision is insufficient. The existing match score
  of 1.0 concerns identity resolution; it does not establish survey accuracy.

Keep aliases and low-confidence source records as evidence; do not simply delete them to make the
address count look cleaner. Likewise, a null warehouse `property_ref` is not itself proof of a
broken address: the current serving path supports lazy deterministic property identity.

### PSI: strong coverage, weaker interpretation and linkage

An exact aggregation of the accepted generation found **4,940,715 exact-address links (66.74%)**
and **2,461,928 unmatched records (33.26%)**. That is a substantial limitation for property-specific
history, although an unmatched sale still retains useful source facts. The
[import linkage quality rule](../../student-1/database/src/propertyscope_data_store/import_profiles.py)
only requires `minimum_linked: 1`; it would not catch a major proportional regression.

Add linkage coverage by source era, locality and address kind, with an agreed regression threshold.
Investigate principal/alias handling and publisher property identifiers before introducing broader
matching. Keep ambiguity explicit. The prototype's much lower reported unmatched rate is not an
equivalent benchmark: its matching included locality-only links that are unsuitable for a specific
property's sale history.

Exact bounded date queries found **three contract dates of 1900-01-01** and **eight contract dates
after 13 September 2026**, including 2031. Some records have settlement dates years before their
contract dates. Consequently, the manifest's 1900–2031 min/max dates are not a credible statement of
the source archive's historical coverage. Store archive coverage separately from observed event-date
extrema, and flag exceptional chronology without rewriting publisher facts.

A public sale-history check also returned two $950,000 observations for one property with the same
dealing/date but different source business keys and revisions. This is evidence to investigate
transaction/component/revision semantics, not proof that either source row should be deleted.
Feature 2's [summary function](../../student-2/backend/src/propertyscope_market_intelligence/domain.py)
currently excludes missing dates, out-of-window dates, missing/nonpositive prices and insufficient
match tiers. It does not independently resolve dealing/component duplication, nominal nonzero
transfers, unusual interests or contradictory chronology.

Retain the existing dealing/property IDs, source revisions, sale code, interest, component, strata
lot, purpose and area evidence. Add explicit source-quality flags in Feature 1 and agree analytical
inclusion rules with Feature 2. Do not replace missing area, price or dates with invented values.

For context only, a 75,145-row reproducible database block sample contained 558 missing/nonpositive
prices, 130 prices between $1 and $1,000, 19,444 missing areas and nine settlement-before-contract
records. Its unmatched share was about 48.9% before 2001 versus 27.4% from 2001 onward. These are
sample results, not exact statewide prevalence estimates. No full transaction-deduplication audit
was completed.

The source cache also contains the week of **7 September 2026**, whereas the accepted release ends
at **31 August**. Review that refresh gap. The latest Feature 2 delivery is successful; older failed
5,000-row import attempts remain historical records and are not the current delivery state.

### Crime: preserve coverage, make it cheaper to consume

The accepted release has two different temporal scopes:

| Geography | Distinct source geographies | Series | Observed months |
| --- | ---: | ---: | --- |
| Postcode | 622 | 38,564 | January 1995–December 2025, 372 months |
| Suburb | 4,509 | 279,558 | January 1995–March 2026, 375 months |

These are exact accepted-generation aggregates. Show the end date for the selected geography;
the combined manifest's March 2026 endpoint does not apply to every series. Do not combine suburb
and postcode records as if they were the same geography or calculate current rates using an
unqualified 2021 population denominator. The publisher exposes geography-specific products on its
[crime data page](https://bocsar.nsw.gov.au/statistics-dashboards/open-datasets/criminal-offences-data.html).

The sparse positive-count model plus explicit observed-zero coverage is worth retaining. However,
all postcode series share one coverage vector and all suburb series share another. Repeating those
vectors in every exported record is unnecessary transport duplication: a future version could use
shared coverage references while preserving exact zero-versus-missing semantics.

Feature 3's Parramatta published-context response was **2,054,790 bytes** for 62 crime series.
Consider a bounded recent-period response and separately requested history; retain the complete
master release. Do not silently narrow today's complete-source contract. Neither whole historical
crime periods nor an entire geography should be dropped solely to improve response size.

The consumer guide's postcode-only wording is stale relative to the accepted postcode-and-suburb
release. Update that guidance when implementing the follow-up work.

### SEIFA and schools: fix delivery before acquiring replacements

Feature 3 reports failed, inactive imports for SEIFA and the synthetic school release; Parramatta's
published context returns empty population and school arrays. The accepted SEIFA artifact now
returns HTTP 200 with 440,418 bytes, so the failure needs explicit reconciliation/retry investigation.
Availability now does not prove an import has succeeded. The synthetic school artifact still returns
HTTP 503 `artifact_unavailable`.

The real school candidate contains 2,210 records with its schema and row-count checks passing, but
is not accepted. Review it through the normal release workflow and verify consumer activation.
Those two passing checks establish structural readiness, not independent completeness against every
school in NSW.

SEIFA's four indexes and population are useful, small enough to keep in full, and appropriately
labelled 2021. An exact scan found nine null IRSD scores and one zero-population row. Preserve those
nulls and the publisher's statistical limitations. The missing addition is **2021 SAL boundaries
and a defensible geography mapping**, not another copy of SEIFA or its population. Selected Census
age, household, dwelling and tenure measures can add context if Feature 3 uses them. Match vintage
and geographic units through the [ABS boundary files](https://www.abs.gov.au/statistics/standards/australian-statistical-geography-standard-asgs/edition-3-july-2021-june-2026/access-and-downloads/digital-boundary-files)
and [Census DataPacks](https://www.abs.gov.au/census/find-census-data/datapacks).

The [school parser](../../student-1/backend/src/propertyscope_data_platform/adapters/schools.py)
keeps code, name, type, operational status, locality, LGA and coordinates. The prototype's retained
source metadata shows useful additional fields: postcode, website, extract date, enrolment, selective
and opportunity-class attributes. Preserve postcode and source edition/extract date first; add other
attributes only where Feature 3 presents a meaningful filter. Verify them against the current source
schema before changing the contract. The parser defaults to `Open` when operational status is absent;
label this as an operating-school extract rather than a complete school closure history.

Government-school coverage excludes independent and Catholic schools by definition. That is an
explicit source limitation, not evidence that this registered government-school import dropped them.
An all-sector school source would be a separate addition if the intended feature is expanded.
ICSEA is context, not a school-quality ranking. Fax, administrative office contacts, old electorates
and internal reporting hierarchies have little value in the current user-facing product; leave them
in retained raw evidence instead of projecting everything into serving tables.

## Additional datasets to capture

The priorities below reflect fit to the existing features and the evidence available in the
prototype, rather than the number of available adapters.

| Priority | Dataset and minimum useful content | Beneficiaries and reason | Prototype evidence / work still needed |
| --- | --- | --- | --- |
| **1** | **NSW cadastre/property parcels:** source parcel IDs, lot/plan, polygon, edition and validated address links. | F1 identity; F4 parcel-based planning/hazard evidence; F2 matching where verified; F5 through those features. | Regional GeoJSON spike exists. Acquire and validate complete declared coverage rather than treating the spike as statewide. [NSW parcel/property data](https://www.nsw.gov.au/environment-land-and-water/spatial-data-and-mapping/foundation-spatial-data-framework/land-parcel-and-property). |
| **1** | **EPI planning controls:** land zoning, height, floor-space ratio, minimum lot size and heritage, with instrument/layer IDs, units and effective/source dates. | F4's central planning workflow; F5's evidence summary. | Adapter and promoted data exist, but recorded output is exactly 5,000 features per layer. Verify complete pagination, counts and geometry. A polygon result is source planning evidence, not a complete development-permission determination. [Official EPI catalogue](https://www.planningportal.nsw.gov.au/opendata/dataset/?organization=department-of-planning-housing-and-infrastructure&res_format=JSON&res_format=STYLE&res_format=WFS&res_format=WMS&tags=LAND-Use). |
| **1** | **Suburb/SAL/LGA boundaries and government-school catchments:** stable codes, edition, polygons, school-code link, primary/secondary and future applicability. | F3 maps, area joins and catchment context; F1 geography resolution. | Catchment ZIP and ABS research exist, but prototype school promotion retained points only. Keep ABS statistical localities distinct from gazetted localities and postal areas. Catchments change; retain effective dates and a verification link. [NSW catchment source](https://www.data.nsw.gov.au/data/dataset/nsw-education-school-intake-zones-catchment-areas-for-nsw-government-schools). |
| **2** | **NSW RFS bushfire-prone land and selected SES/council flood layers:** category/scenario, study/version, polygon and explicit geographic coverage. | F4 environmental evidence, then F5. | RFS was populated in the prototype. Flood data was concentrated in a small set of studies, with access gaps and unknown scenario tags. Distinguish study footprints, flood extents, AEP scenarios and absent coverage. [RFS layer](https://portal.data.nsw.gov.au/arcgis/rest/services/Bush_Fire_Prone_Land_MIL1/MapServer/0), [SES data access](https://www.ses.nsw.gov.au/flood-resources/nsw-flood-data-access/nsw-flood-data-access). |
| **2** | **Strata scheme register, published building orders/undertakings and NCAT decision metadata:** scheme/plan IDs, verified subject address, action type, status, date and source link. | F4 strata/building observations, then F5. | Prototype recorded 88,468 schemes, 713 decisions, 10 orders and 54 undertakings. Its address-to-scheme bridge was incomplete. An SP number in a judgment can be a cited precedent, not the subject property. Start with reliable register/action facts and verified links. [Strata search](https://www.nsw.gov.au/housing-and-construction/strata/strata-search), [building undertakings](https://www.nsw.gov.au/departments-and-agencies/building-commission/undertakings-building-and-construction). |
| **2** | **Amenity points and TfNSW static GTFS:** parks, libraries, health facilities and other agreed categories; stops, routes, trips, calendars and stop times. | F3 liveability maps and comparisons; F5 indirectly. | OSM spike was a Sydney bounding box capped at 5,000 elements. GTFS adapter existed but the recorded promoted stop/route tables were empty. Start with official amenity layers or a deliberate OSM extract and its licence obligations. Stops alone cannot establish service frequency or commute time. [NSW physical infrastructure](https://www.nsw.gov.au/environment-land-and-water/spatial-data-and-mapping/foundation-spatial-data-framework/physical-infrastructure), [TfNSW complete GTFS](https://opendata.transport.nsw.gov.au/dataset/timetables-complete-gtfs). |
| **3 / small optional addition** | **ABS CPI series:** geography, period, index and reference basis. | F2, if it adds explicitly labelled inflation-adjusted historical sale comparisons. | A validated prototype spike exists, not a production adapter. Revisit the current monthly/quarterly schema and reference basis rather than copying the old fixed workbook URL. F2 owns the adjustment calculation. [ABS CPI methodology](https://www.abs.gov.au/methodologies/consumer-price-index-australia-methodology/jul-2026). |

Catchment source metadata explicitly recommends combining it with the school master and checking
School Finder; the latter updates nightly. Do not promise that a periodically acquired ZIP is equally
current. Published building registers can be partial or change after remediation, so retain observed
status and date; absence of a published action does not establish a defect-free building.

### Defer unless a consuming feature commits to the use

* **Development applications:** useful for F4 site/nearby development history after parcel/planning
  foundations. The prototype recorded zero promoted applications despite having an adapter. The
  [official DA dataset](https://www.planningportal.nsw.gov.au/opendata/dataset/online-da-data-api)
  describes applications from January 2019 with potentially incomplete pre-July-2021 council
  coverage. Treat access and integration as fresh work; applications are not completed buildings.
* **NBN/mobile coverage and road traffic:** relevant F3 context, but secondary to working schools,
  amenities and transport. The prototype NBN projection reduced technology to generic `fixed_line`;
  preserve actual technology where available. Traffic counts are not measured property noise or a
  proven property-price effect. Mobile polygons do not establish indoor reception.
* **Detailed StrataHub/SBBIS defect reports:** prototype per-scheme reports covered only 1,019 of
  88,468 schemes, approximately 1.2%. Do not present that as a comprehensive defects dataset. The
  researched building-bond workflow did not establish a public bulk source of inspection reports.
* **Listings/rents, bedrooms/bathrooms, condition and listing photographs:** potentially valuable
  for an expanded buyer/comparables product, but the prototype listing adapter was disabled and its
  promoted table empty. This is a new authorised-source/licensing effort, not ready-to-reuse data.
  G-NAF and PSI cannot reliably supply all these property attributes.
* **VIC sales, postcode solar totals, sparse EV points and BOM station observations:** lower fit to
  today's NSW feature scope. Postcode solar totals do not establish panels on a particular house;
  weather stations do not replace property-level hazard evidence.
* **Other hazard families:** landslide, coastal, acid-sulfate and contaminated-land sources may be
  relevant to F4 later. The prototype's retained hazard audit records these as unpopulated despite
  stronger claims elsewhere in its catalogue. Do not count them as proven reusable acquisitions.

## What to reduce or avoid

There is no strong case for removing an entire current official dataset. Keep historical PSI,
source revisions, unmatched records, the four SEIFA indexes, crime zero/missing coverage and G-NAF
aliases. Their meaning matters more than a smaller row count.

There is a case for reducing **duplicate storage and repeated payloads**:

* The retention API reports **15,730,077,018 referenced artifact bytes**, about 15.73 GB, separate
  from database and source-cache storage. Its largest object is about **7.35 GB**, retained by
  candidate-release evidence associated with failed/interrupted runs. Review terminal candidate
  lifecycle and archive policy; these references are not proof that immediate deletion is safe.
* PostgreSQL's displayed relation sizes include **13 GB of G-NAF**, **6,149 MB of PSI**, **3,505 MB
  of crime observations** and **653 MB of crime coverage**, including indexes and retained generations.
  These are relation footprints, not the size of one accepted release. Review generation reuse and
  retention before multiplying them with new sources.
* New G-NAF acquisitions already use Parquet. The
  [existing performance review](feature-1-data-performance-2026-09-09.md) documents this change;
  do not rebuild that optimisation as new work. Older accepted artifacts remain immutable evidence.
* Consider shared crime coverage vectors and bounded consumer responses, while maintaining complete
  source acquisition. Avoid replicating raw school administration fields or empty source columns
  into hot serving tables without a consumer need.

For each source, expose publisher edition/effective date, retrieval time, geographic extent,
expected versus imported records, null/quality counts, identity-match coverage and consumer activation.
“Acquired”, “accepted” and “usable in Feature 3” are different states. A recent ingestion timestamp
or passing schema check is insufficient evidence of freshness, completeness or usefulness.

## Suggested delivery order

1. Review the real school candidate, replace the synthetic accepted baseline through publication,
   and reconcile the SEIFA consumer failure. Verify actual school/population results in Feature 3.
2. Correct G-NAF edition/cache visibility, preserve its identity and quality fields, and review the
   newer G-NAF and PSI source releases. Add PSI anomaly and linkage-coverage evidence.
3. Establish parcel and statistical-geography links. Add cadastre/EPI for Feature 4 and catchments
   for Feature 3 with explicit precision, vintage and coverage.
4. Add bushfire and scoped flood evidence, strata/building publications, amenities and static GTFS
   as their consumers are ready. Treat CPI as a small optional Feature 2 enhancement.

## Evidence and verification limits

Primary local sources were the Release 0 report, the current source register, each feature README,
the consumer guide and adapter/import/consumer code. Prototype evidence came from
`docs/DATASETS.md`, `docs/49-dataset-interactions.md`, `docs/43-hazard-coverage-audit.md`, the planning,
schools, ABS, CPI, strata and TfNSW spike notes, adapter implementations and retained source files.
The prototype documents contain conflicting counts and dates; their audit tables describe historical
observations, not a verified current deployment. No old prototype database was assumed to be current.

Live checks used public GET endpoints, container status, and bounded `BEGIN READ ONLY` SQL inside
Feature 1's owning PostgreSQL container. No source acquisition, publication, consumer reimport,
database repair or deletion was performed. No other feature's database was opened. No feature code
was changed; this report is the only workspace addition.

| Dataset | Release inspected |
| --- | --- |
| G-NAF accepted | `291863ec-a12d-4a03-a80c-8f334feae2d0` |
| PSI accepted | `a7078066-1bde-4b31-8b4d-4acab03939e6` |
| BOCSAR accepted | `71537336-0c2d-4f2b-9d2e-dbabc29fa9f9` |
| SEIFA accepted | `0320c071-6ee7-451e-83a6-8a7870252be4` |
| Schools synthetic accepted | `60000000-0000-0000-0000-000000000004` |
| Schools real candidate | `a6ffd6c2-fd5e-4696-85c2-bb228059373b` |

Recheck accepted state at `http://localhost:5200/api/data-platform/v1/data-products`, release detail
at `/dataset-releases/{id}`, its manifest at `/dataset-releases/{id}/manifest`, and consumer state at
`http://localhost:5600/api/suburb-analytics/v1/published/sources`. The Parramatta evidence check used
`/published/context?locality=Parramatta`. Successful Feature 2 delivery has consumer operation ID
`c77a52ee-bb66-47eb-9649-7cba20709f7b`.

The raw G-NAF field scan, PSI linkage aggregate, bounded date anomaly queries, SEIFA aggregates and
crime geography/coverage aggregates were complete for the stated files/generations. Other PSI/G-NAF
quality distributions used `TABLESAMPLE SYSTEM` with `REPEATABLE(913)`, at 1% and 0.5% respectively;
block sampling is not an unbiased row sample and does not certify statewide rates. Some attempted
larger aggregate/distinct scans reached 20–45-second statement timeouts; no completeness or duplicate
count is inferred from them. PostgreSQL row estimates were not treated as exact counts.

Publisher documentation was checked for the recommended additions, but not every feed was downloaded
or its future runtime access proven. A direct current-school CSV retrieval failed from the shell;
suggested extra school attributes are evidenced by the retained prototype extract and require current
schema verification. TfNSW metadata was discoverable but the tool's direct page access was restricted.
A later Geoscape overview request was rate-limited; other official August 2026 documentation was
available. These limits do not affect the measured local release and consumer findings.

`uv run python scripts/check.py` completed successfully during the audit. Opt-in integration tests
skipped by that gate were not enabled; the read-only live checks above are additional evidence, not
a replacement for publication/import integration testing when fixes are implemented.
