"""Validate every checked-in feature tool catalogue without contacting services."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ai_mode.tool_catalog import ToolCatalog, build_tool_runtime, load_tool_catalog
from shared_contracts import FeatureManifest, load_feature_manifests

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.onboarding import (
    OnboardingConfigurationError,
    discover_feature_manifests,
    load_enabled_projection,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def discover_catalogs(root: Path = REPOSITORY_ROOT) -> tuple[Path, ...]:
    """Find only catalogues declared by explicitly enabled features."""
    projection = load_enabled_projection(root)
    return tuple(
        sorted(
            root / feature.ai.tool_catalog
            for feature in projection.features
            if feature.ai is not None
        )
    )


def validate_catalog_ownership(catalog: ToolCatalog, manifest: FeatureManifest) -> None:
    """Bind every tool and endpoint to the feature's declared HTTP ownership."""
    onboarding = manifest.onboarding
    if onboarding is None or onboarding.backend is None or onboarding.ai is None:
        raise ValueError(f"feature {manifest.feature_key} has no complete AI/backend onboarding")
    backend = onboarding.backend
    endpoints = {endpoint.service: endpoint for endpoint in catalog.services}
    referenced_services = {registration.service for registration in catalog.tools}
    if set(endpoints) != referenced_services:
        raise ValueError("tool catalogue services must be used exactly by its HTTP tool bindings")
    for endpoint in catalog.services:
        origin = endpoint.base_url
        if (
            origin.scheme != "http"
            or origin.host != backend.service
            or origin.port != backend.internal_port
            or origin.path not in {"", "/"}
            or origin.query is not None
            or origin.fragment is not None
            or origin.username is not None
            or origin.password is not None
        ):
            raise ValueError(
                "tool service origin must exactly match the manifest backend service and port"
            )
    owned_roots = tuple(
        path.rstrip("/")
        for path in (manifest.backend_base_path, *backend.additional_paths)
    )
    for registration in catalog.tools:
        if registration.definition.feature_key != manifest.feature_key:
            raise ValueError(
                "tool definition feature_key must match its owning feature manifest"
            )
        path = registration.path.rstrip("/")
        if not any(path == root or path.startswith(f"{root}/") for root in owned_roots):
            raise ValueError("tool binding path must stay inside an owned backend route namespace")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate tool catalogues declared by enabled feature onboarding metadata."
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=REPOSITORY_ROOT,
        help="Repository root to inspect (defaults to the current project).",
    )
    return parser


def main() -> int:
    """Load and compose each catalogue so unsafe transport metadata fails CI."""
    arguments = _parser().parse_args()
    try:
        root = arguments.root.resolve()
        projection = load_enabled_projection(root)
        manifests = {
            manifest.feature_key: manifest
            for manifest in load_feature_manifests(discover_feature_manifests(root))
        }
    except OnboardingConfigurationError as exc:
        print(f"Tool catalogue discovery failed: {exc}")
        return 1
    catalogs = []
    for feature in projection.features:
        if feature.ai is None:
            continue
        path = root / feature.ai.tool_catalog
        catalog = load_tool_catalog(path)
        try:
            validate_catalog_ownership(catalog, manifests[feature.feature_key])
        except (KeyError, ValueError) as exc:
            print(f"Tool catalogue ownership validation failed for {path}: {exc}")
            return 1
        _, executor = build_tool_runtime(
            catalog,
            max_request_bytes=1,
            max_response_bytes=1,
        )
        executor.close()
        catalogs.append(path)
    print(f"Validated {len(catalogs)} feature tool catalogue(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
