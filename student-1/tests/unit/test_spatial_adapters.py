from __future__ import annotations

import re
from collections.abc import Iterator
from copy import deepcopy
from typing import Any

import httpx
import pytest

from propertyscope_data_platform.adapters import arcgis
from propertyscope_data_platform.adapters.arcgis import (
    _esri_page,
    discover_arcgis_layer,
    iter_arcgis_features,
)
from propertyscope_data_platform.adapters.spatial import (
    _date,
    discover_spatial_sources,
    iter_spatial_records,
)

URL = (
    "https://mapprod1.environment.nsw.gov.au/arcgis/rest/services/Planning/"
    "EPI_Protection_Layers/MapServer/1"
)
METADATA = {
    "fields": [{"name": "OBJECTID", "type": "esriFieldTypeOID"}],
    "advancedQueryCapabilities": {"supportsOrderBy": True},
    "extent": {"spatialReference": {"wkid": 4283}},
    "maxRecordCount": 2,
}


def _feature(oid: int) -> dict[str, Any]:
    return {
        "type": "Feature",
        "properties": {"OBJECTID": oid, "LAY_CLASS": "Flood Planning Area"},
        "geometry": None,
    }


def _client(
    pages: list[list[dict[str, Any]]], count: int = 3, final_count: int | None = None
) -> httpx.Client:
    count_reads = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal count_reads
        if request.url.path.endswith("/query"):
            if request.url.params.get("returnCountOnly"):
                count_reads += 1
                value = final_count if count_reads > 1 and final_count is not None else count
                return httpx.Response(200, json={"count": value})
            assert request.url.params["outSR"] == "4326"
            return httpx.Response(200, json={"type": "FeatureCollection", "features": pages.pop(0)})
        return httpx.Response(200, json=METADATA)

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_keyset_continues_after_short_page_and_reconciles_complete_count() -> None:
    with _client([[_feature(2)], [_feature(7), _feature(11)], []]) as client:
        descriptor = discover_arcgis_layer(client, URL, "flood-planning")
        records = list(iter_arcgis_features(client, descriptor))
    assert [r["properties"]["OBJECTID"] for r in records] == [2, 7, 11]
    assert descriptor["source_crs"] == "EPSG:4283"
    assert descriptor["coverage"]["kind"] == "complete-publisher-layer"
    assert descriptor["edition"] is None


@pytest.mark.parametrize("field", ["enddate", "EndDate"])
def test_publisher_open_end_sentinel_remains_raw_but_is_not_a_real_expiry(field: str) -> None:
    attributes = {field: 32503680000000}
    assert _date(attributes, field, open_ended=True) is None
    assert attributes[field] == 32503680000000
    assert _date({field: 1756684800000}, field, open_ended=True) == "2025-09-01T00:00:00+00:00"


@pytest.mark.parametrize(
    ("pages", "count", "final_count", "message"),
    [
        ([[_feature(1)], []], 3, None, "incomplete"),
        ([[_feature(1)], [_feature(1)]], 3, None, "repeated"),
        ([[_feature(1), _feature(2)]], 1, None, "changed"),
        ([[_feature(1)], []], 1, 2, "count changed"),
        ([[{"properties": {}}]], 1, None, "identifier"),
    ],
)
def test_incomplete_or_mutating_sources_never_finish(
    pages: list[list[dict[str, Any]]], count: int, final_count: int | None, message: str
) -> None:
    with _client(pages, count, final_count) as client:
        descriptor = discover_arcgis_layer(client, URL, "flood-planning")
        with pytest.raises(ValueError, match=message):
            list(iter_arcgis_features(client, descriptor))


def test_flood_planning_never_infers_scenario_or_study_extent() -> None:
    with _client([[_feature(1)], []], 1) as client:
        objects = discover_spatial_sources("nsw-flood-planning", client)
        records = list(iter_spatial_records("nsw-flood-planning", client, objects))
    assert records[0]["attributes"]["aep_percent"] is None
    assert records[0]["attributes"]["study_extent"] is None
    assert records[0]["attributes"]["evidence_kind"] == "flood-planning-control"
    assert records[0]["attributes"]["absence_interpretation"] == "unknown"
    assert records[0]["geometry"] is None
    assert "council mapping may be newer" in objects[0]["coverage"]["interpretation"]


