"""Bounded official ArcGIS reads with keyset pagination and completeness checks."""

from __future__ import annotations

import hashlib
import json
import math
import re
import time
from collections.abc import Iterator
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

import httpx
import shapefile  # type: ignore[import-untyped]
from pyproj import Transformer

_HOSTS = frozenset(
    {"portal.spatial.nsw.gov.au", "portal.data.nsw.gov.au", "geo.abs.gov.au"}
    | {f"mapprod{suffix}.environment.nsw.gov.au" for suffix in ("", "1", "2", "3")}
)
_MAX_RESPONSE_BYTES = 64 * 1024 * 1024
_HOSTED_BFPL = (
    "https://portal.spatial.nsw.gov.au/server/rest/services/Hosted/"
    "NSW_BushFire_Prone_Land/FeatureServer/0"
)


class _ArcGISPageCapacityError(ValueError):
    """A bounded page cannot be delivered at its requested transport size."""


class _ArcGISResponse(dict[str, Any]):
    def __init__(self, payload: dict[str, Any], response_bytes: int) -> None:
        super().__init__(payload)
        self.response_bytes = response_bytes


class _FeaturePage(list[dict[str, Any]]):
    def __init__(self, features: list[dict[str, Any]], response_bytes: int) -> None:
        super().__init__(features)
        self.response_bytes = response_bytes


@dataclass
class _PageWindow:
    ceiling: int
    size: int
    small_pages: int = 0
    failed_growth_probes: int = 0
    probing: bool = False

    def completed(self, page: list[dict[str, Any]], effective_size: int) -> None:
        if self.probing:
            if effective_size < self.size:
                self.failed_growth_probes += 1
            else:
                self.failed_growth_probes = 0
        if effective_size < self.size:
            self.small_pages = 0
        self.size = effective_size
        self.probing = False
        if (
            self.size < self.ceiling
            and len(page) == self.size
            and getattr(page, "response_bytes", _MAX_RESPONSE_BYTES) <= _MAX_RESPONSE_BYTES // 16
        ):
            self.small_pages += 1
        else:
            self.small_pages = 0
        # A large polygon must not force one-record requests forever. Grow only
        # after eight full pages with ample byte headroom. Three failed probes
        # trigger a 64-small-page cooldown before one further attempt.
        successes_required = 64 if self.failed_growth_probes >= 3 else 8
        if self.small_pages >= successes_required:
            self.size = min(self.ceiling, self.size * 2)
            self.small_pages = 0
            self.probing = True


def _is_html_page(content: bytes | bytearray) -> bool:
    prefix = bytes(content[:1024]).lstrip(b"\xef\xbb\xbf \t\r\n")
    return re.match(rb"(?:<!doctype\s+html\b|<html\b)", prefix, re.IGNORECASE) is not None


def _validate_url(url: str) -> None:
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.hostname not in _HOSTS
        or parsed.username
        or parsed.password
        or parsed.port not in (None, 443)
        or parsed.query
        or parsed.fragment
        or not re.fullmatch(r"/[A-Za-z0-9_/-]+/(?:MapServer|FeatureServer)/\d+", parsed.path)
    ):
        raise ValueError("ArcGIS layer URL is outside the official source allowlist")


def _read_json(client: httpx.Client, url: str, params: dict[str, str]) -> dict[str, Any]:
    for attempt in range(3):
        try:
            with client.stream(
                "GET", url, params=params, timeout=120, follow_redirects=False
            ) as response:
                if (
                    attempt == 2
                    and response.status_code == 500
                    and url.endswith("/query")
                    and params.get("returnGeometry") == "true"
                    and "resultRecordCount" in params
                ):
                    # BFPL returns this ArcGIS HTML error for complex large pages.
                    # Inspect only a bounded prefix after the ordinary HTTP retries;
                    # unrelated server errors keep their original failure behavior.
                    error_prefix = bytearray()
                    for chunk in response.iter_bytes(chunk_size=8192):
                        error_prefix.extend(chunk[: 8192 - len(error_prefix)])
                        if len(error_prefix) == 8192:
                            break
                    if (
                        _is_html_page(error_prefix)
                        and b"error performing query operation" in error_prefix.lower()
                    ):
                        raise _ArcGISPageCapacityError(
                            "ArcGIS HTML query operation failed after three HTTP 500 attempts"
                        )
                response.raise_for_status()
                content = bytearray()
                for chunk in response.iter_bytes():
                    content.extend(chunk)
                    if len(content) > _MAX_RESPONSE_BYTES:
                        raise _ArcGISPageCapacityError(
                            "ArcGIS response exceeds the bounded page size"
                        )
            try:
                result = json.loads(content)
            except json.JSONDecodeError as exc:
                if _is_html_page(content):
                    raise _ArcGISPageCapacityError(
                        "ArcGIS returned an HTML page instead of source JSON"
                    ) from exc
                raise
            if not isinstance(result, dict) or "error" in result:
                raise ValueError("ArcGIS publisher returned an invalid or error response")
            return _ArcGISResponse(result, len(content))
        except (httpx.TransportError, httpx.HTTPStatusError) as exc:
            retryable = not isinstance(exc, httpx.HTTPStatusError) or (
                exc.response.status_code == 429 or exc.response.status_code >= 500
            )
            if not retryable or attempt == 2:
                raise
            time.sleep(0.25 * (2**attempt))
    raise AssertionError("unreachable")


