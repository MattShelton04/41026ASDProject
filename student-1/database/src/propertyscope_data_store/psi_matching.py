"""Versioned exact-address equivalences; never fuzzy or property-ID propagation.

Road types: NSW SIX Address Location service, Appendix Road Name Types,
https://maps.six.nsw.gov.au/sws/AddressLocation.html (checked 2026-09-13).
Existing PSI abbreviations AV/CR are retained for replay compatibility.
"""

from __future__ import annotations

MATCHING_VERSION = "psi-exact-address.v2"

# Explicit, reviewed pairs. Do not infer equivalence from spelling similarity.
STREET_TYPES = {
    "AVENUE": "AV",
    "CLOSE": "CL",
    "COURT": "CT",
    "CRESCENT": "CR",
    "DRIVE": "DR",
    "HIGHWAY": "HWY",
    "PARADE": "PDE",
    "PLACE": "PL",
    "ROAD": "RD",
    "STREET": "ST",
    "TERRACE": "TCE",
    "LANE": "LANE",
    "CIRCUIT": "CCT",
    "WAY": "WAY",
    "BOULEVARD": "BVD",
    "GROVE": "GR",
    "PARKWAY": "PKWY",
    "ESPLANADE": "ESP",
    "CIRCLE": "CIR",
    "WALK": "WALK",
    "GLADE": "GLD",
    "LOOP": "LOOP",
    "RISE": "RISE",
    "GARDENS": "GDNS",
    "ROW": "ROW",
    "GLEN": "GLEN",
    "RIDGE": "RDGE",
    "SQUARE": "SQ",
    "CHASE": "CH",
    "MEWS": "MEWS",
    "MALL": "MALL",
    "LINK": "LINK",
    "ALLEY": "ALLY",
    "ARCADE": "ARC",
    "BYPASS": "BYPA",
    "CORNER": "CNR",
    "GREEN": "GRN",
    "JUNCTION": "JNC",
    "HEIGHTS": "HTS",
    "VIEW": "VIEW",
    "COVE": "COVE",
    "CREST": "CRST",
    "RETREAT": "RTT",
    "PROMENADE": "PROM",
    "TRACK": "TRK",
    "TRAIL": "TRL",
    "VALE": "VALE",
    "GARDEN": "GDN",
}

# SQL literals are generated solely from this checked-in ASCII catalogue.
STREET_TYPE_VALUES_SQL = ",\n".join(f"('{name}','{code}')" for name, code in STREET_TYPES.items())
STREET_TYPE_CASE_SQL = "\n".join(
    f"WHEN '{name}' THEN '{code}'" for name, code in STREET_TYPES.items()
)

# Spaces may surround a suffix/hyphen, but cannot split digits ('1 2' != '12').
# Last-number suffixes, LOT text, slash units and multiple ranges remain unresolved.
HOUSE_NUMBER_SQL_PATTERN = "^[0-9]+ *[A-Z]?( *- *[0-9]+)?$"

PSI_LINKAGE_COUNTS_SQL = """
    SELECT count(*) FILTER (WHERE candidate.property_ref IS NOT NULL) AS count,
        count(*) FILTER (WHERE previous.property_ref IS NOT NULL) AS previously_linked,
        count(*) FILTER (WHERE previous.property_ref IS NOT NULL
            AND candidate.property_ref IS NULL) AS lost_links,
        count(*) FILTER (WHERE previous.property_ref IS NOT NULL
            AND candidate.property_ref IS NOT NULL
            AND candidate.property_ref<>previous.property_ref) AS changed_links
    FROM warehouse.psi_sale candidate
    LEFT JOIN warehouse.psi_sale previous
      ON previous.dataset_release_id=(SELECT dataset_release_id
          FROM serving.accepted_generation WHERE dataset_id='nsw-psi-sales')
     AND previous.source_business_key=candidate.source_business_key
     AND previous.source_revision=candidate.source_revision
     AND previous.source_row_sha256=candidate.source_row_sha256
    WHERE candidate.dataset_release_id=%s
"""