def test_profile_inventory_must_include_exact_registered_layers() -> None:
    with _client([]) as client, pytest.raises(ValueError, match="inventory"):
        list(iter_spatial_records("nsw-planning-controls", client, []))


@pytest.mark.parametrize(
    "url", ["http://example.com/MapServer/0", URL + "?token=x", URL.replace("mapprod1", "attacker")]
)
def test_untrusted_endpoint_is_rejected_without_network(url: str) -> None:
    with _client([]) as client, pytest.raises(ValueError, match="allowlist"):
        discover_arcgis_layer(client, url, "untrusted")


def test_esri_conversion_preserves_holes_and_disconnected_polygons() -> None:
    outer = [[0, 0], [0, 4], [4, 4], [4, 0], [0, 0]]
    hole = [[1, 1], [2, 1], [2, 2], [1, 2], [1, 1]]
    other = [[5, 0], [5, 1], [6, 1], [6, 0], [5, 0]]
    page = _esri_page(
        {
            "spatialReference": {"wkid": 4326},
            "features": [
                {"attributes": {"objectid": 1}, "geometry": {"rings": [outer, hole, other]}}
            ],
        }
    )
    geometry = page["features"][0]["geometry"]
    assert geometry["type"] == "MultiPolygon"
    assert geometry["coordinates"] == [[outer, hole], [other]]


def test_esri_conversion_rejects_wrong_crs_and_orphan_hole() -> None:
    with pytest.raises(ValueError, match="CRS"):
        _esri_page({"spatialReference": {"wkid": 3857}, "features": []})
    with pytest.raises(ValueError, match="topology"):
        _esri_page(
            {
                "spatialReference": {"wkid": 4326},
                "features": [{"geometry": {"rings": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]}}],
            }
        )


def test_dates_keep_source_milliseconds_and_unknowns() -> None:
    assert _date({"a": 0}, "a") == "1970-01-01T00:00:00+00:00"
    assert _date({"a": None}, "a") is None
    with pytest.raises(ValueError, match="date"):
        _date({"a": "unknown"}, "a")


def test_parallel_pages_match_serial_records_and_preserve_deterministic_order() -> None:
    ids = [2, 3, 7, 8, 11, 19, 20, 21, 25, 26]

    def handler(request: httpx.Request) -> httpx.Response:
        params = request.url.params
        if not request.url.path.endswith("/query"):
            return httpx.Response(200, json=METADATA)
        if params.get("returnCountOnly"):
            return httpx.Response(200, json={"count": len(ids)})
        if params.get("outStatistics"):
            return httpx.Response(
                200, json={"features": [{"attributes": {"min_oid": 2, "max_oid": 26}}]}
            )
        where = params["where"]
        lower_match = re.search(r"OBJECTID>(\d+)", where)
        upper_match = re.search(r"OBJECTID<=(\d+)", where)
        lower = int(lower_match[1]) if lower_match else -1
        upper = int(upper_match[1]) if upper_match else 100
        matches = [_feature(oid) for oid in ids if lower < oid <= upper][:2]
        return httpx.Response(200, json={"type": "FeatureCollection", "features": matches})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        serial = discover_arcgis_layer(client, URL, "example")
        parallel = discover_arcgis_layer(client, URL, "example", workers=4)
        serial_records = list(iter_arcgis_features(client, serial))
        parallel_records = list(iter_arcgis_features(client, parallel))
        repeat = list(iter_arcgis_features(client, parallel))
    assert sorted(parallel_records, key=lambda row: row["properties"]["OBJECTID"]) == serial_records
    assert parallel_records == repeat


def test_parallel_partial_page_failure_cannot_report_complete() -> None:
    with _client([[]], count=1) as client:
        descriptor = discover_arcgis_layer(client, URL, "example")
        descriptor.update(workers=4, oid_bounds=[1, 1])
        with pytest.raises(ValueError, match="incomplete"):
            list(iter_arcgis_features(client, descriptor))


def test_fixed_filter_is_preserved_in_count_and_all_pages() -> None:
    where = "classsubtype=2 AND buildingcomplextype=11"
    pages = [[_feature(1)], []]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/query"):
            assert where in request.url.params["where"]
            if request.url.params.get("returnCountOnly"):
                return httpx.Response(200, json={"count": 1})
            return httpx.Response(200, json={"type": "FeatureCollection", "features": pages.pop(0)})
        return httpx.Response(200, json=METADATA)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        descriptor = discover_arcgis_layer(client, URL, "libraries", where=where)
        assert len(list(iter_arcgis_features(client, descriptor))) == 1
        assert descriptor["coverage"]["kind"] == "complete-publisher-filter"


