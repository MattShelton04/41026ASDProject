"""Official reference-source discovery and strict canonical record projection."""

from __future__ import annotations

import hashlib
import io
import json
import re
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from zipfile import BadZipFile, ZipFile

import httpx
import shapefile  # type: ignore[import-untyped]
from pyproj import Transformer

from .abs_cpi import discover_abs_cpi, iter_abs_cpi_records
from .arcgis import discover_arcgis_layer, iter_arcgis_features

_CATCHMENTS_URL = (
    "https://data.nsw.gov.au/data/dataset/8b1e8161-7252-43d9-81ed-6311569cb1d7/"
    "resource/32d6f502-ddb1-45d9-b114-5e34ddfd33ac/download/catchments.zip"
)
_MAX_CATCHMENTS_BYTES = 32 * 1024 * 1024
_CATCHMENT_STEMS = ("catchments_primary", "catchments_secondary", "catchments_future")
_CATCHMENT_MEMBERS = frozenset(
    {"catchment_sf_info.json"}
    | {f"{stem}.{suffix}" for stem in _CATCHMENT_STEMS for suffix in ("shp", "shx", "dbf", "prj")}
)
_CATCHMENT_FIELDS = (
    "USE_ID",
    "CATCH_TYPE",
    "USE_DESC",
    "ADD_DATE",
    "KINDERGART",
    "YEAR1",
    "YEAR2",
    "YEAR3",
    "YEAR4",
    "YEAR5",
    "YEAR6",
    "YEAR7",
    "YEAR8",
    "YEAR9",
    "YEAR10",
    "YEAR11",
    "YEAR12",
    "PRIORITY",
)
_GRADE_FIELDS = _CATCHMENT_FIELDS[4:17]
_GDA94_WKT_MARKER = 'AUTHORITY["EPSG",4283]'
_GDA94_TO_WGS84 = Transformer.from_crs("EPSG:4283", "EPSG:4326", always_xy=True)


@dataclass(frozen=True, slots=True)
class ArcSource:
    profile: str
    logical_key: str
    url: str
    layer: str
    edition: str
    id_field: str
    name_fields: tuple[str, ...]
    required_fields: tuple[str, ...]
    geometry_types: tuple[str, ...]
    where: str = "1=1"
    coverage_note: str | None = None
    non_spatial_ids: tuple[str, ...] = ()
    page_size: int | None = None


_ABS_GEOGRAPHY = (
    ArcSource(
        "abs-geography-2021",
        "abs-sal-2021-nsw",
        "https://geo.abs.gov.au/arcgis/rest/services/ASGS2021/SAL/MapServer/0",
        "abs-sal-2021",
        "ASGS Edition 3 - 2021 SAL boundaries",
        "sal_code_2021",
        ("sal_name_2021",),
        ("sal_code_2021", "sal_name_2021", "state_code_2021", "area_albers_sqkm"),
        ("Polygon", "MultiPolygon"),
        "state_code_2021='1'",
        non_spatial_ids=("19494", "19797"),
    ),
    ArcSource(
        "abs-geography-2021",
        "abs-lga-2021-nsw",
        "https://geo.abs.gov.au/arcgis/rest/services/ASGS2021/LGA/MapServer/0",
        "abs-lga-2021",
        "ASGS Edition 3 - 2021 LGA boundaries",
        "lga_code_2021",
        ("lga_name_2021",),
        ("lga_code_2021", "lga_name_2021", "state_code_2021", "area_albers_sqkm"),
        ("Polygon", "MultiPolygon"),
        "state_code_2021='1'",
        non_spatial_ids=("19499", "19799"),
    ),
)

_SUBURBS = (
    ArcSource(
        "nsw-suburb-boundaries",
        "nsw-gazetted-suburb",
        "https://portal.spatial.nsw.gov.au/server/rest/services/"
        "NSW_Administrative_Boundaries_Theme_multiCRS/FeatureServer/2",
        "nsw-gazetted-suburb",
        "Current NSW Administrative Boundaries GDA2020 service",
        "cadid",
        ("suburbname",),
        ("cadid", "suburbname", "state", "startdate", "enddate", "lastupdate"),
        ("Polygon", "MultiPolygon"),
    ),
)

