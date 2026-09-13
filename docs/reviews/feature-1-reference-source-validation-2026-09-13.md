# Feature 1 reference-source validation — 13 September 2026

This record documents the fixed official-source profiles implemented for Feature 1 reference data.
It separates live publisher evidence from adapter capability and from accepted warehouse state. A
successful discovery or parser run does not mean a source has been published or wired to a consumer.

## Validation summary

| Profile | Declared publisher scope | Live discovery | Complete adapter scan performed |
| --- | --- | ---: | --- |
| `abs-geography-2021` | NSW rows from ABS ASGS Edition 3 SAL and LGA 2021 layers | 4,544 SAL; 131 LGA | Yes: 4,675 records and 4,675 unique IDs |
| `nsw-suburb-boundaries` | Current NSW Spatial Services Suburb layer | 4,607 | Yes: 4,607 records and unique IDs |
| `nsw-school-catchments` | All three shapefile layers in the current publisher ZIP | 1,657 primary; 443 secondary; 91 future | Yes: 2,191 records and unique IDs |
| `nsw-strata-schemes` | Current StrataHub FeatureServer layer | 88,926 | Root ingestion is the complete retained-data validation; an earlier run exposed and led to a stable-ID correction |
| `nsw-amenities` | Seventeen named or explicitly filtered NSW FOI/administrative layers | 9,866 | Yes: every descriptor completed; a profile-wide attempt correctly rejected one intervening publisher metadata change |
| `abs-cpi` | All groups CPI, original series, Sydney and Australia, monthly and quarterly | 680 | Yes: 680 records and unique IDs |

All counts above were read from the live sources on 13 September 2026. ArcGIS discovery records the
publisher count, schema, CRS, extent and a metadata digest. Iteration uses ordered keyset pagination,
then reconciles both count and metadata. The ZIP and CSV adapters fence exact bytes with SHA-256 and
reject changes between discovery and iteration.

## Exact registered endpoints

### ABS 2021 geography

The adapter uses the official ABS ArcGIS services and a fixed publisher-side NSW filter
`state_code_2021='1'`:

* SAL: `https://geo.abs.gov.au/arcgis/rest/services/ASGS2021/SAL/MapServer/0`
* LGA: `https://geo.abs.gov.au/arcgis/rest/services/ASGS2021/LGA/MapServer/0`

Both services report EPSG:3857 and are requested as GeoJSON in EPSG:4326. The retained identifiers
are `sal_code_2021` and `lga_code_2021`; names, state code, Albers area and ASGS URI remain source
attributes. Four official statistical categories have no geometry: the SAL and LGA forms of
“No usual address (NSW)” and “Migratory - Offshore - Shipping (NSW)”. Only their exact publisher
codes are allowed to produce canonical `geometry: null`.

The vintage is fixed in the layer and canonical layer names (`abs-sal-2021`, `abs-lga-2021`). It must
remain explicit in future spatial joins. These 2021 statistical boundaries must not be substituted
for the current gazetted suburb layer.

### NSW gazetted suburb boundaries

The exact GDA2020 service is:

`https://portal.spatial.nsw.gov.au/server/rest/services/NSW_Administrative_Boundaries_Theme_multiCRS/FeatureServer/2`

It reported 4,607 polygons in EPSG:7844. `cadid` is the stable publisher identifier. The projection
retains `suburbname`, state, postcode, start/end dates and last-update fields. The publisher's year
3000 end-date sentinel is retained in raw attributes and becomes canonical `valid_to: null`, meaning
open-ended source validity rather than a claimed real-world expiry in 3000.