@pytest.mark.parametrize("workers", [1, 4])
@pytest.mark.parametrize("failure", ["oversized", "html", "query-500"])
def test_adaptive_pages_preserve_records_and_remember_each_stream_bound(
    monkeypatch: pytest.MonkeyPatch, workers: int, failure: str
) -> None:
    monkeypatch.setattr(arcgis, "_MAX_RESPONSE_BYTES", 2048)
    monkeypatch.setattr("propertyscope_data_platform.adapters.arcgis.time.sleep", lambda _: None)
    requests: dict[int, list[tuple[int, int]]] = {}
    count_reads = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal count_reads
        params = request.url.params
        if not request.url.path.endswith("/query"):
            return httpx.Response(200, json={**METADATA, "maxRecordCount": 8})
        if params.get("returnCountOnly"):
            count_reads += 1
            return httpx.Response(200, json={"count": 32})
        if params.get("outStatistics"):
            return httpx.Response(
                200, json={"features": [{"attributes": {"min_oid": 1, "max_oid": 32}}]}
            )
        lower_match = re.search(r"OBJECTID>(\d+)", params["where"])
        upper_match = re.search(r"OBJECTID<=(\d+)", params["where"])
        lower = int(lower_match[1]) if lower_match else 0
        upper = int(upper_match[1]) if upper_match else 32
        size = int(params["resultRecordCount"])
        requests.setdefault(upper, []).append((lower, size))
        if size > 2:
            if failure == "query-500":
                return httpx.Response(
                    500,
                    content=b'<html lang="en"><title>Error performing query operation</title>',
                )
            content = (
                b"x" * 2049
                if failure == "oversized"
                else b"\xef\xbb\xbf\n<!DOCTYPE HTML><html>Service page too large</html>"
            )
            return httpx.Response(200, content=content)
        features = [_feature(oid) for oid in range(lower + 1, min(upper, lower + size) + 1)]
        return httpx.Response(200, json={"type": "FeatureCollection", "features": features})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        descriptor = discover_arcgis_layer(client, URL, "example", workers=workers)
        adapted = list(iter_arcgis_features(client, descriptor))
        assert len(requests) == workers
        retry_count = 3 if failure == "query-500" else 1
        prefix_sizes = [8] * retry_count + [4] * retry_count + [2]
        for stream in requests.values():
            prefix = stream[: len(prefix_sizes)]
            assert [size for _, size in prefix] == prefix_sizes
            assert len({cursor for cursor, _ in prefix}) == 1
            assert all(size == 2 for _, size in stream[len(prefix_sizes) :])
        requests.clear()
        expected = list(iter_arcgis_features(client, {**descriptor, "page_size": 2}))
    assert adapted == expected
    assert sorted(row["properties"]["OBJECTID"] for row in adapted) == list(range(1, 33))
    assert count_reads == 3  # Discovery and both complete-stream reconciliations.
    assert descriptor["page_size"] == 8  # Shared discovery evidence is never mutated.