_STRATA = (
    ArcSource(
        "nsw-strata-schemes",
        "nsw-strata-scheme",
        "https://portal.spatial.nsw.gov.au/server/rest/services/StrataHub/FeatureServer/0",
        "nsw-strata-scheme",
        "Current NSW StrataHub scheme register",
        "rid",
        ("planlabel", "address"),
        ("rid", "plannumber", "planlabel", "registrationdate"),
        ("Polygon", "MultiPolygon"),
    ),
)

_AMENITY_BASE = "https://portal.spatial.nsw.gov.au/server/rest/services"
_POINT_AMENITIES = tuple(
    ArcSource(
        "nsw-amenities",
        logical_key,
        f"{_AMENITY_BASE}/{service}/FeatureServer/{layer_id}",
        layer,
        "Current NSW Foundation Spatial Data GDA2020 service",
        "topoid",
        ("generalname", "alternativelabel"),
        ("topoid", "operationalstatus", "startdate", "enddate", "lastupdate"),
        ("Point",),
    )
    for logical_key, service, layer_id, layer in (
        ("amenity-primary-school", "NSW_FOI_Education_Facilities_multiCRS", 0, "primary-school"),
        (
            "amenity-combined-school",
            "NSW_FOI_Education_Facilities_multiCRS",
            1,
            "combined-school",
        ),
        ("amenity-high-school", "NSW_FOI_Education_Facilities_multiCRS", 2, "high-school"),
        ("amenity-preschool", "NSW_FOI_Education_Facilities_multiCRS", 3, "preschool"),
        (
            "amenity-technical-college",
            "NSW_FOI_Education_Facilities_multiCRS",
            4,
            "technical-college",
        ),
        ("amenity-university", "NSW_FOI_Education_Facilities_multiCRS", 5, "university"),
        (
            "amenity-fire-rescue",
            "NSW_FOI_Emergency_Service_Facilities_multiCRS",
            0,
            "fire-and-rescue-station",
        ),
        (
            "amenity-police",
            "NSW_FOI_Emergency_Service_Facilities_multiCRS",
            1,
            "police-station",
        ),
        (
            "amenity-rural-fire",
            "NSW_FOI_Emergency_Service_Facilities_multiCRS",
            2,
            "rural-fire-station",
        ),
        (
            "amenity-ses",
            "NSW_FOI_Emergency_Service_Facilities_multiCRS",
            3,
            "ses-headquarters",
        ),
        ("amenity-ambulance", "NSW_FOI_Health_Facilities_multiCRS", 0, "ambulance-station"),
        ("amenity-hospital", "NSW_FOI_Health_Facilities_multiCRS", 1, "hospital"),
        ("amenity-airport", "NSW_FOI_Transport_Facilities_multiCRS", 0, "airport"),
        ("amenity-train-station", "NSW_FOI_Transport_Facilities_multiCRS", 1, "train-station"),
        ("amenity-bus-station", "NSW_FOI_Transport_Facilities_multiCRS", 2, "bus-station"),
    )
)
_AMENITIES = (
    *_POINT_AMENITIES,
    ArcSource(
        "nsw-amenities",
        "amenity-library",
        f"{_AMENITY_BASE}/NSW_Features_of_Interest_Category_multiCRS/FeatureServer/3",
        "library",
        "Current NSW Foundation Spatial Data GDA2020 service",
        "topoid",
        ("generalname", "alternativelabel"),
        ("topoid", "buildingcomplextype", "operationalstatus", "lastupdate"),
        ("Point",),
        "classsubtype=2 AND buildingcomplextype=11",
    ),
    ArcSource(
        "nsw-amenities",
        "amenity-protected-reserve",
        f"{_AMENITY_BASE}/NSW_Administrative_Boundaries_Theme_multiCRS/FeatureServer/6",
        "protected-reserve",
        "Current NSW Administrative Boundaries GDA2020 service",
        "cadid",
        ("reservename", "reservecode"),
        ("cadid", "reservename", "reservetype", "startdate", "enddate", "lastupdate"),
        ("Polygon", "MultiPolygon"),
        coverage_note=(
            "NPWS reserves only; this does not establish complete council-managed "
            "urban park coverage"
        ),
        page_size=25,
    ),
)

