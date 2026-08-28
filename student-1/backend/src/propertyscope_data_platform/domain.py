"""Validated, persistence-neutral domain contracts for PropertyScope Feature 1."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import (
    AnyHttpUrl,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

Identifier = Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9._-]*$", max_length=100)]
Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
SafeText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]


class DomainModel(BaseModel):
    """Strict base used at every Feature 1 service boundary."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class LifecycleStatus(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    DISABLED = "disabled"
    RETIRED = "retired"


class RunMode(StrEnum):
    FULL_REFRESH = "full_refresh"
    REPROCESS_CACHED = "reprocess_cached"


class RefreshStrategy(StrEnum):
    FULL_SNAPSHOT = "full_snapshot"
    APPEND_ONLY_PARTITIONED = "append_only_partitioned"
    PARTITIONED_SNAPSHOT = "partitioned_snapshot"
    MANUAL_VERSIONED_IMPORT = "manual_versioned_import"


class RunStatus(StrEnum):
    QUEUED = "queued"
    PLANNING = "planning"
    DISCOVERING = "discovering"
    ACQUIRING = "acquiring"
    STAGING = "staging"
    NORMALISING = "normalising"
    VALIDATING = "validating"
    BUILDING_RELEASE = "building_release"
    INTERRUPTED = "interrupted"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskStatus(StrEnum):
    PENDING = "pending"
    CLAIMED = "claimed"
    RUNNING = "running"
    RETRY_WAIT = "retry_wait"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    SKIPPED = "skipped"


class ImportStatus(StrEnum):
    PLANNED = "planned"
    QUEUED = "queued"
    CLAIMED = "claimed"
    RUNNING = "running"
    INTERRUPTED = "interrupted"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ReleaseStatus(StrEnum):
    DRAFT = "draft"
    CANDIDATE = "candidate"
    AWAITING_REVIEW = "awaiting_review"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"


class QualityStatus(StrEnum):
    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"
    SKIPPED_WITH_REASON = "skipped_with_reason"


class SourceDefinitionCreate(DomainModel):
    name: SafeText
    publisher: SafeText
    source_url: AnyHttpUrl
    adapter_key: Identifier
    cadence: SafeText
    licence_id: Identifier
    licence_url: AnyHttpUrl
    redistribution_policy: Identifier
    target_features: tuple[Identifier, ...] = Field(min_length=1, max_length=5)
    status: LifecycleStatus = LifecycleStatus.DRAFT
    notes: str = Field(default="", max_length=2_000)

    @field_validator("target_features")
    @classmethod
    def unique_targets(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(value)) != len(value):
            raise ValueError("target_features must be unique")
        return value


class SourceDefinitionUpdate(SourceDefinitionCreate):
    version: int = Field(ge=1)


class VersionedKey(DomainModel):
    key: Identifier
    version: str = Field(pattern=r"^\d+\.\d+\.\d+$", max_length=30)


class TargetContract(DomainModel):
    feature: Identifier
    contract: Identifier


class JobDefinitionCreate(DomainModel):
    source_definition_id: UUID
    name: SafeText
    profile_key: Identifier
    profile_version: str = Field(min_length=1, max_length=30)
    adapter: VersionedKey
    release_builder: VersionedKey
    import_profile: VersionedKey
    target: TargetContract
    refresh_strategy: RefreshStrategy
    supported_modes: tuple[RunMode, ...] = Field(min_length=1, max_length=2)
    default_run_mode: RunMode = RunMode.FULL_REFRESH
    quality_policy: Identifier
    status: LifecycleStatus = LifecycleStatus.DRAFT
    schedule_text: str | None = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def validate_modes(self) -> JobDefinitionCreate:
        if len(set(self.supported_modes)) != len(self.supported_modes):
            raise ValueError("supported_modes must be unique")
        if self.default_run_mode not in self.supported_modes:
            raise ValueError("default_run_mode must be supported")
        return self


class JobDefinitionUpdate(JobDefinitionCreate):
    version: int = Field(ge=1)


class RunRequest(DomainModel):
    mode: RunMode
    scope_profile: Identifier
    scope: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str = Field(min_length=8, max_length=200)
    force_reacquire: bool = False

    @model_validator(mode="after")
    def bound_scope(self) -> RunRequest:
        if len(self.scope) > 20:
            raise ValueError("scope cannot contain more than 20 fields")
        if self.mode is RunMode.REPROCESS_CACHED and self.force_reacquire:
            raise ValueError("reprocess_cached cannot force reacquisition")
        return self


class PlannedTask(DomainModel):
    logical_key: str = Field(min_length=1, max_length=300)
    stage: Identifier
    partition: dict[str, Any] = Field(default_factory=dict)


class RunPlan(DomainModel):
    job_id: UUID
    mode: RunMode
    resolved_scope: dict[str, Any]
    tasks: tuple[PlannedTask, ...] = Field(max_length=100_000)
    requires_confirmation: bool = False
    warnings: tuple[str, ...] = Field(default=(), max_length=50)

    @field_validator("tasks")
    @classmethod
    def stable_unique_tasks(cls, value: tuple[PlannedTask, ...]) -> tuple[PlannedTask, ...]:
        keys = [(task.stage, task.logical_key) for task in value]
        if len(keys) != len(set(keys)):
            raise ValueError("planned task stage/logical_key pairs must be unique")
        if keys != sorted(keys):
            raise ValueError("planned tasks must be deterministically sorted")
        return value


