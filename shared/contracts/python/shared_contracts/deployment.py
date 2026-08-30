"""Domain-neutral feature onboarding and deployment projections."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Literal

from pydantic import Field, field_validator, model_validator

from shared_contracts.agent import Identifier
from shared_contracts.base import ContractModel
from shared_contracts.http import HealthStatus

if TYPE_CHECKING:
    from shared_contracts.feature import FeatureManifest


class FrontendOnboarding(ContractModel):
    """Feature-owned frontend assets and their edge service projection."""

    asset_root: str = Field(min_length=1, max_length=300)
    service: Identifier
    internal_port: int = Field(ge=1, le=65535)
    host_port_variable: str = Field(pattern=r"^[A-Z][A-Z0-9_]*$", max_length=100)
    host_port_default: int = Field(ge=1, le=65535)
    route_fragment: str | None = Field(default=None, min_length=1, max_length=300)

    @field_validator("asset_root", "route_fragment")
    @classmethod
    def validate_repository_paths(cls, value: str | None) -> str | None:
        if value is not None:
            _validate_repository_path(value)
        return value


class BackendOnboarding(ContractModel):
    """Backend service that owns the feature's declared API route."""

    service: Identifier
    internal_port: int = Field(ge=1, le=65535)
    additional_paths: tuple[str, ...] = Field(default=(), max_length=20)

    @field_validator("additional_paths")
    @classmethod
    def validate_additional_paths(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(values) != len(set(values)):
            raise ValueError("additional backend paths must not contain duplicates")
        for value in values:
            _validate_absolute_path("additional_paths", value)
        return values


class AiOnboarding(ContractModel):
    """Feature-owned tool catalogue source and fixed AI-mode runtime mount path."""

    tool_catalog: str = Field(min_length=1, max_length=300)
    runtime_path: str = Field(min_length=2, max_length=300)

    @field_validator("tool_catalog")
    @classmethod
    def validate_catalog_path(cls, value: str) -> str:
        _validate_repository_path(value)
        return value

    @field_validator("runtime_path")
    @classmethod
    def validate_runtime_path(cls, value: str) -> str:
        _validate_absolute_path("runtime_path", value)
        return value


class QualityOnboarding(ContractModel):
    """Feature-owned test inputs discovered by the repository quality gate."""

    python_test_paths: tuple[str, ...] = Field(default=(), max_length=100)
    node_test_files: tuple[str, ...] = Field(default=(), max_length=100)
    coverage_packages: tuple[str, ...] = Field(default=(), max_length=100)
    coverage_fail_under: int | None = Field(default=None, ge=0, le=100)

    @field_validator("python_test_paths", "node_test_files")
    @classmethod
    def validate_quality_paths(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(values) != len(set(values)):
            raise ValueError("quality paths must not contain duplicates")
        for value in values:
            _validate_repository_path(value)
        return values

    @field_validator("coverage_packages")
    @classmethod
    def validate_coverage_packages(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(values) != len(set(values)):
            raise ValueError("coverage packages must not contain duplicates")
        if any(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.]*", value) is None for value in values):
            raise ValueError("coverage packages must be Python import names")
        return values

    @model_validator(mode="after")
    def validate_coverage_policy(self) -> QualityOnboarding:
        if self.coverage_fail_under is not None and not self.coverage_packages:
            raise ValueError("coverage_fail_under requires at least one coverage package")
        return self


class DatabaseOnboarding(ContractModel):
    """One database service and the named volumes it exclusively owns."""

    database_service: Identifier
    volumes: tuple[Identifier, ...] = Field(min_length=1, max_length=20)

    @field_validator("volumes")
    @classmethod
    def validate_volumes(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(values) != len(set(values)):
            raise ValueError("database volumes must not contain duplicates")
        return values


class EvidenceAdapterOnboarding(ContractModel):
    """Optional feature-owned executable that returns its own evidence object."""

    path: str = Field(min_length=1, max_length=300)

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        _validate_repository_path(value)
        return value


class FeatureOnboarding(ContractModel):
    """Optional deployment metadata owned beside a feature manifest."""

    frontend: FrontendOnboarding | None = None
    backend: BackendOnboarding | None = None
    ai: AiOnboarding | None = None
    quality: QualityOnboarding = QualityOnboarding()
    databases: tuple[DatabaseOnboarding, ...] = Field(default=(), max_length=20)
    evidence_adapter: EvidenceAdapterOnboarding | None = None

    @model_validator(mode="after")
    def validate_database_owners(self) -> FeatureOnboarding:
        services = [database.database_service for database in self.databases]
        if len(services) != len(set(services)):
            raise ValueError("a database service must be declared at most once per feature")
        return self


class FeatureEnablement(ContractModel):
    """Explicit operator choice to enable or disable one discovered feature."""

    feature_key: Identifier
    enabled: bool


class DeploymentSelectionV1(ContractModel):
    """Closed deployment selection; omitted features are disabled."""

    schema_version: Literal[1] = 1
    features: tuple[FeatureEnablement, ...] = ()

    @model_validator(mode="after")
    def validate_unique_features(self) -> DeploymentSelectionV1:
        keys = [feature.feature_key for feature in self.features]
        if len(keys) != len(set(keys)):
            raise ValueError("deployment selection contains a duplicate feature_key")
        return self


class DeploymentRoute(ContractModel):
    """One same-origin edge path bound to a declared service."""

    kind: Literal["frontend", "backend"]
    path: str = Field(min_length=2, max_length=200)
    service: Identifier

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        _validate_absolute_path("path", value)
        return value


class EnabledFeatureProjection(ContractModel):
    """Deployment-safe projection for one explicitly enabled feature."""

    feature_key: Identifier
    owner: Identifier
    enabled: Literal[True] = True
    routes: tuple[DeploymentRoute, ...]
    ai: AiOnboarding | None = None
    frontend: FrontendOnboarding | None = None
    quality: QualityOnboarding
    databases: tuple[DatabaseOnboarding, ...]
    evidence_adapter: EvidenceAdapterOnboarding | None = None
    health_path: str = Field(min_length=2, max_length=200)

    @field_validator("health_path")
    @classmethod
    def validate_health_path(cls, value: str) -> str:
        _validate_absolute_path("health_path", value)
        return value


class DeploymentProjectionV1(ContractModel):
    """Deterministic projection consumed by deployment and quality tooling."""

    schema_version: Literal[1] = 1
    features: tuple[EnabledFeatureProjection, ...]

    @model_validator(mode="after")
    def validate_global_ownership(self) -> DeploymentProjectionV1:
        _reject_projection_duplicates(self.features)
        if tuple(sorted(self.features, key=lambda item: item.feature_key)) != self.features:
            raise ValueError("deployment features must be ordered by feature_key")
        return self


class ReadinessCheckProjection(ContractModel):
    """One required or optional process/readiness dependency."""

    required: bool
    status: HealthStatus
    detail: str | None = Field(default=None, max_length=500)


class TypedHealthProjection(ContractModel):
    """Health body and HTTP status with explicit optional-degradation semantics."""

    schema_version: Literal[1] = 1
    service: str = Field(min_length=1, max_length=100)
    version: str = Field(min_length=1, max_length=50)
    status: HealthStatus
    http_status: Literal[200, 503]
    media_type: Literal["application/json"] = "application/json"
    checks: dict[str, ReadinessCheckProjection] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_projection(self) -> TypedHealthProjection:
        expected_status, expected_http_status = _project_health_state(self.checks.values())
        if self.status != expected_status or self.http_status != expected_http_status:
            raise ValueError("health status/body projection is inconsistent with its checks")
        return self


def build_deployment_projection(
    manifests: Iterable[FeatureManifest], selection: DeploymentSelectionV1
) -> DeploymentProjectionV1:
    """Project only explicitly enabled feature manifests in stable key order."""
    manifest_by_key: dict[str, FeatureManifest] = {}
    for manifest in manifests:
        if manifest.feature_key in manifest_by_key:
            raise ValueError(f"duplicate feature manifest: {manifest.feature_key}")
        manifest_by_key[manifest.feature_key] = manifest

    enabled: list[EnabledFeatureProjection] = []
    for selected in selection.features:
        selected_manifest = manifest_by_key.get(selected.feature_key)
        if selected_manifest is None:
            raise ValueError(
                f"deployment selection references an unknown feature: {selected.feature_key}"
            )
        if not selected.enabled:
            continue
        if selected_manifest.onboarding is None:
            raise ValueError(
                f"enabled feature has no onboarding declaration: {selected.feature_key}"
            )
        onboarding = selected_manifest.onboarding
        routes: list[DeploymentRoute] = []
        if onboarding.frontend is not None:
            routes.append(
                DeploymentRoute(
                    kind="frontend",
                    path=selected_manifest.frontend_base_path,
                    service=onboarding.frontend.service,
                )
            )
        if onboarding.backend is not None:
            routes.append(
                DeploymentRoute(
                    kind="backend",
                    path=selected_manifest.backend_base_path,
                    service=onboarding.backend.service,
                )
            )
        enabled.append(
            EnabledFeatureProjection(
                feature_key=selected_manifest.feature_key,
                owner=selected_manifest.owner,
                routes=tuple(routes),
                ai=onboarding.ai,
                frontend=onboarding.frontend,
                quality=onboarding.quality,
                databases=onboarding.databases,
                evidence_adapter=onboarding.evidence_adapter,
                health_path=selected_manifest.health_path,
            )
        )
    return DeploymentProjectionV1(
        features=tuple(sorted(enabled, key=lambda item: item.feature_key))
    )


def project_readiness(
    *,
    service: str,
    version: str,
    checks: Mapping[str, ReadinessCheckProjection],
) -> TypedHealthProjection:
    """Derive a truthful response: optional failures degrade but do not return 503."""
    status, http_status = _project_health_state(checks.values())
    return TypedHealthProjection(
        service=service,
        version=version,
        status=status,
        http_status=http_status,
        checks=dict(checks),
    )


def _project_health_state(
    checks: Iterable[ReadinessCheckProjection],
) -> tuple[HealthStatus, Literal[200, 503]]:
    values = tuple(checks)
    if any(check.required and check.status == HealthStatus.UNHEALTHY for check in values):
        return HealthStatus.UNHEALTHY, 503
    if any(check.status != HealthStatus.HEALTHY for check in values):
        return HealthStatus.DEGRADED, 200
    return HealthStatus.HEALTHY, 200


def _reject_projection_duplicates(features: Iterable[EnabledFeatureProjection]) -> None:
    seen: dict[tuple[str, str], str] = {}
    for feature in features:
        values: list[tuple[str, str]] = [("route", route.path) for route in feature.routes]
        if feature.ai is not None:
            values.append(("ai_runtime_path", feature.ai.runtime_path))
        for database in feature.databases:
            values.append(("database_service", database.database_service))
            values.extend(("volume", volume) for volume in database.volumes)
        for kind, value in values:
            key = (kind, value)
            if key in seen:
                raise ValueError(
                    f"duplicate {kind} {value!r} in {seen[key]} and {feature.feature_key}"
                )
            seen[key] = feature.feature_key


def _validate_repository_path(value: str) -> None:
    path = PurePosixPath(value)
    if value.startswith(("/", "\\")) or "\\" in value:
        raise ValueError("repository paths must be relative POSIX paths")
    if any(character in value for character in ("?", "#")) or ".." in path.parts:
        raise ValueError("repository paths cannot traverse or contain query/fragment data")
    if str(path) in {"", "."}:
        raise ValueError("repository paths must identify a file or directory")


def _validate_absolute_path(field_name: str, value: str) -> None:
    if not value.startswith("/") or value.startswith("//"):
        raise ValueError(f"{field_name} must be an absolute POSIX path")
    if any(character in value for character in ("?", "#", "\\")):
        raise ValueError(f"{field_name} cannot contain a query, fragment, or backslash")
    if ".." in PurePosixPath(value).parts:
        raise ValueError(f"{field_name} cannot traverse parent paths")