@pytest.mark.parametrize("failure", ["oversized", "html", "query-500"])
def test_adaptive_pages_fail_at_one_without_skipping_a_feature(
    monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    monkeypatch.setattr(arcgis, "_MAX_RESPONSE_BYTES", 2048)
    monkeypatch.setattr("propertyscope_data_platform.adapters.arcgis.time.sleep", lambda _: None)
    sizes = []

    def handler(request: httpx.Request) -> httpx.Response:
        if not request.url.path.endswith("/query"):
            return httpx.Response(200, json={**METADATA, "maxRecordCount": 8})
        if request.url.params.get("returnCountOnly"):
            return httpx.Response(200, json={"count": 1})
        sizes.append(int(request.url.params["resultRecordCount"]))
        assert "OBJECTID>" not in request.url.params["where"]
        if failure == "query-500":
            return httpx.Response(
                500, content=b"<html><title>Error performing query operation</title></html>"
            )
        content = b"x" * 2049 if failure == "oversized" else b"<html>Error</html>"
        return httpx.Response(200, content=content)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        descriptor = discover_arcgis_layer(client, URL, "example")
        with pytest.raises(ValueError, match=r"bounded page size|HTML page|HTTP 500"):
            list(iter_arcgis_features(client, descriptor))
    attempts = 3 if failure == "query-500" else 1
    assert sizes == [size for size in [8, 4, 2, 1] for _ in range(attempts)]


@pytest.mark.parametrize(
    "content",
    [
        b'{"features": [',
        b'{"error":{"code":400,"message":"Invalid query"}}',
        b'{"type":"FeatureCollection","features":[{"properties":{}}]}',
    ],
)
def test_invalid_source_json_is_not_retried_as_page_capacity(content: bytes) -> None:
    sizes = []

    def handler(request: httpx.Request) -> httpx.Response:
        if not request.url.path.endswith("/query"):
            return httpx.Response(200, json=METADATA)
        if request.url.params.get("returnCountOnly"):
            return httpx.Response(200, json={"count": 1})
        sizes.append(int(request.url.params["resultRecordCount"]))
        return httpx.Response(200, content=content)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        descriptor = discover_arcgis_layer(client, URL, "example")
        with pytest.raises(ValueError):
            list(iter_arcgis_features(client, descriptor))
    assert sizes == [2]


@pytest.mark.parametrize("publisher_limit", [75, 1500, 4000])
def test_standard_queries_respect_publisher_and_application_page_limits(
    publisher_limit: int,
) -> None:
    requested_sizes = []
    expected_size = min(publisher_limit, 2000)
    count = expected_size + 3

    def handler(request: httpx.Request) -> httpx.Response:
        params = request.url.params
        if not request.url.path.endswith("/query"):
            return httpx.Response(
                200,
                json={
                    **METADATA,
                    "maxRecordCount": 100,
                    "standardMaxRecordCount": publisher_limit,
                    "advancedQueryCapabilities": {
                        "supportsOrderBy": True,
                        "supportsQueryWithResultType": True,
                    },
                },
            )
        if params.get("returnCountOnly"):
            return httpx.Response(200, json={"count": count})
        assert params["resultType"] == "standard"
        size = int(params["resultRecordCount"])
        requested_sizes.append(size)
        lower_match = re.search(r"OBJECTID>(\d+)", params["where"])
        lower = int(lower_match[1]) if lower_match else 0
        features = [_feature(oid) for oid in range(lower + 1, min(count, lower + size) + 1)]
        return httpx.Response(200, json={"type": "FeatureCollection", "features": features})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        descriptor = discover_arcgis_layer(client, URL, "example", standard_page_size=2000)
        assert descriptor["page_size"] == expected_size
        assert descriptor["publisher_page_limit"] == publisher_limit
        descriptor["page_size"] = 9999  # Replay also enforces both immutable bounds.
        records = list(iter_arcgis_features(client, descriptor))
    assert requested_sizes == [expected_size] * 3
    assert [row["properties"]["OBJECTID"] for row in records] == list(range(1, count + 1))


@pytest.mark.parametrize(
    ("profile", "page_size", "result_type"),
    [
        ("nsw-cadastre", 2000, "standard"),
        ("nsw-planning-controls", 100, None),
        ("nsw-bushfire-prone-land", 100, None),
        ("nsw-flood-planning", 100, None),
    ],
)
def test_only_cadastre_opts_into_advertised_standard_query_mode(
    profile: str, page_size: int, result_type: str | None
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/query"):
            return httpx.Response(200, json={"count": 0})
        return httpx.Response(
            200,
            json={
                **METADATA,
                "maxRecordCount": 100,
                "standardMaxRecordCount": 4000,
                "advancedQueryCapabilities": {
                    "supportsOrderBy": True,
                    "supportsQueryWithResultType": True,
                },
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        descriptors = discover_spatial_sources(profile, client)
    assert all(item["page_size"] == page_size for item in descriptors)
    assert all(item["query_result_type"] == result_type for item in descriptors)


def test_standard_query_opt_in_falls_back_when_not_advertised() -> None:
    with _client([[_feature(1)], []], count=1) as client:
        descriptor = discover_arcgis_layer(client, URL, "example", standard_page_size=2000)
        assert descriptor["query_result_type"] is None
        assert descriptor["page_size"] == METADATA["maxRecordCount"]
        assert len(list(iter_arcgis_features(client, descriptor))) == 1


@pytest.mark.parametrize(
    ("status", "content"),
    [
        (500, b"<html>Unrelated internal server error</html>"),
        (500, b'{"error":{"message":"Error performing query operation"}}'),
        (503, b"<html>Error performing query operation</html>"),
        (401, b"<html>Error performing query operation</html>"),
    ],
)
def test_other_http_errors_do_not_trigger_smaller_feature_pages(
    monkeypatch: pytest.MonkeyPatch, status: int, content: bytes
) -> None:
    monkeypatch.setattr("propertyscope_data_platform.adapters.arcgis.time.sleep", lambda _: None)
    sizes = []

    def handler(request: httpx.Request) -> httpx.Response:
        if not request.url.path.endswith("/query"):
            return httpx.Response(200, json=METADATA)
        if request.url.params.get("returnCountOnly"):
            return httpx.Response(200, json={"count": 1})
        sizes.append(int(request.url.params["resultRecordCount"]))
        return httpx.Response(status, content=content)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        descriptor = discover_arcgis_layer(client, URL, "example")
        with pytest.raises(httpx.HTTPStatusError) as error:
            list(iter_arcgis_features(client, descriptor))
    assert error.value.response.status_code == status
    assert sizes == [2] * (1 if status == 401 else 3)


@pytest.mark.parametrize(
    "params",
    [
        {"f": "json"},
        {"f": "json", "returnCountOnly": "true"},
        {"f": "json", "returnGeometry": "false", "resultRecordCount": "2"},
        {"f": "json", "returnGeometry": "true"},
    ],
)
def test_query_error_html_does_not_change_discovery_or_nonfeature_http_errors(
    monkeypatch: pytest.MonkeyPatch, params: dict[str, str]
) -> None:
    monkeypatch.setattr("propertyscope_data_platform.adapters.arcgis.time.sleep", lambda _: None)
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(500, content=b"<html>Error performing query operation</html>")

    with (
        httpx.Client(transport=httpx.MockTransport(handler)) as client,
        pytest.raises(httpx.HTTPStatusError),
    ):
        arcgis._read_json(client, URL + "/query", params)
    assert len(requests) == 3


def test_query_error_classification_reads_only_a_bounded_error_prefix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("propertyscope_data_platform.adapters.arcgis.time.sleep", lambda _: None)
    chunks_read = []

    class ErrorStream(httpx.SyncByteStream):
        def __iter__(self) -> Iterator[bytes]:
            for chunk in [b"<html>" + b"x" * 8186, b"Error performing query operation</html>"]:
                chunks_read.append(len(chunk))
                yield chunk

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, stream=ErrorStream())

    with (
        httpx.Client(transport=httpx.MockTransport(handler)) as client,
        pytest.raises(httpx.HTTPStatusError),
    ):
        arcgis._read_json(
            client,
            URL + "/query",
            {"f": "json", "returnGeometry": "true", "resultRecordCount": "2"},
        )
    assert chunks_read == [8192]


@pytest.mark.parametrize("workers", [1, 4])
def test_page_regrowth_preserves_all_ids_and_restores_bounded_throughput(
    monkeypatch: pytest.MonkeyPatch, workers: int
) -> None:
    monkeypatch.setattr(arcgis, "_MAX_RESPONSE_BYTES", 65536)
    requests: dict[int, list[tuple[int, int]]] = {}

    def source_feature(oid: int) -> dict[str, Any]:
        feature = _feature(oid)
        if oid % 100 == 1:
            feature["properties"]["large_source_attribute"] = "x" * 8192
        return feature

    def handler(request: httpx.Request) -> httpx.Response:
        params = request.url.params
        if not request.url.path.endswith("/query"):
            return httpx.Response(200, json={**METADATA, "maxRecordCount": 8})
        if params.get("returnCountOnly"):
            return httpx.Response(200, json={"count": 400})
        if params.get("outStatistics"):
            return httpx.Response(
                200, json={"features": [{"attributes": {"min_oid": 1, "max_oid": 400}}]}
            )
        lower_match = re.search(r"OBJECTID>(\d+)", params["where"])
        upper_match = re.search(r"OBJECTID<=(\d+)", params["where"])
        lower = int(lower_match[1]) if lower_match else 0
        upper = int(upper_match[1]) if upper_match else 400
        size = int(params["resultRecordCount"])
        requests.setdefault(upper, []).append((lower, size))
        ids = range(lower + 1, min(upper, lower + size) + 1)
        if size > 1 and any(oid % 100 == 1 for oid in ids):
            return httpx.Response(200, content=b"<html>Large polygon page</html>")
        return httpx.Response(
            200,
            json={"type": "FeatureCollection", "features": [source_feature(oid) for oid in ids]},
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        descriptor = discover_arcgis_layer(client, URL, "example", workers=workers)
        records = list(iter_arcgis_features(client, descriptor))
        for stream in requests.values():
            assert [size for _, size in stream[:4]] == [8, 4, 2, 1]
            assert len({cursor for cursor, _ in stream[:4]}) == 1
            assert [size for _, size in stream[4:12]] == [1] * 8
            assert stream[12][1] == 2
            assert any(size == 8 for _, size in stream[12:])
            assert all(size <= 8 for _, size in stream)
        assert sum(map(len, requests.values())) < 200
        repeated = list(iter_arcgis_features(client, descriptor))
    assert sorted(records, key=lambda row: row["properties"]["OBJECTID"]) == [
        source_feature(oid) for oid in range(1, 401)
    ]
    assert records == repeated


def test_growth_requires_byte_headroom_and_backs_off_failed_probes() -> None:
    window = arcgis._PageWindow(8, 1)
    small = arcgis._FeaturePage([_feature(1)], 100)
    large = arcgis._FeaturePage([_feature(1)], arcgis._MAX_RESPONSE_BYTES // 2)
    for _ in range(16):
        window.completed(large, 1)
    assert window.size == 1
    for failure in range(3):
        while not window.probing:
            window.completed(small, 1)
        assert window.size == 2
        window.completed(small, 1)  # Failed larger page, same cursor succeeds at one.
        assert window.failed_growth_probes == failure + 1
    assert not window.probing
    # The failed probe's successful small page is the first page of cooldown.
    for _ in range(62):
        window.completed(small, 1)
        assert not window.probing
    window.completed(small, 1)
    assert (window.probing, window.size) == (True, 2)
    window.completed(arcgis._FeaturePage([_feature(1), _feature(2)], 200), 2)
    assert window.failed_growth_probes == 0


def test_current_hosted_bfpl_preserves_lowercase_fields_and_open_end() -> None:
    url = (
        "https://portal.spatial.nsw.gov.au/server/rest/services/Hosted/"
        "NSW_BushFire_Prone_Land/FeatureServer/0"
    )
    metadata = {
        **METADATA,
        "fields": [{"name": "fid", "type": "esriFieldTypeOID"}],
        "extent": {"spatialReference": {"wkid": 102100, "latestWkid": 3857}},
        "maxRecordCount": 2000,
    }
    attributes = {
        "fid": 189388,
        "d_category": "Vegetation Category 3",
        "startdate": 1477958400000,
        "enddate": 32503680000000,
        "lastupdate": 1759795200000,
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url).startswith(url)
        if not request.url.path.endswith("/query"):
            return httpx.Response(200, json=metadata)
        if request.url.params.get("returnCountOnly"):
            return httpx.Response(200, json={"count": 1})
        assert request.url.params["f"] == "json"
        assert request.url.params["outSR"] == "4326"
        features = (
            []
            if "fid>" in request.url.params["where"]
            else [
                {
                    "attributes": attributes,
                    "geometry": {"rings": [[[0, 0], [0, 1], [1, 0], [0, 0]]]},
                }
            ]
        )
        return httpx.Response(200, json={"spatialReference": {"wkid": 4326}, "features": features})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        descriptors = discover_spatial_sources("nsw-bushfire-prone-land", client)
        assert descriptors[0]["page_size"] == 1000
        records = list(iter_spatial_records("nsw-bushfire-prone-land", client, descriptors))
    assert records[0]["record_id"] == "bushfire-prone-land:189388"
    assert records[0]["name"] == "Vegetation Category 3"
    assert records[0]["source_url"] == url
    assert records[0]["source_crs"] == "EPSG:3857"
    assert records[0]["source_updated_at"] == "2025-10-07T00:00:00+00:00"
    assert records[0]["valid_from"] == "2016-11-01T00:00:00+00:00"
    assert records[0]["valid_to"] is None
    assert records[0]["attributes"] == attributes


_THIN_BFPL_RING = [
    [16862693.1634, -3447710.787799999],
    [16862693.1634, -3447710.784400001],
    [16862793.3508, -3447645.1673999988],
    [16862693.1634, -3447710.787799999],
]


def _empty_projection_client(
    failure: str | None = None,
) -> tuple[httpx.Client, list[str]]:
    queries: list[str] = []
    attributes = {"fid": 21, "d_category": "Vegetation Buffer", "area": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        params = request.url.params
        if not request.url.path.endswith("/query"):
            return httpx.Response(
                200,
                json={
                    **METADATA,
                    "fields": [{"name": "fid", "type": "esriFieldTypeOID"}],
                    "extent": {"spatialReference": {"latestWkid": 3857, "wkid": 102100}},
                    "maxRecordCount": 1,
                },
            )
        if params.get("returnCountOnly"):
            return httpx.Response(200, json={"count": 1})
        queries.append(params["outSR"])
        if params["outSR"] == "3857":
            assert params["where"] == "(1=1) AND fid=21"
            assert params["resultRecordCount"] == "1"
            feature: dict[str, Any] = {
                "attributes": dict(attributes),
                "geometry": {"rings": [deepcopy(_THIN_BFPL_RING)]},
            }
            sr = 3857
            if failure == "wrong-crs":
                sr = 4326
            elif failure == "wrong-id":
                feature["attributes"]["fid"] = 22
            elif failure == "changed-attributes":
                feature["attributes"]["area"] = 99
            elif failure == "empty-native":
                feature["geometry"] = {"rings": []}
            elif failure == "missing-native":
                feature["geometry"] = None
            elif failure == "unclosed-native":
                feature["geometry"]["rings"][0][-1] = [0, 0]
            elif failure == "nonfinite-native":
                feature["geometry"]["rings"][0][1] = [1, None]
            return httpx.Response(
                200,
                json={"spatialReference": {"wkid": sr}, "features": [feature]},
            )
        features = (
            []
            if "fid>" in params["where"]
            else [{"attributes": attributes, "geometry": {"rings": []}}]
        )
        return httpx.Response(200, json={"spatialReference": {"wkid": 4326}, "features": features})

    return httpx.Client(transport=httpx.MockTransport(handler)), queries


def test_projected_empty_bfpl_retains_native_polygon_and_explicit_provenance() -> None:
    client, queries = _empty_projection_client()
    with client:
        descriptors = discover_spatial_sources("nsw-bushfire-prone-land", client)
        records = list(iter_spatial_records("nsw-bushfire-prone-land", client, descriptors))
    assert queries == ["4326", "3857", "4326"]
    record = records[0]
    ring = record["geometry"]["coordinates"][0]
    assert len(ring) == 4 and ring[0] == ring[-1] and ring[0] != ring[1]
    assert ring[0] == pytest.approx([151.48015000099983, -29.564644340939505], abs=1e-12)
    evidence = record["attributes"]["_propertyscope_geometry_provenance"]
    assert evidence["native_geometry"] == {"rings": [_THIN_BFPL_RING]}
    assert evidence["publisher_projected_geometry"] == {"rings": []}
    assert evidence["reason"] == "publisher-projected-empty"
    assert record["source_crs"] == "EPSG:3857"


@pytest.mark.parametrize(
    "failure",
    [
        "wrong-crs",
        "wrong-id",
        "changed-attributes",
        "empty-native",
        "missing-native",
        "unclosed-native",
        "nonfinite-native",
    ],
)
def test_native_projection_fallback_rejects_missing_changed_or_malformed_source(
    failure: str,
) -> None:
    client, queries = _empty_projection_client(failure)
    with client:
        descriptors = discover_spatial_sources("nsw-bushfire-prone-land", client)
        with pytest.raises(ValueError, match="Native fallback"):
            list(iter_spatial_records("nsw-bushfire-prone-land", client, descriptors))
    assert queries == ["4326", "3857"]


@pytest.mark.parametrize("unsupported", ["crs", "url", "unregistered"])
def test_empty_projection_fallback_never_applies_outside_verified_bfpl_source(
    unsupported: str,
) -> None:
    client, queries = _empty_projection_client()
    with client:
        descriptor = discover_spatial_sources("nsw-bushfire-prone-land", client)[0]
        if unsupported == "crs":
            descriptor["source_crs"] = "EPSG:4283"
        elif unsupported == "url":
            descriptor["url"] = URL
        else:
            descriptor.pop("empty_projection_fallback")
        with pytest.raises(ValueError, match="empty or unclosed"):
            list(iter_arcgis_features(client, descriptor))
    assert queries == ["4326"]