def _count(client: httpx.Client, url: str, where: str = "1=1") -> int:
    result = _read_json(
        client, url + "/query", {"f": "json", "where": where, "returnCountOnly": "true"}
    )
    value = result.get("count")
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError("ArcGIS count is missing or invalid")
    return value


def discover_arcgis_layer(
    client: httpx.Client,
    url: str,
    logical_key: str,
    *,
    where: str = "1=1",
    workers: int = 1,
    standard_page_size: int | None = None,
) -> dict[str, Any]:
    """Discover one entire publisher layer; never infer completeness from a sample."""
    _validate_url(url)
    if not 1 <= workers <= 4:
        raise ValueError("ArcGIS acquisition supports one to four workers")
    if standard_page_size is not None and not 1 <= standard_page_size <= 2000:
        raise ValueError("ArcGIS standard page size must be between one and 2000")
    metadata = _read_json(client, url, {"f": "json"})
    fields = metadata.get("fields", [])
    oids = [field["name"] for field in fields if field.get("type") == "esriFieldTypeOID"]
    capabilities = metadata.get("advancedQueryCapabilities", {})
    if len(oids) != 1 or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", oids[0]):
        raise ValueError("ArcGIS requires one valid object identifier field")
    if not capabilities.get("supportsOrderBy"):
        raise ValueError("ArcGIS layer does not support deterministic ordering")
    extent = metadata.get("extent", {})
    sr = extent.get("spatialReference", {})
    crs = sr.get("latestWkid", sr.get("wkid"))
    if not isinstance(crs, int):
        raise ValueError("ArcGIS source CRS is missing")
    page_size = metadata.get("maxRecordCount")
    if not isinstance(page_size, int) or page_size <= 0:
        raise ValueError("ArcGIS page limit is missing")
    query_result_type = None
    application_limit = 1000
    if standard_page_size is not None and capabilities.get("supportsQueryWithResultType"):
        page_size = metadata.get("standardMaxRecordCount")
        if not isinstance(page_size, int) or isinstance(page_size, bool) or page_size <= 0:
            raise ValueError("ArcGIS standard query page limit is missing")
        query_result_type = "standard"
        application_limit = standard_page_size
    fingerprint = hashlib.sha256(json.dumps(metadata, sort_keys=True).encode()).hexdigest()
    descriptor = {
        "logical_key": logical_key,
        "url": url,
        "media_type": "application/geo+json",
        "complete": True,
        "count": _count(client, url, where),
        "where": where,
        "workers": workers,
        "oid_field": oids[0],
        "page_size": min(page_size, application_limit),
        "publisher_page_limit": page_size,
        "query_result_type": query_result_type,
        # This publisher advertises GeoJSON but returns HTTP 503 for it (verified
        # 2026-09-13). Request projected Esri JSON and convert polygon topology.
        "query_format": "json"
        if urlsplit(url).hostname == "portal.spatial.nsw.gov.au"
        else "geojson",
        "source_crs": f"EPSG:{crs}",
        "output_crs": "EPSG:4326",
        "schema": fields,
        "coverage": {
            "kind": "complete-publisher-layer" if where == "1=1" else "complete-publisher-filter",
            "where": where,
            "extent": extent,
        },
        "edition": metadata.get("editingInfo") or None,
        "metadata_sha256": fingerprint,
        "copyright": metadata.get("copyrightText") or None,
        "description": metadata.get("description") or None,
    }
    if workers > 1 and descriptor["count"]:
        statistics = [
            {"statisticType": kind, "onStatisticField": oids[0], "outStatisticFieldName": name}
            for kind, name in (("min", "min_oid"), ("max", "max_oid"))
        ]
        bounds = _read_json(
            client,
            url + "/query",
            {
                "f": "json",
                "where": where,
                "outStatistics": json.dumps(statistics),
                "returnGeometry": "false",
            },
        )
        attributes = bounds.get("features", [{}])[0].get("attributes", {})
        lower, upper = attributes.get("min_oid"), attributes.get("max_oid")
        if not isinstance(lower, int) or not isinstance(upper, int) or lower > upper:
            raise ValueError("ArcGIS did not provide integer object identifier bounds")
        descriptor["oid_bounds"] = [lower, upper]
    return descriptor


