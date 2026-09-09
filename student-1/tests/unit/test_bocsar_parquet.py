from __future__ import annotations

import hashlib
import json
import uuid
from datetime import date
from pathlib import Path
from typing import Any, cast

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]
import pytest

from propertyscope_data_platform.adapters.bocsar import CrimeCoverage, CrimeObservation
from propertyscope_data_platform.bocsar_parquet import (
    BOCSAR_PARQUET_MEDIA_TYPE,
    BOCSAR_PARQUET_SCHEMA_VERSION,
    bocsar_parquet_schema,
    write_bocsar_parquet,
)
from propertyscope_data_store.import_profiles import (
    ImportProfileError,
    ImportResult,
    iter_bocsar_parquet_import,
    iter_ndjson_import,
)
from propertyscope_data_store.loader import DatabaseLoader


def _records() -> tuple[CrimeObservation | CrimeCoverage, ...]:
    return (
        CrimeObservation("postcode", "0200", "theft-other", "Theft", "Other", date(2025, 1, 1), 3),
        CrimeCoverage(
            "postcode",
            "0200",
            "theft-other",
            (date(2025, 1, 1), date(2025, 2, 1)),
        ),
    )


def _ndjson_rows() -> list[bytes]:
    rows = (
        {
            "record_kind": "observation",
            "geography_kind": "postcode",
            "geography_value": "0200",
            "source_category_key": "theft-other",
            "offence_label": "Theft",
            "subcategory_label": "Other",
            "month": "2025-01-01",
            "count": 3,
        },
        {
            "record_kind": "coverage",
            "geography_kind": "postcode",
            "geography_value": "0200",
            "source_category_key": "theft-other",
            "observed_months": ["2025-01-01", "2025-02-01"],
            "blank_means_observed_zero": True,
        },
    )
    return [json.dumps(row, sort_keys=True, separators=(",", ":")).encode() + b"\n" for row in rows]


def test_parquet_round_trip_is_semantically_identical_to_legacy_ndjson(tmp_path: Path) -> None:
    path = tmp_path / "bocsar.parquet"

    assert write_bocsar_parquet(path, _records(), batch_rows=1) == 2

    parquet_rows = list(iter_bocsar_parquet_import(path, profile="bocsar-sparse"))
    ndjson_rows = list(iter_ndjson_import(_ndjson_rows(), profile="bocsar-sparse"))
    assert parquet_rows == ndjson_rows
    parquet = pq.ParquetFile(path)
    assert parquet.metadata.num_rows == 2
    assert parquet.metadata.num_row_groups == 2
    assert parquet.schema_arrow.equals(bocsar_parquet_schema())
    assert parquet.schema_arrow.metadata == {
        b"propertyscope.schema_version": BOCSAR_PARQUET_SCHEMA_VERSION.encode(),
        b"propertyscope.import_profile": b"bocsar-sparse",
        b"propertyscope.zero_semantics": b"coverage-evidence-required",
        b"propertyscope.sha256_encoding": b"fixed-size-binary-32",
    }


def test_cached_coverage_still_checks_each_records_checksum(tmp_path: Path) -> None:
    path = tmp_path / "bocsar.parquet"
    write_bocsar_parquet(path, [_records()[1], _records()[1]])
    table = pq.read_table(path)
    records = table.to_pylist()
    records[1]["completeness_sha256"] = b"x" * 32
    pq.write_table(pa.Table.from_pylist(records, schema=table.schema), path)
    rows = iter(iter_bocsar_parquet_import(path, profile="bocsar-sparse"))
    assert next(rows)["month_count"] == 2
    with pytest.raises(ImportProfileError, match="completeness checksum"):
        next(rows)