_ARC_SOURCES = _ABS_GEOGRAPHY + _SUBURBS + _STRATA + _AMENITIES
_ARC_BY_PROFILE = {
    profile: tuple(item for item in _ARC_SOURCES if item.profile == profile)
    for profile in {item.profile for item in _ARC_SOURCES}
}
_ARC_BY_KEY = {item.logical_key: item for item in _ARC_SOURCES}
REFERENCE_PROFILES = frozenset((*_ARC_BY_PROFILE, "nsw-school-catchments", "abs-cpi"))


def discover_reference_sources(profile: str, client: httpx.Client) -> list[dict[str, Any]]:
    """Discover the complete fixed source set for one registered profile."""
    if profile == "abs-cpi":
        return discover_abs_cpi(client)
    if profile == "nsw-school-catchments":
        return [_discover_school_catchments(client)]
    try:
        specs = _ARC_BY_PROFILE[profile]
    except KeyError as exc:
        raise ValueError(f"unsupported reference source profile: {profile}") from exc
    discovered: list[dict[str, Any]] = []
    for spec in specs:
        descriptor = discover_arcgis_layer(client, spec.url, spec.logical_key, where=spec.where)
        if spec.page_size is not None:
            descriptor["page_size"] = min(int(descriptor["page_size"]), spec.page_size)
        descriptor.update(
            {
                "profile": profile,
                "layer": spec.layer,
                "edition": spec.edition,
                "publisher": _publisher(spec),
                "licence": _licence(spec),
                "coverage_note": spec.coverage_note,
            }
        )
        discovered.append(descriptor)
    return sorted(discovered, key=lambda item: str(item["logical_key"]))


def iter_reference_records(
    profile: str, client: httpx.Client, objects: list[dict[str, Any]]
) -> Iterator[dict[str, Any]]:
    """Project a complete discovered source set to the reference-feature contract."""
    if profile == "abs-cpi":
        yield from iter_abs_cpi_records(client, objects)
        return
    if profile == "nsw-school-catchments":
        if len(objects) != 1:
            raise ValueError("school catchments require one complete publisher archive")
        yield from _iter_school_catchments(client, objects[0])
        return
    try:
        specs = _ARC_BY_PROFILE[profile]
    except KeyError as exc:
        raise ValueError(f"unsupported reference source profile: {profile}") from exc
    expected_keys = sorted(item.logical_key for item in specs)
    if sorted(str(item.get("logical_key")) for item in objects) != expected_keys:
        raise ValueError(
            "reference acquisition does not contain the complete registered source set"
        )
    for descriptor in sorted(objects, key=lambda item: str(item["logical_key"])):
        spec = _ARC_BY_KEY[str(descriptor["logical_key"])]
        if (
            spec.profile != profile
            or descriptor.get("url") != spec.url
            or descriptor.get("where") != spec.where
            or descriptor.get("complete") is not True
        ):
            raise ValueError("reference descriptor is outside the registered source scope")
        seen: set[str] = set()
        for feature in iter_arcgis_features(client, descriptor):
            record = _project_arcgis_feature(spec, descriptor, feature)
            record_id = str(record["record_id"])
            if record_id in seen:
                raise ValueError(f"reference source duplicates stable ID {record_id}")
            seen.add(record_id)
            yield record


