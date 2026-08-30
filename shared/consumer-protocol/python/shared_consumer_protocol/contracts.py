"""Closed, domain-neutral contracts for verified publication imports."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import (
    AliasChoices,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from shared_contracts.base import ContractModel
from shared_contracts.http import RequestId, Traceparent

Identifier = Annotated[
    str,
    Field(min_length=1, max_length=200, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$"),
]
Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class ManifestBinding(ContractModel):
    """Security-relevant manifest fields understood by every consumer.

    Producer-owned manifest extensions are retained and may be checked by the caller's
    manifest hook. Only these transport and immutable-identity fields are interpreted here.
    """

    model_config = ConfigDict(extra="allow", frozen=True)

    manifest_schema_version: Identifier
    release_id: Identifier
    dataset_id: Identifier
    target: Identifier = Field(validation_alias=AliasChoices("target", "target_feature"))
    schema_version: Identifier = Field(
        validation_alias=AliasChoices("schema_version", "product_schema_version")
    )
    content_sha256: Sha256
    record_count: int = Field(ge=0)
    byte_count: int = Field(ge=1)
    media_type: Literal["application/x-ndjson"]
    content_encoding: Literal["gzip"]


class PublicationRequest(ContractModel):
    """Producer request binding an artifact path to one immutable release."""

    release_id: Identifier
    dataset_id: Identifier
    schema_version: Identifier
    content_sha256: Sha256
    record_count: int = Field(ge=0)
    manifest: dict[str, Any]
    artifact_path: str = Field(min_length=1, max_length=1_000)
    idempotency_key: str = Field(min_length=1, max_length=200)

    @field_validator("idempotency_key")
    @classmethod
    def safe_idempotency_key(cls, value: str) -> str:
        if any(not 0x21 <= ord(character) <= 0x7E for character in value):
            raise ValueError("idempotency_key must contain visible ASCII header characters")
        return value

    @model_validator(mode="after")
    def manifest_matches_request(self) -> PublicationRequest:
        binding = ManifestBinding.model_validate(self.manifest)
        expected = (
            self.release_id,
            self.dataset_id,
            self.schema_version,
            self.content_sha256,
            self.record_count,
        )
        actual = (
            binding.release_id,
            binding.dataset_id,
            binding.schema_version,
            binding.content_sha256,
            binding.record_count,
        )
        if actual != expected:
            raise ValueError("manifest immutable evidence does not match the publication request")
        return self

    @property
    def manifest_binding(self) -> ManifestBinding:
        return ManifestBinding.model_validate(self.manifest)


class CorrelationContext(ContractModel):
    """Safe correlation values forwarded across the artifact request."""

    request_id: RequestId
    traceparent: Traceparent | None = None


class ReleaseIdentity(ContractModel):
    """Immutable release identity, intentionally separate from delivery operations."""

    release_id: Identifier
    dataset_id: Identifier
    target: Identifier
    schema_version: Identifier
    content_sha256: Sha256
    record_count: int = Field(ge=0)


class ImportEvidence(ReleaseIdentity):
    """Fully verified evidence supplied at the atomic commit boundary."""

    compressed_bytes: int = Field(ge=1)
    uncompressed_bytes: int = Field(ge=0)
    rows_received: int = Field(ge=0)

    @model_validator(mode="after")
    def counts_match(self) -> ImportEvidence:
        if self.rows_received != self.record_count:
            raise ValueError("verified row count must match the immutable release identity")
        return self


class ReceiptError(ContractModel):
    """Safe failure details for a consumer-owned operation."""

    code: Identifier
    message: str = Field(min_length=1, max_length=500)
    retryable: bool = False


class ImportReceipt(ReleaseIdentity):
    """Closed consumer receipt; unknown evidence fields are rejected."""

    consumer_operation_id: Identifier
    status: Literal["accepted", "rejected", "failed"]
    rows_received: int = Field(ge=0)
    rows_accepted: int = Field(ge=0)
    rows_rejected: int = Field(ge=0)
    error: ReceiptError | None = None

    @model_validator(mode="after")
    def coherent_outcome(self) -> ImportReceipt:
        if self.rows_accepted + self.rows_rejected > self.rows_received:
            raise ValueError("accepted and rejected rows cannot exceed rows received")
        if self.status == "accepted":
            if (
                self.error is not None
                or self.rows_received != self.record_count
                or self.rows_accepted != self.record_count
                or self.rows_rejected != 0
            ):
                raise ValueError("an accepted receipt must accept the complete bound release")
        elif self.error is None:
            raise ValueError("a non-accepted receipt requires a safe error")
        return self

    def matches(self, request: PublicationRequest, *, target: str) -> bool:
        """Return whether this receipt is replay-safe for exactly this release evidence."""
        try:
            binding = request.manifest_binding
        except ValidationError:
            return False
        return (
            binding.release_id == request.release_id
            and binding.dataset_id == request.dataset_id
            and binding.target == target
            and binding.schema_version == request.schema_version
            and binding.content_sha256 == request.content_sha256
            and binding.record_count == request.record_count
            and self.release_id == request.release_id
            and self.dataset_id == request.dataset_id
            and self.target == target
            and self.schema_version == request.schema_version
            and self.content_sha256 == request.content_sha256
            and self.record_count == request.record_count
            and self.rows_received == request.record_count
            and self.rows_accepted == request.record_count
            and self.rows_rejected == 0
            and self.status == "accepted"
        )

    def reconciles(
        self,
        request: PublicationRequest,
        *,
        target: str,
        consumer_operation_id: str,
    ) -> bool:
        """Return whether a persisted receipt resolves one uncertain consumer operation."""
        return self.consumer_operation_id == consumer_operation_id and self.matches(
            request, target=target
        )


def immutable_identity(request: PublicationRequest, *, target: str) -> ReleaseIdentity:
    """Build the release identity without deriving any delivery-operation identifier."""
    return ReleaseIdentity(
        release_id=request.release_id,
        dataset_id=request.dataset_id,
        target=target,
        schema_version=request.schema_version,
        content_sha256=request.content_sha256,
        record_count=request.record_count,
    )