def test_parquet_writer_is_deterministic_and_materially_smaller_than_ndjson(
    tmp_path: Path,
) -> None:
    records = tuple(
        CrimeObservation(
            "suburb",
            f"SUBURB {index:05d}",
            "theft-other",
            "Theft",
            "Other",
            date(2025, (index % 12) + 1, 1),
            (index % 7) + 1,
        )
        for index in range(10_000)
    )
    first = tmp_path / "first.parquet"
    second = tmp_path / "second.parquet"

    write_bocsar_parquet(first, records)
    write_bocsar_parquet(second, records)
    legacy_bytes = sum(
        len(
            json.dumps(
                {
                    "record_kind": "observation",
                    "geography_kind": item.geography_kind,
                    "geography_value": item.geography_value,
                    "source_category_key": item.category_key,
                    "offence_label": item.offence_label,
                    "subcategory_label": item.subcategory_label,
                    "month": item.month.isoformat(),
                    "count": item.count,
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        )
        + 1
        for item in records
        if isinstance(item, CrimeObservation)
    )

    assert (
        hashlib.sha256(first.read_bytes()).digest() == hashlib.sha256(second.read_bytes()).digest()
    )
    assert first.stat().st_size < legacy_bytes // 2


def test_parquet_reader_rejects_unregistered_schema_before_rows(tmp_path: Path) -> None:
    path = tmp_path / "wrong.parquet"
    pq.write_table(pa.table({"record_kind": ["observation"]}), path)

    with pytest.raises(ImportProfileError, match="schema is not registered"):
        list(iter_bocsar_parquet_import(path, profile="bocsar-sparse"))


def test_parquet_reader_rejects_unregistered_metadata_and_invalid_coverage(
    tmp_path: Path,
) -> None:
    valid = tmp_path / "valid.parquet"
    write_bocsar_parquet(valid, _records())
    table = pq.read_table(valid)

    wrong_metadata = tmp_path / "wrong-metadata.parquet"
    pq.write_table(
        table.replace_schema_metadata(
            {**(table.schema.metadata or {}), b"propertyscope.schema_version": b"unknown"}
        ),
        wrong_metadata,
    )
    with pytest.raises(ImportProfileError, match="metadata is not registered"):
        list(iter_bocsar_parquet_import(wrong_metadata, profile="bocsar-sparse"))

    invalid_coverage = tmp_path / "invalid-coverage.parquet"
    month_count_index = table.schema.get_field_index("month_count")
    pq.write_table(
        table.set_column(
            month_count_index,
            table.schema.field(month_count_index),
            pa.array([None, 3], type=pa.int32()),
        ),
        invalid_coverage,
    )
    with pytest.raises(ImportProfileError, match="month_count does not match"):
        list(iter_bocsar_parquet_import(invalid_coverage, profile="bocsar-sparse"))


class _StreamStore:
    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []

    def import_cancel_requested(self, _operation_id: uuid.UUID) -> bool:
        return False

    def execute_stream_import_profile(
        self,
        _work: dict[str, Any],
        *,
        profile: str,
        rows: Any,
        verify_complete: Any,
        phase_callback: Any,
        **_options: Any,
    ) -> ImportResult:
        assert profile == "bocsar-sparse"
        self.rows = list(rows)
        verify_complete()
        phase_callback("verification", len(self.rows))
        return ImportResult(len(self.rows), len(self.rows), len(self.rows), 0, 1)


def test_loader_verifies_parquet_before_streaming_typed_rows(tmp_path: Path) -> None:
    generated = tmp_path / "generated.parquet"
    write_bocsar_parquet(generated, _records())
    payload = generated.read_bytes()
    digest = hashlib.sha256(payload).hexdigest()
    storage_key = Path("sha256") / digest[:2] / digest
    stored = tmp_path / storage_key
    stored.parent.mkdir(parents=True)
    stored.write_bytes(payload)
    store = _StreamStore()
    loader = DatabaseLoader(cast(Any, store), tmp_path, worker_id="loader-test")
    loader._preflight_materialisation_capacity = lambda *_args, **_kwargs: None  # type: ignore[method-assign]
    work = {
        "id": str(uuid.uuid4()),
        "import_profile_key": "bocsar-sparse",
        "storage_key": storage_key.as_posix(),
        "artifact_bytes": len(payload),
        "content_sha256": digest,
        "media_type": BOCSAR_PARQUET_MEDIA_TYPE,
        "candidate_release_id": str(uuid.uuid4()),
    }

    counts, evidence = loader._execute(work)

    assert counts == {"rows_in": 2, "rows_staged": 2, "rows_accepted": 2, "rows_rejected": 0}
    assert store.rows == list(iter_ndjson_import(_ndjson_rows(), profile="bocsar-sparse"))
    assert evidence["verified"] is True


def test_loader_rejects_corrupt_parquet_before_database_copy(tmp_path: Path) -> None:
    generated = tmp_path / "generated.parquet"
    write_bocsar_parquet(generated, _records())
    payload = generated.read_bytes()
    digest = hashlib.sha256(payload).hexdigest()
    storage_key = Path("sha256") / digest[:2] / digest
    stored = tmp_path / storage_key
    stored.parent.mkdir(parents=True)
    stored.write_bytes(payload[:-1] + bytes([payload[-1] ^ 1]))
    store = _StreamStore()
    loader = DatabaseLoader(cast(Any, store), tmp_path, worker_id="loader-test")
    loader._preflight_materialisation_capacity = lambda *_args, **_kwargs: None  # type: ignore[method-assign]

    with pytest.raises(RuntimeError, match="checksum does not match"):
        loader._execute(
            {
                "id": str(uuid.uuid4()),
                "import_profile_key": "bocsar-sparse",
                "storage_key": storage_key.as_posix(),
                "artifact_bytes": len(payload),
                "content_sha256": digest,
                "media_type": BOCSAR_PARQUET_MEDIA_TYPE,
                "candidate_release_id": str(uuid.uuid4()),
            }
        )
    assert store.rows == []