The current [Data.NSW GDA2020 administrative-boundaries record](https://www.data.nsw.gov.au/data/dataset/1-54c7b3b18680416a8b4496eceb6740fa)
describes the new service and migration from retiring GDA94 services. Its portal record says
“Creative Commons” in terms while the resource licence field is not versioned. The adapter therefore
records that ambiguity rather than claiming CC BY 4.0. The older Foundation Spatial Data Framework
[licensing statement](https://data.nsw.gov.au/data/dataset/ee5e06a2-255b-48e4-9f55-ec3c0e7bcec8/resource/010f8c31-770b-42bc-898d-a45897814002/download/nsw-foundation-spatial-data-framework-v3.pdf)
states CC BY 3.0 Australia and requires an extraction date, but it is not treated as proof that every
new GDA2020 portal resource carries that exact version.

### NSW government-school catchments

The registered artifact is the sole ZIP resource linked by the current
[Data.NSW school intake-zone dataset](https://data.nsw.gov.au/data/dataset/nsw-education-school-intake-zones-catchment-areas-for-nsw-government-schools):

`https://data.nsw.gov.au/data/dataset/8b1e8161-7252-43d9-81ed-6311569cb1d7/resource/32d6f502-ddb1-45d9-b114-5e34ddfd33ac/download/catchments.zip`

The validated response was 8,444,554 bytes with `Last-Modified: Sun, 06 Sep 2026 23:38:50 GMT` and
SHA-256 `3cc90b5cf7f6bf1819f9ff2fe77c52f45e9b600a8d07deaa72685d425d6b0627`. The archive contains
exactly the manifest and SHP/SHX/DBF/PRJ members for `catchments_primary`,
`catchments_secondary` and `catchments_future`. All three layers declare GDA94 / EPSG:4283 and are
transformed to EPSG:4326. The manifest says `current_enrolment_year: 2026`.

The exact DBF schema is `USE_ID`, `CATCH_TYPE`, `USE_DESC`, `ADD_DATE`, kindergarten through year 12,
and `PRIORITY`. Current layers use Y/N grade flags. Future layers use a year or zero for each grade;
those future years are retained as a mapping. `ADD_DATE` is a publisher addition date and is not used
as the zone's effective date. Canonical `valid_from` remains null because the archive supplies no
single explicit zone-effective date.

`USE_ID` is not row-unique: the real primary file contains two repeated school IDs and the future
file contains sixteen. Stable record identity combines layer, school ID and a digest of the
publisher's catchment type, priority and grade scope. This preserves every source row without making
geometry changes create a new identity. The publisher page labels the licence “Creative Commons
Attribution” without a version and warns that zones change and should not be relied on alone for a
property purchase or rental.

### NSW StrataHub scheme register

The exact service is:

`https://portal.spatial.nsw.gov.au/server/rest/services/StrataHub/FeatureServer/0`

It reported 88,926 polygon rows in EPSG:7844. The retained fields include publisher row ID `rid`,
`plannumber`, `planlabel`, registration date, address, suburb, LGA, postcode and lot total.
`plannumber` is not row-unique. A live check found two rows for SP69436: `rid` 55738 labels Elermore
Vale/Newcastle and `rid` 55739 labels Glendale/Lake Macquarie, while their registration date and shape
metrics match. The adapter therefore uses `rid` for record identity and preserves the plan number as
a scheme attribute. It does not discard one locality representation or infer that either is an error.

The layer represents registered scheme geometry and attributes. Absence from this layer is not
evidence that a property has no strata or community-title issue, and the source does not answer every
due-diligence question about a scheme.

### NSW amenities

The selected scope avoids the roughly 932,000-row unfiltered general-cultural-point layer. Each
selected class has a clear Feature 3 use. All current services report EPSG:7844 and are projected to
EPSG:4326.

| Service | Layers / fixed filter | Live counts |
| --- | --- | ---: |
| `NSW_FOI_Education_Facilities_multiCRS/FeatureServer` | 0 primary; 1 combined; 2 high; 3 preschool; 4 technical college; 5 university | 2,294; 332; 727; 165; 157; 68 |
| `NSW_FOI_Emergency_Service_Facilities_multiCRS/FeatureServer` | 0 Fire and Rescue NSW; 1 police; 2 Rural Fire Service; 3 SES | 352; 427; 2,287; 325 |
| `NSW_FOI_Health_Facilities_multiCRS/FeatureServer` | 0 ambulance; 1 hospital | 316; 306 |
| `NSW_FOI_Transport_Facilities_multiCRS/FeatureServer` | 0 airport; 1 train station; 2 bus station | 109; 582; 97 |
| `NSW_Features_of_Interest_Category_multiCRS/FeatureServer/3` | `classsubtype=2 AND buildingcomplextype=11` (libraries) | 423 |
| `NSW_Administrative_Boundaries_Theme_multiCRS/FeatureServer/6` | NPWS Reserve polygons | 899 |

Every path above is rooted at
`https://portal.spatial.nsw.gov.au/server/rest/services/`. Point layers use publisher `topoid` and
reserve polygons use `cadid`. Names, alternate labels, operational status and source dates are
retained when supplied. The library filter was validated against live records rather than inferred
from an unverified label.

The reserve layer covers NPWS protected estate. It does not establish complete council-managed urban
park coverage and is labelled `protected-reserve`, not a generic park layer. Complex reserve polygons
use 25-feature pages to keep responses under the adapter's 64 MiB page bound; point layers retain the
publisher's 1,000-feature page size.

Current Data.NSW spatial records describe these datasets as Creative Commons but do not consistently
state a licence version on the individual new GDA2020 resources. The extraction metadata retains this
status and the publisher copyright text instead of upgrading it to a more permissive version.

### ABS CPI

The adapter uses ABS dataflow `ABS:CPI(2.0.0)` with four exact keys under
`https://data.api.abs.gov.au/rest/data/ABS,CPI,2.0.0`:

* `1.10001.10.1.M` — Sydney monthly, 28 observations, 2024-04 through 2026-07;
* `1.10001.10.50.M` — Australia monthly, 28 observations, 2024-04 through 2026-07;
* `1.10001.10.1.Q` — Sydney quarterly, 312 observations, 1948-Q3 through 2026-Q2;
* `1.10001.10.50.Q` — Australia quarterly, 312 observations, 1948-Q3 through 2026-Q2.

Each request adds `?format=csvfilewithlabels`. The strict projection requires measure `1` (index
numbers), index `10001` (All groups CPI), adjustment `10` (original), unit `IN`, the requested region
and frequency, base-period code `25`, and label `Sep 2025 = 100.0`. The reference basis is part of
every record and discovery descriptor, so a future rebase fails validation rather than silently
changing historical meaning. Monthly and quarterly observations are separate source series; the
adapter does not derive one from the other or calculate inflation adjustments.

ABS states on its [website copyright page](https://www.abs.gov.au/website-privacy-copyright-and-disclaimer)
that website material is generally CC BY 4.0 International, subject to listed exceptions, and
requires ABS attribution.

## Capability and adoption status

The implementation provides strict discovery and complete streaming projection for all six profiles.
It validates exact HTTPS allowlists, source membership, schema, CRS, record counts, publisher IDs,
geometry coordinates, dates and source drift. It preserves raw source fields alongside canonical
names, geometry, validity and provenance.

Live validation established complete acquisition for ABS geography, gazetted suburbs, school
catchments and CPI, plus complete per-descriptor amenity scans. One amenity profile-wide attempt
correctly stopped when publisher metadata changed after discovery; a later per-descriptor run
completed all 9,866 records. The retained strata ingestion is the remaining large-run proof and must
finish at 88,926 records. None of these observations alone establishes an accepted warehouse release
or downstream Feature 3/4 activation.