class ReleaseCreate(DomainModel):
    dataset_id: Identifier
    source_definition_id: UUID
    ingestion_run_id: UUID
    target_feature: Identifier
    release_version: str = Field(min_length=1, max_length=100)
    schema_version: Identifier
    coverage: dict[str, Any]
    record_count: int = Field(ge=0)
    content_sha256: Sha256
    artifact_record_id: UUID
    manifest: dict[str, Any]
    status: Literal[ReleaseStatus.DRAFT] = ReleaseStatus.DRAFT


class ReleaseUpdate(DomainModel):
    dataset_id: Identifier
    source_definition_id: UUID
    ingestion_run_id: UUID
    target_feature: Identifier
    release_version: str = Field(min_length=1, max_length=100)
    schema_version: Identifier
    coverage: dict[str, Any]
    record_count: int = Field(ge=0)
    content_sha256: Sha256
    artifact_record_id: UUID
    manifest: dict[str, Any]
    version: int = Field(ge=1)
    status: ReleaseStatus
    review_comment: str | None = Field(default=None, max_length=2_000)


class SafeError(DomainModel):
    code: Identifier
    message: str = Field(min_length=1, max_length=500)
    retryable: bool = False
    details: dict[str, Any] = Field(default_factory=dict)


class ConsumerPublicationRequest(DomainModel):
    release_id: UUID
    dataset_id: Identifier
    schema_version: Identifier
    content_sha256: Sha256
    record_count: int = Field(ge=0)
    manifest: dict[str, Any]
    artifact_path: str = Field(
        pattern=r"^/api/data-platform/v1/dataset-releases/[0-9a-f-]+/artifact$"
    )
    idempotency_key: str = Field(min_length=8, max_length=200)


class PublicationReceiptResult(DomainModel):
    consumer_operation_id: str = Field(min_length=1, max_length=200)
    status: Literal["accepted", "rejected", "failed"]
    schema_version: Identifier
    content_sha256: Sha256
    rows_received: int = Field(ge=0)
    rows_accepted: int = Field(ge=0)
    rows_rejected: int = Field(ge=0)
    error: SafeError | None = None

    @model_validator(mode="after")
    def coherent_counts_and_error(self) -> PublicationReceiptResult:
        if self.rows_accepted + self.rows_rejected > self.rows_received:
            raise ValueError("receipt accepted/rejected counts cannot exceed rows received")
        if self.status == "accepted" and (
            self.error is not None or self.rows_accepted != self.rows_received
        ):
            raise ValueError("accepted receipt must accept every received row without an error")
        if self.status != "accepted" and self.error is None:
            raise ValueError("non-accepted receipt requires a safe error")
        return self


class WorkerClaimRequest(DomainModel):
    worker_id: Identifier
    lease_seconds: int = Field(ge=10, le=900)
    compatible_stages: tuple[Identifier, ...] = Field(min_length=1, max_length=20)
    request_id: str = Field(min_length=1, max_length=100)


class WorkerClaim(DomainModel):
    task_id: UUID
    run_id: UUID
    worker_id: Identifier
    lease_token: str = Field(min_length=16, max_length=200)
    lease_expires_at: datetime
    task_version: int = Field(ge=1)
    logical_key: str
    stage: Identifier
    partition: dict[str, Any]

    @field_validator("lease_expires_at")
    @classmethod
    def aware_expiry(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("lease_expires_at must be timezone-aware")
        return value


class WorkerHeartbeat(DomainModel):
    worker_id: Identifier
    lease_token: str = Field(min_length=16, max_length=200)
    task_version: int = Field(ge=1)
    progress: int = Field(default=0, ge=0, le=100)
    request_id: str = Field(min_length=1, max_length=100)


class WorkerComplete(DomainModel):
    worker_id: Identifier
    lease_token: str = Field(min_length=16, max_length=200)
    task_version: int = Field(ge=1)
    rows_in: int = Field(ge=0)
    rows_out: int = Field(ge=0)
    output_artifact_id: UUID | None = None
    checkpoint: dict[str, Any] | None = None
    request_id: str = Field(min_length=1, max_length=100)
    idempotency_key: str = Field(min_length=8, max_length=200)


class WorkerFail(DomainModel):
    worker_id: Identifier
    lease_token: str = Field(min_length=16, max_length=200)
    task_version: int = Field(ge=1)
    error: SafeError
    retry_recommended: bool
    request_id: str = Field(min_length=1, max_length=100)
    idempotency_key: str = Field(min_length=8, max_length=200)


class Coordinates(DomainModel):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)


class MatchEvidence(DomainModel):
    tier: Literal["exact", "alias", "candidate", "ambiguous", "unmatched"]
    source: Identifier
    source_release: str = Field(min_length=1, max_length=100)
    confidence: float = Field(ge=0, le=1)
    explanation: str = Field(min_length=1, max_length=500)


class CoverageEvidence(DomainModel):
    dataset_id: Identifier
    target_feature: Identifier
    state: Literal["accepted", "partial", "stale", "unavailable", "unsupported"]
    release_id: str | None = Field(default=None, max_length=100)
    limitation: str | None = Field(default=None, max_length=500)


class PropertyResponse(DomainModel):
    property_ref: UUID
    display_address: str = Field(min_length=1, max_length=500)
    locality: str = Field(min_length=1, max_length=100)
    state: Literal["NSW"] = "NSW"
    postcode: str = Field(pattern=r"^\d{4}$")
    coordinates: Coordinates | None
    match: MatchEvidence
    coverage: tuple[CoverageEvidence, ...] = Field(default=(), max_length=20)
    observed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
