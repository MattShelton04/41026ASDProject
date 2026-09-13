"""Closed Feature 1 reference-source capabilities, independent of local releases."""

from __future__ import annotations

REFERENCE_PROFILES = frozenset(
    {
        "nsw-cadastre",
        "nsw-planning-controls",
        "nsw-bushfire-prone-land",
        "nsw-flood-planning",
        "abs-geography-2021",
        "nsw-suburb-boundaries",
        "nsw-school-catchments",
        "nsw-strata-schemes",
        "nsw-amenities",
        "abs-cpi",
    }
)
SPATIAL_PROFILES = frozenset(
    {"nsw-cadastre", "nsw-planning-controls", "nsw-bushfire-prone-land", "nsw-flood-planning"}
)
REFERENCE_LIMITATIONS = (
    "Source features retain their declared layer, edition, coverage and publisher attributes.",
    "A source feature is not a verified property match or a determination of legal applicability.",
    "Absent or invalid geometry cannot establish absence of a planning or environmental issue.",
    "Feature 1 supplies reference facts; downstream interpretation and integration are separate.",
)

_SOURCE_LIMITATIONS: dict[str, tuple[str, ...]] = {
    "nsw-cadastre": (
        "Cadastral lots are distinct from addresses, sales, titles and ownership records.",
    ),
    "nsw-planning-controls": (
        "Published zoning, height, floor-space ratio, minimum lot size and heritage layers "
        "require the relevant instrument and effective dates to determine applicability.",
    ),
    "nsw-bushfire-prone-land": (
        "Bushfire-prone land designation is planning evidence, not a predicted fire event "
        "or a property-specific risk assessment.",
    ),
    "nsw-flood-planning": (
        "This is the published EPI flood-planning-control layer, "
        "not complete NSW inundation mapping.",
        "Council flood mapping responsibility changed in 2021; published coverage may be stale. "
        "AEP, scenario and study extent are unknown unless explicitly provided.",
    ),
    "abs-geography-2021": (
        "ASGS Edition 3 SAL and LGA boundaries retain their 2021 codes and edition; "
        "they are not current gazetted suburbs or a crosswalk between changing boundaries.",
    ),
    "nsw-suburb-boundaries": (
        "Current gazetted suburb boundaries are distinct from ABS statistical localities.",
    ),
    "nsw-school-catchments": (
        "Primary, secondary and future catchments retain grade and priority fields. "
        "An added date does not establish a future catchment's commencement date or eligibility.",
    ),
    "nsw-strata-schemes": (
        "Scheme boundaries and register facts do not establish an individual unit, "
        "ownership, levies, defects or financial health.",
    ),
    "nsw-amenities": (
        "Registered official facility classes are not an exhaustive business or amenity inventory.",
        "NPWS reserves represent protected estates, not all urban or council parks. "
        "Location alone does not establish current public access or service availability.",
    ),
    "abs-cpi": (
        "All groups, original CPI for Sydney and Australia retains monthly/quarterly series "
        "and its published reference base; it is not a local property price index.",
    ),
}


def reference_limitations(profile: str) -> tuple[str, ...]:
    return REFERENCE_LIMITATIONS + _SOURCE_LIMITATIONS.get(profile, ())
