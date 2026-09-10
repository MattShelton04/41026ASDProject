from __future__ import annotations

import hashlib
import json
import uuid
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]
import pytest

from propertyscope_data_platform.adapters.psi import PsiSale
from propertyscope_data_platform.psi_parquet import (
    PSI_PARQUET_MEDIA_TYPE,
    PSI_PARQUET_SCHEMA_VERSION,
    psi_parquet_schema,
    write_psi_parquet,
)
from propertyscope_data_platform.runner import _psi_record
from propertyscope_data_store.import_profiles import (
    ImportProfileError,
    ImportResult,
    iter_ndjson_import,
    iter_psi_parquet_import,
)
from propertyscope_data_store.loader import DatabaseLoader


def _sale(index: int = 1, *, house_number: str = "10") -> PsiSale:
    return PsiSale(
        source_business_key=f"001:P{index}:1",
        source_era="post-2001",
        district_code="001",
        property_id=f"P{index}",
        sale_counter="1",
        contract_date=date(2025, 1, 1),
        settlement_date=date(2025, 2, 1),
        price_aud=800_000 + index,
        area_original=Decimal("500.25"),
        area_unit="M",
        area_square_metres=Decimal("500.25"),
        dealing_id=f"D{index}",
        source_system="VG",
        valuation_number=f"V{index}",
        source_downloaded_at=datetime(2025, 3, 4, 5, 6),
        property_name="Example",
        unit_number="u1",
        house_number=house_number,
        street_number_first=None if int(house_number.split("-", 1)[0]) > 2_147_483_647 else 10,
        street_number_last=None,
        street_number_suffix="a",
        street_name="George",
        street_name_normalised="george",
        street_type="st",
        locality="sydney",
        postcode="2000",
        land_description="Lot 1",
        dimensions="10x20",
        zoning_code="R2",
        nature_code="R",
        primary_purpose="Residence",
        strata_lot_number="1",
        component_code="C",
        sale_code="S",
        interest_of_sale="Full",
    )


