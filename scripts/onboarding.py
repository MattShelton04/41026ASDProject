"""Load the validated, explicitly enabled feature onboarding projection."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from shared_contracts.deployment import (
    DeploymentProjectionV1,
    DeploymentSelectionV1,
    build_deployment_projection,
)
from shared_contracts.feature import FeatureManifestError, load_feature_manifests

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEPLOYMENT_SELECTION_PATH = Path("deployment/features.yaml")


class OnboardingConfigurationError(ValueError):
    """Deployment selection or enabled feature metadata is invalid."""


@dataclass(frozen=True, slots=True)
class FeatureQualityCheck:
    """One enabled feature's isolated test and coverage policy."""

    feature_key: str
    owner: str
    python_test_paths: tuple[str, ...]
    node_test_files: tuple[str, ...]
    coverage_packages: tuple[str, ...]
    coverage_fail_under: int | None


@dataclass(frozen=True, slots=True)
class FeatureQualityInputs:
    """Stable per-feature quality inputs from the enabled deployment projection."""

    features: tuple[FeatureQualityCheck, ...]

    @property
    def python_test_paths(self) -> tuple[str, ...]:
        return tuple(path for feature in self.features for path in feature.python_test_paths)

    @property
    def node_test_files(self) -> tuple[str, ...]:
        return tuple(path for feature in self.features for path in feature.node_test_files)


def discover_feature_manifests(root: Path = REPOSITORY_ROOT) -> tuple[Path, ...]:
    """Discover canonical student-owned manifests without treating fixtures as features."""
    return tuple(
        path
        for path in sorted(root.glob("student-*/feature.yaml"))
        if path.parent.name.removeprefix("student-").isdigit()
    )


def load_enabled_projection(root: Path = REPOSITORY_ROOT) -> DeploymentProjectionV1:
    """Load manifests and the closed root selection into one enabled-only projection."""
    selection_path = root / DEPLOYMENT_SELECTION_PATH
    try:
        payload = yaml.safe_load(selection_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise OnboardingConfigurationError(
            f"could not read deployment selection {selection_path}: {exc}"
        ) from exc
    if not isinstance(payload, dict):
        raise OnboardingConfigurationError(
            f"deployment selection {selection_path} must contain a YAML object"
        )
    try:
        selection = DeploymentSelectionV1.model_validate(payload)
        manifests = load_feature_manifests(discover_feature_manifests(root))
        projection = build_deployment_projection(manifests, selection)
        _validate_enabled_paths(root, projection)
        return projection
    except (FeatureManifestError, ValueError) as exc:
        raise OnboardingConfigurationError(f"invalid feature onboarding projection: {exc}") from exc


def discover_tool_catalogs(root: Path = REPOSITORY_ROOT) -> tuple[Path, ...]:
    """Return existing feature-owned catalogues for explicitly enabled AI features."""
    catalogs: list[Path] = []
    for feature in load_enabled_projection(root).features:
        if feature.ai is None:
            continue
        relative = _owned_path(feature.owner, feature.ai.tool_catalog, kind="tool catalogue")
        path = root / relative
        if not path.is_file():
            raise OnboardingConfigurationError(
                f"enabled feature {feature.feature_key} tool catalogue does not exist: {relative}"
            )
        catalogs.append(path)
    return tuple(sorted(catalogs))


def discover_quality_inputs(root: Path = REPOSITORY_ROOT) -> FeatureQualityInputs:
    """Return existing feature-owned Python and Node checks for enabled features only."""
    checks: list[FeatureQualityCheck] = []
    for feature in load_enabled_projection(root).features:
        python_paths: list[str] = []
        node_files: list[str] = []
        for raw_path in feature.quality.python_test_paths:
            relative = _owned_path(feature.owner, raw_path, kind="Python quality path")
            if not (root / relative).exists():
                raise OnboardingConfigurationError(
                    f"enabled feature {feature.feature_key} Python quality path does not exist: "
                    f"{relative}"
                )
            python_paths.append(relative)
        for raw_path in feature.quality.node_test_files:
            relative = _owned_path(feature.owner, raw_path, kind="Node quality file")
            path = root / relative
            if not path.is_file():
                raise OnboardingConfigurationError(
                    f"enabled feature {feature.feature_key} Node quality file does not exist: "
                    f"{relative}"
                )
            if path.suffix not in {".js", ".mjs", ".cjs"}:
                raise OnboardingConfigurationError(
                    f"enabled feature {feature.feature_key} Node quality file must be JavaScript: "
                    f"{relative}"
                )
            node_files.append(relative)
        if feature.quality.coverage_packages and not python_paths:
            raise OnboardingConfigurationError(
                f"enabled feature {feature.feature_key} declares coverage packages without "
                "Python quality paths"
            )
        for package in feature.quality.coverage_packages:
            if not _feature_owns_python_import(root / feature.owner, package):
                raise OnboardingConfigurationError(
                    f"enabled feature {feature.feature_key} coverage package is not owned by "
                    f"{feature.owner}: {package}"
                )
        checks.append(
            FeatureQualityCheck(
                feature_key=feature.feature_key,
                owner=feature.owner,
                python_test_paths=tuple(sorted(python_paths)),
                node_test_files=tuple(sorted(node_files)),
                coverage_packages=feature.quality.coverage_packages,
                coverage_fail_under=feature.quality.coverage_fail_under,
            )
        )
    return FeatureQualityInputs(features=tuple(checks))


def _owned_path(owner: str, value: str, *, kind: str) -> str:
    path = Path(value)
    relative = path.as_posix()
    if not path.parts or path.parts[0] != owner:
        raise OnboardingConfigurationError(f"{kind} must be owned by {owner}: {value}")
    return relative


def _validate_enabled_paths(root: Path, projection: DeploymentProjectionV1) -> None:
    for feature in projection.features:
        if feature.frontend is not None:
            asset_root = _owned_path(
                feature.owner, feature.frontend.asset_root, kind="frontend asset root"
            )
            if not (root / asset_root).is_dir():
                raise OnboardingConfigurationError(
                    f"enabled feature {feature.feature_key} frontend asset root does not exist: "
                    f"{asset_root}"
                )
            if feature.frontend.route_fragment is not None:
                fragment = _owned_path(
                    feature.owner,
                    feature.frontend.route_fragment,
                    kind="frontend route fragment",
                )
                if not (root / fragment).is_file():
                    raise OnboardingConfigurationError(
                        f"enabled feature {feature.feature_key} route fragment does not exist: "
                        f"{fragment}"
                    )
        if feature.evidence_adapter is not None:
            adapter = _owned_path(
                feature.owner, feature.evidence_adapter.path, kind="evidence adapter"
            )
            if not (root / adapter).is_file():
                raise OnboardingConfigurationError(
                    f"enabled feature {feature.feature_key} evidence adapter does not exist: "
                    f"{adapter}"
                )


def _feature_owns_python_import(feature_root: Path, import_name: str) -> bool:
    package_parts = tuple(import_name.split("."))
    module_parts = (*package_parts[:-1], f"{package_parts[-1]}.py")
    for candidate in feature_root.rglob("__init__.py"):
        relative = candidate.parent.relative_to(feature_root).parts
        if relative[-len(package_parts) :] == package_parts:
            return True
    for candidate in feature_root.rglob(module_parts[-1]):
        relative = candidate.relative_to(feature_root).parts
        if relative[-len(module_parts) :] == module_parts:
            return True
    return False
