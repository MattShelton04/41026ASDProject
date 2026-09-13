"""Presentation metadata for Feature 1's registered datasets.

The keys in this module are existing source, adapter, and job-profile identifiers.  They
remain machine-facing contract values; the labels and purposes are for catalogue UI only.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class CatalogueGroup:
    key: str
    label: str
    description: str


@dataclass(frozen=True)
class DatasetPresentation:
    source_key: str
    adapter_key: str
    job_profile: str
    group_key: str
    display_name: str
    purpose: str
    default_names: tuple[str, ...]


CATALOGUE_GROUPS = (
    CatalogueGroup(
        "foundational-property",
        "Foundational property data",
        "Core address identity, location and sale-history records used in property operations.",
    ),
    CatalogueGroup(
        "geography-boundaries",
        "Geography and boundaries",
        "Parcel, statistical, suburb and strata boundaries used to locate property evidence.",
    ),
    CatalogueGroup(
        "planning-hazards",
        "Planning and hazards",
        "Published planning controls and mapped hazard constraints for site research.",
    ),
    CatalogueGroup(
        "community-amenities",
        "Community and amenities",
        "Schools, catchments, facilities, recorded crime and area-level social context.",
    ),
    CatalogueGroup(
        "economic-context",
        "Economic context",
        "Official economic series used to place property evidence in broader context.",
    ),
    CatalogueGroup(
        "development-fixtures",
        "Development fixtures",
        "Synthetic records used for deterministic development and demonstration workflows.",
    ),
)


DATASET_PRESENTATIONS = (
    DatasetPresentation(
        "gnaf-nsw",
        "gnaf-bulk",
        "gnaf-nsw-address-registry",
        "foundational-property",
        "G-NAF addresses",
        "Foundational address identity and location for NSW properties.",
        (
            "G-NAF Open NSW",
            "G-NAF NSW address registry",
            "G-NAF NSW address registry snapshot",
        ),
    ),
    DatasetPresentation(
        "nsw-psi-sales",
        "psi-bulk",
        "nsw-psi-sales-year",
        "foundational-property",
        "NSW property sale history (PSI)",
        "Official NSW property sale history from the Valuer General.",
        (
            "NSW Valuer General property sales information",
            "NSW Valuer General PSI complete property sales",
            "NSW property sales yearly backfill",
            "NSW PSI sales history update",
        ),
    ),
    DatasetPresentation(
        "nsw-cadastre",
        "nsw-cadastre-source",
        "nsw-cadastre",
        "geography-boundaries",
        "NSW cadastral lots",
        "Parcel boundaries and lot references from NSW Spatial Services.",
        ("NSW cadastral lots",),
    ),
    DatasetPresentation(
        "abs-geography-2021",
        "abs-geography-2021-source",
        "abs-geography-2021",
        "geography-boundaries",
        "ABS 2021 statistical boundaries",
        "Suburbs and Localities (SAL) and Local Government Area boundaries for area matching.",
        ("ABS 2021 NSW statistical locality and LGA boundaries",),
    ),
    DatasetPresentation(
        "nsw-suburb-boundaries",
        "nsw-suburb-boundaries-source",
        "nsw-suburb-boundaries",
        "geography-boundaries",
        "NSW gazetted suburb boundaries",
        "Official gazetted suburb and locality boundaries for NSW.",
        ("NSW gazetted suburb boundaries",),
    ),
    DatasetPresentation(
        "nsw-strata-schemes",
        "nsw-strata-schemes-source",
        "nsw-strata-schemes",
        "geography-boundaries",
        "NSW strata schemes",
        "Strata scheme boundaries and published register facts.",
        ("NSW strata scheme boundaries and register facts",),
    ),
    DatasetPresentation(
        "nsw-planning-controls",
        "nsw-planning-controls-source",
        "nsw-planning-controls",
        "planning-hazards",
        "NSW planning controls",
        "Published zoning, height, floor-space, heritage and minimum-lot-size controls.",
        ("NSW EPI planning controls",),
    ),
    DatasetPresentation(
        "nsw-bushfire-prone-land",
        "nsw-bushfire-prone-land-source",
        "nsw-bushfire-prone-land",
        "planning-hazards",
        "Bush fire prone land (BFPL)",
        "Published NSW bush fire prone land mapping for site research.",
        ("NSW bushfire prone land",),
    ),
    DatasetPresentation(
        "nsw-flood-planning",
        "nsw-flood-planning-source",
        "nsw-flood-planning",
        "planning-hazards",
        "NSW flood planning controls",
        "Published flood-planning controls from the NSW planning map service.",
        ("NSW published flood planning controls",),
    ),
    DatasetPresentation(
        "nsw-government-schools",
        "schools-csv",
        "nsw-government-schools-master",
        "community-amenities",
        "NSW government schools",
        "Government school locations and published school attributes.",
        (
            "NSW government school locations and attributes",
            "NSW government schools master snapshot",
        ),
    ),
    DatasetPresentation(
        "nsw-school-catchments",
        "nsw-school-catchments-source",
        "nsw-school-catchments",
        "community-amenities",
        "NSW government school catchments",
        "Published intake zones for NSW government schools.",
        ("NSW government school catchments",),
    ),
    DatasetPresentation(
        "nsw-amenities",
        "nsw-amenities-source",
        "nsw-amenities",
        "community-amenities",
        "NSW official amenities",
        "Selected official facility and amenity locations for local-area research.",
        ("NSW official amenity and facility locations",),
    ),
    DatasetPresentation(
        "bocsar-crime",
        "bocsar-bulk",
        "bocsar-crime-quarterly",
        "community-amenities",
        "Recorded crime by area (BOCSAR)",
        "Recorded crime series and their published geographic coverage.",
        (
            "BOCSAR recorded crime data",
            "BOCSAR crime quarterly release",
            "BOCSAR crime quarterly snapshot",
        ),
    ),
    DatasetPresentation(
        "abs-seifa-2021",
        "abs-seifa-xlsx",
        "abs-seifa-2021-sal-nsw",
        "community-amenities",
        "Socio-economic area context (SEIFA 2021)",
        "Area-level socio-economic indexes for ABS 2021 Suburbs and Localities.",
        (
            "ABS SEIFA 2021 NSW Suburbs and Localities",
            "ABS SEIFA 2021 NSW suburb and locality indexes",
        ),
    ),
    DatasetPresentation(
        "abs-cpi",
        "abs-cpi-source",
        "abs-cpi",
        "economic-context",
        "Inflation context (ABS CPI)",
        "All-groups consumer price indexes for Sydney and Australia.",
        ("ABS All groups CPI Sydney and Australia",),
    ),
    DatasetPresentation(
        "fixture-property",
        "fixture-snapshot",
        "fixture-property-full",
        "development-fixtures",
        "Example property records",
        "Synthetic NSW property records for deterministic development and demonstrations.",
        (
            "Example NSW property records",
            "Example property records update",
            "Property identity register",
            "Deterministic property critical-path fixture",
            "Deterministic synthetic property snapshot",
        ),
    ),
)

_BY_SOURCE_KEY = {item.source_key: item for item in DATASET_PRESENTATIONS}
_BY_ADAPTER_KEY = {item.adapter_key: item for item in DATASET_PRESENTATIONS}


def source_presentation(source: Mapping[str, Any]) -> DatasetPresentation | None:
    """Resolve presentation metadata without depending on a mutable display name."""
    adapter_key = source.get("adapter_key")
    return _BY_ADAPTER_KEY.get(str(adapter_key)) if adapter_key else None


def presented_name(item: DatasetPresentation | None, saved_name: object) -> str:
    """Improve registered defaults while preserving a user-customized saved name."""
    name = str(saved_name or "").strip()
    if item is not None and (not name or name == item.display_name or name in item.default_names):
        return item.display_name
    return name or "Unnamed dataset"


def group_sources(items: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """Group source rows in the declared UI order, retaining unknown user sources."""
    grouped: dict[str, list[dict[str, Any]]] = {group.key: [] for group in CATALOGUE_GROUPS}
    other: list[dict[str, Any]] = []
    for source in items:
        presentation = source_presentation(source)
        source["presentation_name"] = presented_name(presentation, source.get("name"))
        source["presentation_purpose"] = presentation.purpose if presentation else ""
        source["presentation_group"] = presentation.group_key if presentation else "other-sources"
        (grouped[presentation.group_key] if presentation else other).append(source)
    groups = [
        {
            "key": group.key,
            "label": group.label,
            "description": group.description,
            "items": grouped[group.key],
        }
        for group in CATALOGUE_GROUPS
        if grouped[group.key]
    ]
    if other:
        groups.append(
            {
                "key": "other-sources",
                "label": "Other sources",
                "description": "Additional source definitions managed in this environment.",
                "items": other,
            }
        )
    return groups


def catalogue_presentation_payload() -> dict[str, Any]:
    """Return bounded UI metadata; readiness remains on releases and runtime evidence."""
    return {
        "schema_version": "propertyscope.catalogue-presentation.v1",
        "groups": [group.__dict__ for group in CATALOGUE_GROUPS],
        "datasets": [item.__dict__ for item in DATASET_PRESENTATIONS],
    }