def iter_arcgis_features(
    client: httpx.Client, descriptor: dict[str, Any]
) -> Iterator[dict[str, Any]]:
    """Stream deterministically ordered pages, then reconcile source count/metadata.

    Page sizes are transport bounds, not record limits. A partial page is never a
    completion signal. Publication must wait until this iterator finishes.
    """
    url = str(descriptor["url"])
    _validate_url(url)
    oid = str(descriptor["oid_field"])
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", oid):
        raise ValueError("Invalid ArcGIS object identifier")
    expected = int(descriptor["count"])
    result_type = descriptor.get("query_result_type")
    if result_type not in (None, "standard"):
        raise ValueError("Unsupported ArcGIS query result type")
    publisher_limit = int(descriptor.get("publisher_page_limit", 1000))
    size = min(int(descriptor["page_size"]), publisher_limit, 2000 if result_type else 1000)
    if expected < 0 or size < 1:
        raise ValueError("Invalid ArcGIS discovery bounds")
    received = 0
    for features in _ordered_pages(client, descriptor, oid, size):
        for feature in features:
            received += 1
            if received > expected:
                raise ValueError("ArcGIS source changed after discovery")
            yield feature
        del features
    if received != expected or _count(client, url, str(descriptor.get("where", "1=1"))) != expected:
        raise ValueError("ArcGIS acquisition is incomplete or source count changed")
    metadata = _read_json(client, url, {"f": "json"})
    fingerprint = hashlib.sha256(json.dumps(metadata, sort_keys=True).encode()).hexdigest()
    if fingerprint != descriptor["metadata_sha256"]:
        raise ValueError("ArcGIS metadata changed during acquisition")


def _fetch_page(
    client: httpx.Client,
    descriptor: dict[str, Any],
    oid: str,
    size: int,
    previous: int | None,
    upper: int | None,
) -> list[dict[str, Any]]:
    where = str(descriptor.get("where", "1=1"))
    if previous is not None:
        where = f"({where}) AND {oid}>{previous}"
    if upper is not None:
        where = f"({where}) AND {oid}<={upper}"
    page = _read_json(
        client,
        str(descriptor["url"]) + "/query",
        {
            "f": str(descriptor.get("query_format", "geojson")),
            "where": where,
            "outFields": "*",
            "returnGeometry": "true",
            "outSR": "4326",
            "orderByFields": f"{oid} ASC",
            "resultRecordCount": str(size),
            **({"resultType": "standard"} if descriptor.get("query_result_type") else {}),
        },
    )
    response_bytes = getattr(page, "response_bytes", _MAX_RESPONSE_BYTES)
    if descriptor.get("query_format") == "json":
        response_bytes += _recover_projected_empty(client, descriptor, oid, page)
        page = _esri_page(page)
    features = page.get("features")
    if page.get("type") != "FeatureCollection" or not isinstance(features, list):
        raise ValueError("ArcGIS did not return a GeoJSON feature collection")
    crs = page.get("crs")
    if crs and crs.get("properties", {}).get("name") not in (
        "urn:ogc:def:crs:OGC:1.3:CRS84",
        "urn:ogc:def:crs:EPSG::4326",
        "EPSG:4326",
    ):
        raise ValueError("ArcGIS did not honour the requested output CRS")
    if not features:
        if page.get("exceededTransferLimit"):
            raise ValueError("ArcGIS returned an empty truncated page")
        return []
    if len(features) > size:
        raise ValueError("ArcGIS exceeded the requested page bound")
    for feature in features:
        properties = feature.get("properties")
        value = properties.get(oid) if isinstance(properties, dict) else None
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError("ArcGIS feature is missing its integer object identifier")
        if previous is not None and value <= previous:
            raise ValueError("ArcGIS pagination repeated or reordered an object identifier")
        if upper is not None and value > upper:
            raise ValueError("ArcGIS feature escaped its requested object identifier range")
        previous = value
    return _FeaturePage(features, response_bytes)