def _legacy_rows(partitions: tuple[tuple[int, tuple[PsiSale, ...]], ...]) -> list[dict[str, Any]]:
    lines = [
        json.dumps(
            _psi_record(sale, source_year=source_year),
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        + b"\n"
        for source_year, sales in partitions
        for sale in sales
    ]
    return list(iter_ndjson_import(lines, profile="psi-sales"))


def test_psi_parquet_round_trip_preserves_legacy_rows_hashes_and_partition_order(
    tmp_path: Path,
) -> None:
    sale = _sale()
    anomalous = _sale(2, house_number="6711011622")
    partitions = ((2025, (sale, anomalous)), (2026, (sale,)))
    path = tmp_path / "psi.parquet"

    assert write_psi_parquet(path, partitions, batch_rows=10) == 3

    parquet_rows = list(iter_psi_parquet_import(path, profile="psi-sales"))
    assert parquet_rows == _legacy_rows(partitions)
    assert parquet_rows[0]["source_row_sha256"] == parquet_rows[2]["source_row_sha256"]
    assert [row["source_partition_year"] for row in parquet_rows] == [2025, 2025, 2026]
    assert parquet_rows[1]["_propertyscope_import_quality_warnings"] == (
        "address_number_out_of_range",
    )
    parquet = pq.ParquetFile(path)
    assert parquet.metadata.num_row_groups == 2
    assert parquet.schema_arrow.equals(psi_parquet_schema())
    assert parquet.schema_arrow.metadata == {
        b"propertyscope.schema_version": PSI_PARQUET_SCHEMA_VERSION.encode(),
        b"propertyscope.import_profile": b"psi-sales",
        b"propertyscope.partition_semantics": b"source-archive-order",
        b"propertyscope.retransmission_semantics": b"business-key-and-row-sha256",
        b"propertyscope.sha256_encoding": b"fixed-size-binary-32",
    }


def test_psi_parquet_is_deterministic_and_materially_smaller_than_ndjson(tmp_path: Path) -> None:
    sales = tuple(_sale(index) for index in range(1, 10_001))
    partitions = ((2025, sales),)
    first = tmp_path / "first.parquet"
    second = tmp_path / "second.parquet"

    write_psi_parquet(first, partitions)
    write_psi_parquet(second, partitions)
    legacy_bytes = sum(
        len(
            json.dumps(
                _psi_record(sale, source_year=2025),
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        )
        + 1
        for sale in sales
    )

    assert first.read_bytes() == second.read_bytes()
    assert first.stat().st_size < legacy_bytes // 2


def test_psi_parquet_rejects_unregistered_metadata_and_invalid_partition(
    tmp_path: Path,
) -> None:
    valid = tmp_path / "valid.parquet"
    write_psi_parquet(valid, ((2025, (_sale(),)),))
    table = pq.read_table(valid)

    wrong_metadata = tmp_path / "wrong-metadata.parquet"
    pq.write_table(
        table.replace_schema_metadata(
            {**(table.schema.metadata or {}), b"propertyscope.schema_version": b"unknown"}
        ),
        wrong_metadata,
    )
    with pytest.raises(ImportProfileError, match="metadata is not registered"):
        list(iter_psi_parquet_import(wrong_metadata, profile="psi-sales"))

    invalid_partition = tmp_path / "invalid-partition.parquet"
    column = table.schema.get_field_index("source_partition_year")
    pq.write_table(
        table.set_column(column, table.schema.field(column), pa.array([1989], type=pa.int32())),
        invalid_partition,
    )
    with pytest.raises(ImportProfileError, match="outside its registered range"):
        list(iter_psi_parquet_import(invalid_partition, profile="psi-sales"))


def test_psi_parquet_rejects_empty_and_corrupt_artifacts(tmp_path: Path) -> None:
    empty = tmp_path / "empty.parquet"
    pq.write_table(pa.Table.from_pylist([], schema=psi_parquet_schema()), empty)
    with pytest.raises(ImportProfileError, match="must not be empty"):
        list(iter_psi_parquet_import(empty, profile="psi-sales"))

    corrupt = tmp_path / "corrupt.parquet"
    corrupt.write_bytes(b"not a parquet artifact")
    with pytest.raises(ImportProfileError, match="unreadable"):
        list(iter_psi_parquet_import(corrupt, profile="psi-sales"))


class _StreamStore:
    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []
        self.progress: list[dict[str, Any]] = []

    def update_import_progress(self, _operation_id: uuid.UUID, **values: Any) -> None:
        self.progress.append(values)

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
        assert profile == "psi-sales"
        self.rows = list(rows)
        verify_complete()
        phase_callback("verification", len(self.rows))
        return ImportResult(len(self.rows), len(self.rows), len(self.rows), 0, 1)


def test_loader_routes_verified_psi_parquet_to_the_existing_postgres_import(
    tmp_path: Path,
) -> None:
    generated = tmp_path / "generated.parquet"
    partitions = ((2025, (_sale(),)),)
    write_psi_parquet(generated, partitions)
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
        "import_profile_key": "psi-sales",
        "storage_key": storage_key.as_posix(),
        "artifact_bytes": len(payload),
        "content_sha256": digest,
        "media_type": PSI_PARQUET_MEDIA_TYPE,
        "candidate_release_id": str(uuid.uuid4()),
    }

    counts, evidence = loader._execute(work)

    assert counts == {"rows_in": 1, "rows_staged": 1, "rows_accepted": 1, "rows_rejected": 0}
    assert store.rows == _legacy_rows(partitions)
    assert evidence["staging_method"] == "postgresql-copy"
    staging = [event for event in store.progress if event["phase_key"] == "typed_staging"]
    assert staging and all(event["total_rows"] == 1 for event in staging)
