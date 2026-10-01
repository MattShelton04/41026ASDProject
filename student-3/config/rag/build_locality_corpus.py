"""Build a geometry-free Feature 3 corpus from accepted Feature 1 reference releases."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import zlib
from collections import defaultdict
from collections.abc import Callable, Iterable, Iterator
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx

FEATURE_KEY = "student-3-suburb-analytics"
CORPUS_ID = "suburb-analytics-guidance"
GEOGRAPHY_DATASET = "abs-geography-2021"
AMENITY_DATASET = "nsw-amenities"
SAL_LAYER = "abs-sal-2021"
LGA_LAYER = "abs-lga-2021"
MAX_NAMES_PER_CATEGORY = 5

JsonObject = dict[str, Any]
Point = tuple[float, float]
Bbox = tuple[float, float, float, float]


def _normalise_name(value: str) -> str:
    return " ".join(value.casefold().split())


def _locality_key(value: str) -> str:
    """Match ABS disambiguation suffixes without broad fuzzy locality matching."""
    return re.sub(r"\s+\(nsw\)$", "", _normalise_name(value))


def _slug(value: str) -> str:
    result = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")
    if not result:
        raise ValueError("locality cannot produce an empty document identifier")
    return result[:70]


def _coordinates(geometry: JsonObject) -> Iterator[Point]:
    def walk(value: Any) -> Iterator[Point]:
        if (
            isinstance(value, list)
            and len(value) >= 2
            and isinstance(value[0], int | float)
            and isinstance(value[1], int | float)
        ):
            yield float(value[0]), float(value[1])
            return
        if isinstance(value, list):
            for item in value:
                yield from walk(item)

    yield from walk(geometry.get("coordinates"))


def geometry_bbox(geometry: JsonObject) -> Bbox:
    points = list(_coordinates(geometry))
    if not points:
        raise ValueError("geometry has no coordinates")
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return min(xs), min(ys), max(xs), max(ys)


def _point_on_segment(point: Point, start: Point, end: Point) -> bool:
    px, py = point
    ax, ay = start
    bx, by = end
    cross = (px - ax) * (by - ay) - (py - ay) * (bx - ax)
    if not math.isclose(cross, 0.0, abs_tol=1e-10):
        return False
    return (
        min(ax, bx) - 1e-10 <= px <= max(ax, bx) + 1e-10
        and min(ay, by) - 1e-10 <= py <= max(ay, by) + 1e-10
    )


def _point_in_ring(point: Point, ring: list[list[float]]) -> bool:
    if len(ring) < 3:
        return False
    inside = False
    previous = (float(ring[-1][0]), float(ring[-1][1]))
    for raw in ring:
        current = (float(raw[0]), float(raw[1]))
        if _point_on_segment(point, previous, current):
            return True
        px, py = point
        ax, ay = previous
        bx, by = current
        if (ay > py) != (by > py):
            crossing = (bx - ax) * (py - ay) / (by - ay) + ax
            if px < crossing:
                inside = not inside
        previous = current
    return inside


def _point_in_polygon(point: Point, rings: list[list[list[float]]]) -> bool:
    return (
        bool(rings)
        and _point_in_ring(point, rings[0])
        and not any(_point_in_ring(point, hole) for hole in rings[1:])
    )


def point_in_geometry(point: Point, geometry: JsonObject) -> bool:
    coordinates = geometry.get("coordinates")
    if geometry.get("type") == "Polygon" and isinstance(coordinates, list):
        return _point_in_polygon(point, coordinates)
    if geometry.get("type") == "MultiPolygon" and isinstance(coordinates, list):
        return any(_point_in_polygon(point, polygon) for polygon in coordinates)
    return False


def representative_point(geometry: JsonObject) -> Point:
    """Return a deterministic interior point without retaining derived geometry."""
    west, south, east, north = geometry_bbox(geometry)
    candidates = [((west + east) / 2, (south + north) / 2)]
    points = list(_coordinates(geometry))
    candidates.append(
        (
            sum(point[0] for point in points) / len(points),
            sum(point[1] for point in points) / len(points),
        )
    )
    for rows in (9, 17):
        for y_index in range(1, rows):
            for x_index in range(1, rows):
                candidates.append(
                    (
                        west + (east - west) * x_index / rows,
                        south + (north - south) * y_index / rows,
                    )
                )
    for candidate in candidates:
        if point_in_geometry(candidate, geometry):
            return candidate
    raise ValueError("could not find an interior representative point")


def _same_origin(base_url: str, value: str) -> bool:
    base = urlsplit(base_url)
    candidate = urlsplit(value)
    return (candidate.scheme, candidate.hostname, candidate.port) == (
        base.scheme,
        base.hostname,
        base.port,
    )


def _accepted_release(client: httpx.Client, base_url: str, dataset: str) -> JsonObject:
    response = client.get(f"{base_url}/data-products/{dataset}/accepted")
    response.raise_for_status()
    release = response.json().get("release")
    if not isinstance(release, dict) or release.get("status") != "accepted":
        raise ValueError(f"{dataset} has no accepted release")
    return release


def _stream_release(
    client: httpx.Client,
    base_url: str,
    release: JsonObject,
    keep: Callable[[JsonObject], bool],
) -> list[JsonObject]:
    manifest = release.get("manifest_json") or release.get("manifest")
    if not isinstance(manifest, dict) or manifest.get("download_permitted") is not True:
        raise ValueError("accepted release does not permit its declared artifact download")
    release_id = str(release["id"])
    artifact_url = f"{base_url}/dataset-releases/{release_id}/artifact"
    if not _same_origin(base_url, artifact_url):
        raise ValueError("artifact URL escaped the configured Feature 1 origin")
    expected_hash = str(release["content_sha256"])
    expected_count = int(release["record_count"])
    digest = hashlib.sha256()
    decoder = zlib.decompressobj(16 + zlib.MAX_WBITS)
    buffer = b""
    count = 0
    selected: list[JsonObject] = []

    def consume(data: bytes) -> None:
        nonlocal buffer, count
        buffer += data
        lines = buffer.split(b"\n")
        buffer = lines.pop()
        for line in lines:
            if not line.strip():
                continue
            count += 1
            record = json.loads(line)
            if not isinstance(record, dict):
                raise ValueError("artifact contains a non-object record")
            if keep(record):
                selected.append(record)

    with client.stream("GET", artifact_url) as response:
        response.raise_for_status()
        if response.is_redirect:
            raise ValueError("artifact download must not redirect")
        for chunk in response.iter_raw():
            digest.update(chunk)
            consume(decoder.decompress(chunk))
        consume(decoder.flush())
    if buffer.strip():
        count += 1
        record = json.loads(buffer)
        if not isinstance(record, dict):
            raise ValueError("artifact contains a non-object record")
        if keep(record):
            selected.append(record)
    if count != expected_count or digest.hexdigest() != expected_hash:
        raise ValueError("artifact record count or SHA-256 does not match the accepted release")
    return selected


def _load_guidance(manifest_path: Path) -> list[JsonObject]:
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    documents: list[JsonObject] = []
    for source in payload["documents"]:
        document = dict(source)
        relative = document.pop("path", None)
        if relative is not None:
            resolved = (manifest_path.parent / str(relative)).resolve()
            if not resolved.is_relative_to(manifest_path.parent.resolve()):
                raise ValueError("guidance document escapes its corpus directory")
            document["text"] = resolved.read_text(encoding="utf-8")
        documents.append(document)
    return documents


def _release_date(release: JsonObject) -> str:
    manifest = release.get("manifest_json") or release.get("manifest") or {}
    value = str(manifest.get("source_retrieved_at") or release.get("created_at") or "")
    return value[:10] if re.fullmatch(r"\d{4}-\d{2}-\d{2}.*", value) else date.today().isoformat()


def _source_line(dataset: str, release: JsonObject) -> str:
    manifest = release.get("manifest_json") or release.get("manifest") or {}
    return (
        f"{dataset} release {release['id']} ({release['record_count']:,} records), "
        f"retrieved {manifest.get('source_retrieved_at', 'date unavailable')}."
    )


def build_documents(
    *,
    localities: Iterable[str],
    geography: list[JsonObject],
    amenities: list[JsonObject],
    geography_release: JsonObject,
    amenity_release: JsonObject,
    base_url: str,
) -> list[JsonObject]:
    requested = {_locality_key(locality): locality for locality in localities}
    suburbs: dict[str, JsonObject] = {}
    lgas: list[JsonObject] = []
    for record in geography:
        layer = record.get("layer")
        geometry = record.get("geometry")
        if not isinstance(geometry, dict) or geometry.get("type") not in {
            "Polygon",
            "MultiPolygon",
        }:
            continue
        if layer == SAL_LAYER and _locality_key(str(record.get("name", ""))) in requested:
            suburbs[_locality_key(str(record["name"]))] = record
        elif layer == LGA_LAYER:
            lgas.append(record)
    missing = sorted(set(requested) - set(suburbs))
    if missing:
        raise ValueError(
            f"accepted geography release lacks requested localities: {', '.join(missing)}"
        )

    lga_shapes = [(record, geometry_bbox(record["geometry"])) for record in lgas]
    amenity_points: list[tuple[Point, JsonObject]] = []
    for record in amenities:
        geometry = record.get("geometry")
        coordinates = geometry.get("coordinates") if isinstance(geometry, dict) else None
        if (
            isinstance(geometry, dict)
            and geometry.get("type") == "Point"
            and isinstance(coordinates, list)
            and len(coordinates) >= 2
        ):
            amenity_points.append(((float(coordinates[0]), float(coordinates[1])), record))

    documents: list[JsonObject] = []
    for key, requested_name in requested.items():
        suburb = suburbs[key]
        geometry = suburb["geometry"]
        west, south, east, north = geometry_bbox(geometry)
        point = representative_point(geometry)
        matching_lgas = sorted(
            {
                str(record["name"])
                for record, bbox in lga_shapes
                if bbox[0] <= point[0] <= bbox[2]
                and bbox[1] <= point[1] <= bbox[3]
                and point_in_geometry(point, record["geometry"])
            }
        )
        grouped: dict[str, list[str]] = defaultdict(list)
        for amenity_point, amenity in amenity_points:
            if not (
                west <= amenity_point[0] <= east
                and south <= amenity_point[1] <= north
                and point_in_geometry(amenity_point, geometry)
            ):
                continue
            category = str(amenity.get("layer") or "other")
            name = str(amenity.get("name") or "Unnamed recorded facility")
            grouped[category].append(name)

        lga_text = ", ".join(matching_lgas) if matching_lgas else "not resolved"
        facility_lines = []
        for category in sorted(grouped):
            names = sorted(set(grouped[category]))
            examples = "; ".join(names[:MAX_NAMES_PER_CATEGORY])
            suffix = f" Examples: {examples}." if examples else ""
            facility_lines.append(
                f"- {category}: {len(grouped[category])} recorded point(s).{suffix}"
            )
        facilities = "\n".join(facility_lines) or (
            "- No registered facility points were associated with this statistical-locality "
            "polygon. This is unavailable coverage, not proof that the locality has no amenities."
        )
        sal_code = suburb["attributes"].get("sal_code_2021", "unavailable")
        text = "\n\n".join(
            (
                f"# {requested_name} official geography and amenity evidence",
                "## Geographic identity",
                f"The accepted ABS 2021 geography release records {suburb['name']} as "
                f"statistical-locality code {sal_code}. A deterministic interior "
                "representative point falls within the following 2021 LGA polygon: "
                f"{lga_text}. This representative-point association is not an official "
                "suburb-to-LGA crosswalk; locality and LGA boundaries can differ or overlap.",
                "## Recorded facilities",
                "The accepted NSW amenities release contains these registered facility points "
                f"inside the ABS statistical-locality polygon:\n\n{facilities}",
                "Facility counts describe registered source layers, not service quality, "
                "capacity, accessibility, route frequency or travel time. Missing categories "
                "do not establish real-world absence. A station point can support a statement "
                "that rail or bus infrastructure is recorded, but not that transport is good.",
                "## Provenance and use",
                f"{_source_line(GEOGRAPHY_DATASET, geography_release)}\n"
                f"{_source_line(AMENITY_DATASET, amenity_release)}",
                "This geometry-free assistant projection was generated from accepted releases. "
                "Polygon and point coordinates were used only during deterministic association "
                "and are not included in this document. Rebuild and reingest after either "
                "accepted release changes.",
            )
        )
        documents.append(
            {
                "document_id": f"locality-{_slug(requested_name)}",
                "title": f"{requested_name} official geography and amenity evidence",
                "source_uri": f"{base_url}/data-products/{GEOGRAPHY_DATASET}/accepted",
                "source_date": max(
                    _release_date(geography_release), _release_date(amenity_release)
                ),
                "license": (
                    "ABS CC BY 4.0 and NSW Spatial Services CC BY; derived assistant projection"
                ),
                "evidence_kind": "official",
                "location": f"Accepted locality projection: {requested_name}",
                "text": text,
            }
        )
    return documents


def build_manifest(
    *,
    api_base: str,
    localities: Iterable[str],
    guidance_manifest: Path,
) -> JsonObject:
    base_url = api_base.rstrip("/")
    with httpx.Client(timeout=httpx.Timeout(120, connect=10), follow_redirects=False) as client:
        geography_release = _accepted_release(client, base_url, GEOGRAPHY_DATASET)
        amenity_release = _accepted_release(client, base_url, AMENITY_DATASET)
        requested = {_locality_key(locality) for locality in localities}
        geography = _stream_release(
            client,
            base_url,
            geography_release,
            lambda record: (
                record.get("layer") == LGA_LAYER
                or (
                    record.get("layer") == SAL_LAYER
                    and _locality_key(str(record.get("name", ""))) in requested
                )
            ),
        )
        amenities = _stream_release(
            client,
            base_url,
            amenity_release,
            lambda record: (
                isinstance(record.get("geometry"), dict)
                and record["geometry"].get("type") == "Point"
            ),
        )
    return {
        "schema_version": "1.0",
        "feature_key": FEATURE_KEY,
        "corpus_id": CORPUS_ID,
        "documents": [
            *_load_guidance(guidance_manifest),
            *build_documents(
                localities=localities,
                geography=geography,
                amenities=amenities,
                geography_release=geography_release,
                amenity_release=amenity_release,
                base_url=base_url,
            ),
        ],
    }


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--api-base",
        default="http://127.0.0.1:5200/api/data-platform/v1",
        help="Feature 1 public API root",
    )
    parser.add_argument(
        "--localities",
        type=Path,
        default=Path(__file__).with_name("supported-localities.json"),
        help="JSON array of exact ABS locality names",
    )
    parser.add_argument(
        "--guidance-manifest",
        type=Path,
        default=Path(__file__).with_name("corpus.json"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(".propertyscope-runtime/host/rag/suburb-analytics-generated.json"),
    )
    return parser.parse_args()


def main() -> None:
    args = _arguments()
    localities = json.loads(args.localities.read_text(encoding="utf-8"))
    if not isinstance(localities, list) or not all(
        isinstance(locality, str) and locality.strip() for locality in localities
    ):
        raise ValueError("localities file must contain a JSON array of non-empty strings")
    if len(localities) != len({_normalise_name(locality) for locality in localities}):
        raise ValueError("localities file contains duplicate names")
    payload = build_manifest(
        api_base=args.api_base,
        localities=localities,
        guidance_manifest=args.guidance_manifest,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    official = sum(document.get("evidence_kind") == "official" for document in payload["documents"])
    print(
        json.dumps(
            {
                "output": str(args.output),
                "documents": len(payload["documents"]),
                "official_locality_documents": official,
            }
        )
    )


if __name__ == "__main__":
    main()