def _ordered_pages(
    client: httpx.Client,
    descriptor: dict[str, Any],
    oid: str,
    size: int,
) -> Iterator[list[dict[str, Any]]]:
    workers = int(descriptor.get("workers", 1))
    if not 1 <= workers <= 4:
        raise ValueError("ArcGIS acquisition supports one to four workers")
    bounds = descriptor.get("oid_bounds")
    if workers == 1 or not descriptor["count"]:
        previous = None
        window = _PageWindow(size, size)
        while True:
            page, effective_size = _fetch_adaptive_page(
                client, descriptor, oid, window.size, previous, None
            )
            if not page:
                break
            window.completed(page, effective_size)
            previous = page[-1]["properties"][oid]
            yield page
        return
    if not isinstance(bounds, list) or len(bounds) != 2:
        raise ValueError("Parallel ArcGIS acquisition requires discovered OID bounds")
    lower, upper = map(int, bounds)
    width = (upper - lower + workers) // workers
    if width < 1:
        raise ValueError("Invalid ArcGIS OID bounds")
    # Each worker has one bounded page in flight. Round-robin consumption makes
    # output independent of network timing, without buffering an entire range.
    executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="arcgis-read")
    pending: dict[int, tuple[Future[tuple[list[dict[str, Any]], int]], int]] = {}
    windows: dict[int, _PageWindow] = {}
    try:
        for index in range(workers):
            start = lower + index * width
            if start > upper:
                break
            end = min(upper, start + width - 1)
            windows[index] = _PageWindow(size, size)
            pending[index] = (
                executor.submit(
                    _fetch_adaptive_page, client, descriptor, oid, size, start - 1, end
                ),
                end,
            )
        while pending:
            for index in sorted(pending):
                future, end = pending.pop(index)
                page, stream_size = future.result()
                del future
                if page:
                    windows[index].completed(page, stream_size)
                    previous = page[-1]["properties"][oid]
                    yield page
                    del page
                    pending[index] = (
                        executor.submit(
                            _fetch_adaptive_page,
                            client,
                            descriptor,
                            oid,
                            windows[index].size,
                            previous,
                            end,
                        ),
                        end,
                    )
    finally:
        for future, _ in pending.values():
            future.cancel()
        executor.shutdown(wait=True, cancel_futures=True)