def _project_arcgis_feature(
    spec: ArcSource, descriptor: dict[str, Any], feature: dict[str, Any]
) -> dict[str, Any]:
    properties = feature.get("properties")
    geometry = feature.get("geometry")
    if not isinstance(properties, dict):
        raise ValueError("ArcGIS feature properties are missing")
    missing = [field for field in spec.required_fields if field not in properties]
    if missing:
        raise ValueError(f"{spec.logical_key} is missing registered fields: {missing}")
    stable_id = properties.get(spec.id_field)
    if isinstance(stable_id, bool) or not isinstance(stable_id, (str, int)):
        raise ValueError(f"{spec.logical_key} has no stable publisher identifier")
    stable_text = str(stable_id).strip()
    if not stable_text:
        raise ValueError(f"{spec.logical_key} has no stable publisher identifier")
    if geometry is None:
        if stable_text not in spec.non_spatial_ids:
            raise ValueError(f"{spec.logical_key} has a missing or unexpected geometry")
    elif not isinstance(geometry, dict) or geometry.get("type") not in spec.geometry_types:
        raise ValueError(f"{spec.logical_key} has a missing or unexpected geometry")
    else:
        _validate_geometry_coordinates(geometry.get("coordinates"))
    if spec.profile == "abs-geography-2021" and properties.get("state_code_2021") != "1":
        raise ValueError("ABS geography filter returned a non-NSW feature")
    if spec.profile == "nsw-suburb-boundaries" and properties.get("state") != 2:
        raise ValueError("NSW suburb source returned a non-NSW feature")
    name = next(
        (
            str(properties[field]).strip()
            for field in spec.name_fields
            if properties.get(field) is not None and str(properties[field]).strip()
        ),
        None,
    )
    attrs = dict(properties)
    attrs["source_layer"] = spec.layer
    attrs["publisher_edition"] = spec.edition
    if spec.coverage_note:
        attrs["coverage_note"] = spec.coverage_note
    updated = _first_esri_date(properties, "lastupdate", "modifieddate", "featuremoddate")
    valid_from = _first_esri_date(properties, "startdate", "registrationdate", date_only=True)
    valid_to = _first_esri_date(properties, "enddate", date_only=True, open_ended=True)
    return {
        "record_id": f"{spec.layer}:{stable_text}",
        "layer": spec.layer,
        "name": name,
        "geometry": geometry,
        "attributes": attrs,
        "source_url": spec.url,
        "source_crs": str(descriptor["source_crs"]),
        "source_updated_at": updated,
        "valid_from": valid_from,
        "valid_to": valid_to,
    }


def _discover_school_catchments(client: httpx.Client) -> dict[str, Any]:
    content, headers = _download_catchments(client)
    inventory = _catchment_inventory(content)
    return {
        "logical_key": "nsw-government-school-catchments",
        "url": _CATCHMENTS_URL,
        "media_type": "application/zip",
        "complete": True,
        "count": inventory["count"],
        "counts_by_layer": inventory["counts_by_layer"],
        "expected_bytes": len(content),
        "expected_sha256": hashlib.sha256(content).hexdigest(),
        "edition": f"NSW government school intake areas {inventory['current_enrolment_year']}",
        "current_enrolment_year": inventory["current_enrolment_year"],
        "source_crs": "EPSG:4283",
        "output_crs": "EPSG:4326",
        "schema": list(_CATCHMENT_FIELDS),
        "coverage": {
            "kind": "complete-publisher-archive",
            "layers": list(_CATCHMENT_STEMS),
            "scope": "NSW government schools only",
        },
        "source_updated_at": _http_date(headers.get("last-modified")),
        "publisher": "NSW Department of Education",
        "licence": "Creative Commons Attribution",
    }


def _iter_school_catchments(
    client: httpx.Client, descriptor: dict[str, Any]
) -> Iterator[dict[str, Any]]:
    if (
        descriptor.get("logical_key") != "nsw-government-school-catchments"
        or descriptor.get("url") != _CATCHMENTS_URL
        or descriptor.get("complete") is not True
    ):
        raise ValueError("school catchment descriptor is outside the registered source scope")
    content, _headers = _download_catchments(client)
    if hashlib.sha256(content).hexdigest() != descriptor.get("expected_sha256"):
        raise ValueError("school catchment source changed after discovery")
    inventory = _catchment_inventory(content)
    if inventory["count"] != descriptor.get("count"):
        raise ValueError("school catchment acquisition is incomplete")
    current_year = inventory["current_enrolment_year"]
    seen: set[str] = set()
    with ZipFile(io.BytesIO(content)) as archive:
        for stem in _CATCHMENT_STEMS:
            reader = _shapefile_reader(archive, stem)
            try:
                for shape_record in reader.iterShapeRecords():
                    properties = shape_record.record.as_dict()
                    school_code = _required_catchment_text(properties, "USE_ID")
                    future = stem.endswith("future")
                    grades = _catchment_grades(properties, future=future)
                    scope_key = _catchment_scope_key(properties, grades)
                    record_id = (
                        f"school-catchment:{stem.removeprefix('catchments_')}:"
                        f"{school_code}:{scope_key}"
                    )
                    if record_id in seen:
                        raise ValueError(f"school catchments duplicate stable ID {record_id}")
                    seen.add(record_id)
                    name = _required_catchment_text(properties, "USE_DESC")
                    geometry = _project_gda94_geometry(shape_record.shape.__geo_interface__)
                    attrs = dict(properties)
                    attrs.update(
                        {
                            "archive_layer": stem,
                            "current_enrolment_year": current_year,
                            "school_code": school_code,
                            "catchment_type": _required_catchment_text(properties, "CATCH_TYPE"),
                            "publisher_add_date": _catchment_add_date(properties.get("ADD_DATE")),
                            "grades": grades,
                        }
                    )
                    yield {
                        "record_id": record_id,
                        "layer": f"school-{stem.removeprefix('catchments_')}-catchment",
                        "name": name,
                        "geometry": geometry,
                        "attributes": attrs,
                        "source_url": _CATCHMENTS_URL,
                        "source_crs": "EPSG:4283",
                        "source_updated_at": descriptor.get("source_updated_at"),
                        # Future polygons carry grade-specific activation years. Keep
                        # those values in attributes rather than inventing one date.
                        "valid_from": None,
                        "valid_to": None,
                    }
            finally:
                reader.close()
    if len(seen) != descriptor["count"]:
        raise ValueError("school catchment acquisition is incomplete")