def _fetch_adaptive_page(
    client: httpx.Client,
    descriptor: dict[str, Any],
    oid: str,
    size: int,
    previous: int | None,
    upper: int | None,
) -> tuple[list[dict[str, Any]], int]:
    """Retry only transport-capacity failures at the same unchanged OID cursor.

    Return the successful bound so this serial stream or parallel OID range keeps
    its smaller pages. Malformed JSON, publisher error objects and invalid source
    features fail immediately; no record can be skipped by resizing a page.
    """
    while True:
        try:
            return _fetch_page(client, descriptor, oid, size, previous, upper), size
        except _ArcGISPageCapacityError:
            if size == 1:
                raise
            size = max(1, size // 2)


def _esri_page(page: dict[str, Any]) -> dict[str, Any]:
    sr = page.get("spatialReference", {})
    if sr.get("latestWkid", sr.get("wkid")) != 4326:
        raise ValueError("ArcGIS did not honour the requested output CRS")
    features = page.get("features")
    if not isinstance(features, list):
        raise ValueError("ArcGIS did not return features")
    converted = []
    for feature in features:
        geometry = feature.get("geometry")
        if geometry is not None:
            if "rings" in geometry:
                rings = geometry["rings"]
                if not rings or any(len(ring) < 4 or ring[0] != ring[-1] for ring in rings):
                    raise ValueError("ArcGIS polygon contains empty or unclosed rings")
                errors: dict[str, Any] = {}
                polygons = shapefile.organize_polygon_rings(rings, errors)
                if errors:
                    raise ValueError("ArcGIS polygon rings have ambiguous topology")
                geometry = {
                    "type": "Polygon" if len(polygons) == 1 else "MultiPolygon",
                    "coordinates": polygons[0] if len(polygons) == 1 else polygons,
                }
            elif "x" in geometry and "y" in geometry:
                geometry = {"type": "Point", "coordinates": [geometry["x"], geometry["y"]]}
            else:
                raise ValueError("Unsupported Esri geometry")
        converted.append(
            {"type": "Feature", "properties": feature.get("attributes"), "geometry": geometry}
        )
    return {
        "type": "FeatureCollection",
        "features": converted,
        "exceededTransferLimit": page.get("exceededTransferLimit", False),
    }


def _recover_projected_empty(
    client: httpx.Client, descriptor: dict[str, Any], oid: str, page: dict[str, Any]
) -> int:
    """Retain a native BFPL polygon the publisher's geographic projection dropped."""
    if (
        descriptor.get("empty_projection_fallback") != "EPSG:3857"
        or descriptor.get("source_crs") != "EPSG:3857"
        or descriptor.get("url") != _HOSTED_BFPL
    ):
        return 0
    features = page.get("features")
    if not isinstance(features, list):
        return 0
    extra_bytes = 0
    for feature in features:
        projected = feature.get("geometry")
        if not isinstance(projected, dict) or projected.get("rings") != []:
            continue
        attributes = feature.get("attributes")
        value = attributes.get(oid) if isinstance(attributes, dict) else None
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError("Projected-empty fallback requires the source object identifier")
        native = _read_json(
            client,
            str(descriptor["url"]) + "/query",
            {
                "f": "json",
                "where": f"({descriptor.get('where', '1=1')}) AND {oid}={value}",
                "outFields": "*",
                "returnGeometry": "true",
                "outSR": "3857",
                "orderByFields": f"{oid} ASC",
                "resultRecordCount": "1",
            },
        )
        extra_bytes += getattr(native, "response_bytes", _MAX_RESPONSE_BYTES)
        if extra_bytes + getattr(page, "response_bytes", _MAX_RESPONSE_BYTES) > _MAX_RESPONSE_BYTES:
            raise _ArcGISPageCapacityError("Native fallback exceeds the bounded combined page size")
        sr = native.get("spatialReference", {})
        candidates = native.get("features")
        if (
            sr.get("latestWkid", sr.get("wkid")) not in (3857, 102100)
            or not isinstance(candidates, list)
            or len(candidates) != 1
            or native.get("exceededTransferLimit")
            or candidates[0].get("attributes") != attributes
        ):
            raise ValueError("Native fallback source CRS, identity or attributes changed")
        native_geometry = candidates[0].get("geometry")
        rings = native_geometry.get("rings") if isinstance(native_geometry, dict) else None
        if not isinstance(rings, list) or not rings:
            raise ValueError("Native fallback requires nonempty closed polygon rings")
        transformer = Transformer.from_crs(3857, 4326, always_xy=True)
        transformed = []
        for ring in rings:
            if not isinstance(ring, list) or len(ring) < 4 or ring[0] != ring[-1]:
                raise ValueError("Native fallback requires nonempty closed polygon rings")
            converted = []
            for position in ring:
                if (
                    not isinstance(position, (list, tuple))
                    or len(position) != 2
                    or any(
                        isinstance(item, bool)
                        or not isinstance(item, (int, float))
                        or not math.isfinite(item)
                        for item in position
                    )
                ):
                    raise ValueError("Native fallback requires finite two-dimensional positions")
                longitude, latitude = transformer.transform(position[0], position[1], errcheck=True)
                if not (-180 <= longitude <= 180 and -90 <= latitude <= 90):
                    raise ValueError("Native fallback produced coordinates outside EPSG:4326")
                converted.append([longitude, latitude])
            transformed.append(converted)
        evidence_key = "_propertyscope_geometry_provenance"
        if evidence_key in attributes:
            raise ValueError("Publisher attributes conflict with geometry provenance")
        feature["attributes"] = {
            **attributes,
            evidence_key: {
                "method": "pyproj-always-xy-3857-to-4326",
                "reason": "publisher-projected-empty",
                "native_geometry": native_geometry,
                "publisher_projected_geometry": projected,
            },
        }
        feature["geometry"] = {"rings": transformed}
    return extra_bytes