def _catchment_inventory(content: bytes) -> dict[str, Any]:
    try:
        archive = ZipFile(io.BytesIO(content))
    except BadZipFile as exc:
        raise ValueError("school catchment source is not a ZIP archive") from exc
    with archive:
        if set(archive.namelist()) != _CATCHMENT_MEMBERS:
            raise ValueError("school catchment ZIP members do not match the registered archive")
        try:
            manifest = json.loads(archive.read("catchment_sf_info.json"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ValueError("school catchment manifest is invalid") from exc
        current_year = (
            manifest.get("current_enrolment_year") if isinstance(manifest, dict) else None
        )
        if (
            not isinstance(current_year, int)
            or isinstance(current_year, bool)
            or current_year < 2020
        ):
            raise ValueError("school catchment manifest has no valid enrolment year")
        counts: dict[str, int] = {}
        for stem in _CATCHMENT_STEMS:
            projection = archive.read(f"{stem}.prj").decode("ascii")
            if _GDA94_WKT_MARKER not in projection.replace(" ", ""):
                raise ValueError("school catchment source CRS is not EPSG:4283")
            reader = _shapefile_reader(archive, stem)
            try:
                fields = tuple(field[0] for field in reader.fields[1:])
                if fields != _CATCHMENT_FIELDS:
                    raise ValueError(
                        "school catchment DBF schema does not match the registered layout"
                    )
                counts[stem] = int(reader.numRecords)
            finally:
                reader.close()
        if any(value <= 0 for value in counts.values()):
            raise ValueError("school catchment archive contains an empty layer")
        return {
            "count": sum(counts.values()),
            "counts_by_layer": counts,
            "current_enrolment_year": current_year,
        }


def _shapefile_reader(archive: ZipFile, stem: str) -> shapefile.Reader:
    return shapefile.Reader(
        shp=io.BytesIO(archive.read(f"{stem}.shp")),
        shx=io.BytesIO(archive.read(f"{stem}.shx")),
        dbf=io.BytesIO(archive.read(f"{stem}.dbf")),
        encoding="utf-8",
    )


def _download_catchments(client: httpx.Client) -> tuple[bytes, httpx.Headers]:
    with client.stream("GET", _CATCHMENTS_URL, timeout=120, follow_redirects=False) as response:
        response.raise_for_status()
        if response.headers.get("content-type", "").split(";", 1)[0] != "application/zip":
            raise ValueError("school catchment source is not published as a ZIP archive")
        content = bytearray()
        for chunk in response.iter_bytes():
            content.extend(chunk)
            if len(content) > _MAX_CATCHMENTS_BYTES:
                raise ValueError("school catchment archive exceeds the registered size bound")
    return bytes(content), response.headers


def _project_gda94_geometry(geometry: dict[str, Any]) -> dict[str, Any]:
    geometry_type = geometry.get("type")
    if geometry_type not in ("Polygon", "MultiPolygon"):
        raise ValueError("school catchment geometry is not a polygon")

    def transform(value: Any) -> Any:
        if (
            isinstance(value, (list, tuple))
            and len(value) >= 2
            and isinstance(value[0], (int, float))
            and isinstance(value[1], (int, float))
        ):
            x, y = _GDA94_TO_WGS84.transform(float(value[0]), float(value[1]))
            if not 140 <= x <= 160 or not -39 <= y <= -27:
                raise ValueError("school catchment coordinate falls outside NSW")
            return [x, y]
        if isinstance(value, (list, tuple)):
            return [transform(item) for item in value]
        raise ValueError("school catchment geometry has invalid coordinates")

    result = {"type": geometry_type, "coordinates": transform(geometry.get("coordinates"))}
    _validate_geometry_coordinates(result["coordinates"])
    return result


def _validate_geometry_coordinates(value: Any) -> None:
    if (
        isinstance(value, (list, tuple))
        and len(value) >= 2
        and isinstance(value[0], (int, float))
        and isinstance(value[1], (int, float))
    ):
        if not -180 <= float(value[0]) <= 180 or not -90 <= float(value[1]) <= 90:
            raise ValueError("reference geometry coordinate is outside EPSG:4326")
        return
    if not isinstance(value, (list, tuple)) or not value:
        raise ValueError("reference geometry coordinates are empty or malformed")
    for item in value:
        _validate_geometry_coordinates(item)


def _required_catchment_text(properties: dict[str, Any], field: str) -> str:
    value = properties.get(field)
    text = str(value).strip() if value is not None else ""
    if not text:
        raise ValueError(f"school catchment {field} is required")
    return text


def _catchment_add_date(value: Any) -> str | None:
    text = str(value).strip() if value is not None else ""
    if not text:
        return None
    if not re.fullmatch(r"\d{8}", text):
        raise ValueError("school catchment ADD_DATE is invalid")
    try:
        return datetime.strptime(text, "%Y%m%d").date().isoformat()
    except ValueError as exc:
        raise ValueError("school catchment ADD_DATE is invalid") from exc


def _catchment_grades(properties: dict[str, Any], *, future: bool) -> dict[str, bool | int]:
    grades: dict[str, bool | int] = {}
    for field in _GRADE_FIELDS:
        value = properties.get(field)
        if future:
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"future school catchment {field} year is invalid")
            grades[field] = value
        else:
            if value not in ("Y", "N"):
                raise ValueError(f"school catchment {field} flag is invalid")
            grades[field] = value == "Y"
    return grades


def _catchment_scope_key(properties: dict[str, Any], grades: dict[str, bool | int]) -> str:
    """Distinguish grade/priority zones for schools with more than one polygon row."""
    semantic_scope = {
        "catchment_type": _required_catchment_text(properties, "CATCH_TYPE"),
        "priority": str(properties.get("PRIORITY") or "").strip(),
        "grades": grades,
    }
    encoded = json.dumps(semantic_scope, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()[:16]


def _first_esri_date(
    properties: dict[str, Any],
    *fields: str,
    date_only: bool = False,
    open_ended: bool = False,
) -> str | None:
    for field in fields:
        value = properties.get(field)
        if value is None:
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"ArcGIS {field} is not an epoch-millisecond date")
        parsed = datetime.fromtimestamp(value / 1000, tz=UTC)
        if open_ended and parsed.year == 3000:
            return None
        return parsed.date().isoformat() if date_only else parsed.isoformat().replace("+00:00", "Z")
    return None


def _http_date(value: str | None) -> str | None:
    if value is None:
        return None
    try:
        return (
            datetime.strptime(value, "%a, %d %b %Y %H:%M:%S %Z")
            .replace(tzinfo=UTC)
            .isoformat()
            .replace("+00:00", "Z")
        )
    except ValueError as exc:
        raise ValueError("school catchment Last-Modified header is invalid") from exc


def _publisher(spec: ArcSource) -> str:
    return (
        "Australian Bureau of Statistics"
        if spec.profile == "abs-geography-2021"
        else "NSW Spatial Services"
    )


def _licence(spec: ArcSource) -> str:
    return (
        "Creative Commons Attribution 4.0 International"
        if spec.profile == "abs-geography-2021"
        else "Creative Commons (version not specified in current Data.NSW metadata)"
    )
