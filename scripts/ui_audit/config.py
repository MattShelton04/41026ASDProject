"""Load, validate, select, and shard the executable UI audit matrix."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from scripts.ui_audit.models import AuditBatch, AuditCase, Gate, RouteDefinition, Viewport
from scripts.ui_fixtures import (
    AGENT_RUN_ID,
    DATASET_ID,
    JOB_ID,
    PROPERTY_ID,
    RELEASE_ID,
    RUN_ID,
    SOURCE_ID,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = REPOSITORY_ROOT / "docs" / "ui" / "feature-1-audit-config.json"
PATH_VALUES = {
    "{property_ref}": PROPERTY_ID,
    "{source_id}": SOURCE_ID,
    "{job_id}": JOB_ID,
    "{run_id}": RUN_ID,
    "{release_id}": RELEASE_ID,
    "{dataset_id}": DATASET_ID,
    "{agent_run_id}": AGENT_RUN_ID,
}


class AuditConfigError(ValueError):
    """Raised when the route/state matrix cannot be executed honestly."""


@dataclass(frozen=True)
class AuditConfig:
    """Validated executable audit configuration."""

    path: Path
    digest: str
    schema_version: int
    scenarios: tuple[str, ...]
    viewports: tuple[Viewport, ...]
    routes: tuple[RouteDefinition, ...]
    destructive_labels: tuple[str, ...]


@dataclass(frozen=True)
class AuditSelection:
    """Optional selectors and stable shard coordinates."""

    workspaces: tuple[str, ...] = ()
    route_groups: tuple[str, ...] = ()
    routes: tuple[str, ...] = ()
    scenarios: tuple[str, ...] = ()
    viewports: tuple[str, ...] = ()
    shard_index: int = 0
    shard_total: int = 1


def _mapping(value: object, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise AuditConfigError(f"{name} must be an object")
    return cast(dict[str, Any], value)


def _sequence(value: object, name: str) -> list[Any]:
    if not isinstance(value, list):
        raise AuditConfigError(f"{name} must be an array")
    return value


def _text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AuditConfigError(f"{name} must be a non-empty string")
    return value


def _texts(value: object, name: str) -> tuple[str, ...]:
    return tuple(_text(item, name) for item in _sequence(value, name))


def load_config(path: Path = DEFAULT_CONFIG_PATH) -> AuditConfig:
    """Load the baseline matrix and require explicit case/defer accounting per route."""
    raw_text = path.read_text(encoding="utf-8")
    raw = _mapping(json.loads(raw_text), "audit config")
    scenarios = _texts(_mapping(raw.get("fixtureMode"), "fixtureMode").get("scenarios"), "scenario")
    viewport_rows = _sequence(raw.get("viewports"), "viewports")
    viewports: list[Viewport] = []
    for index, value in enumerate(viewport_rows):
        row = _mapping(value, f"viewports[{index}]")
        gate = _text(row.get("gate"), "viewport gate")
        if gate not in {
            "release-critical-full-matrix",
            "required-capture-bounded-resilience",
        }:
            raise AuditConfigError(f"unsupported viewport gate: {gate}")
        width, height = row.get("width"), row.get("height")
        if not isinstance(width, int) or not isinstance(height, int) or width < 1 or height < 1:
            raise AuditConfigError("viewport dimensions must be positive integers")
        viewports.append(
            Viewport(
                id=_text(row.get("id"), "viewport id"),
                width=width,
                height=height,
                gate=cast(Gate, gate),
            )
        )

    execution = _mapping(raw.get("auditExecution"), "auditExecution")
    case_file = execution.get("caseFile")
    templates: dict[str, Any] = {}
    if isinstance(case_file, str):
        case_path = (REPOSITORY_ROOT / case_file).resolve()
        try:
            case_path.relative_to(REPOSITORY_ROOT)
        except ValueError as exc:
            raise AuditConfigError("audit case file must stay inside the repository") from exc
        case_text = case_path.read_text(encoding="utf-8")
        case_document = _mapping(json.loads(case_text), "audit case file")
        templates = _mapping(case_document.get("templates", {}), "audit case templates")
        route_execution = _mapping(case_document.get("routes"), "audit case routes")
        config_digest = hashlib.sha256(f"{raw_text}\n{case_text}".encode()).hexdigest()
    else:
        route_execution = _mapping(execution.get("routes"), "auditExecution.routes")
        config_digest = hashlib.sha256(raw_text.encode()).hexdigest()
    routes: list[RouteDefinition] = []
    known_route_ids: set[str] = set()
    for group_index, group_value in enumerate(_sequence(raw.get("routeGroups"), "routeGroups")):
        group = _mapping(group_value, f"routeGroups[{group_index}]")
        group_id = _text(group.get("id"), "route group id")
        workspace = _text(group.get("workspace"), "workspace")
        for route_index, route_value in enumerate(_sequence(group.get("routes"), "routes")):
            route = _mapping(route_value, f"routes[{route_index}]")
            route_id = _text(route.get("id"), "route id")
            if route_id in known_route_ids:
                raise AuditConfigError(f"duplicate route id: {route_id}")
            known_route_ids.add(route_id)
            required_states = set(_texts(route.get("requiredStates"), "requiredStates"))
            execution_row = _mapping(
                route_execution.get(route_id), f"auditExecution.routes.{route_id}"
            )
            cases: list[AuditCase] = []
            covered: set[str] = set()
            for case_index, case_value in enumerate(
                _sequence(execution_row.get("cases"), f"{route_id}.cases")
            ):
                if isinstance(case_value, str):
                    case = dict(
                        _mapping(templates.get(case_value), f"case template {case_value!r}")
                    )
                    case.setdefault("id", case_value)
                else:
                    case = _mapping(case_value, f"{route_id}.cases[{case_index}]")
                case_scenario = _text(case.get("scenario"), "case scenario")
                if case_scenario not in scenarios:
                    raise AuditConfigError(
                        f"{route_id} case uses unknown fixture scenario {case_scenario!r}"
                    )
                states = _texts(case.get("states"), "case states")
                covered.update(states)
                settle_ms = case.get("settleMs", execution_row.get("settleMs", 650))
                if not isinstance(settle_ms, int) or settle_ms < 0 or settle_ms > 10_000:
                    raise AuditConfigError(f"{route_id} case settleMs is invalid")
                capture_phase = case.get("capturePhase", "settled")
                if capture_phase not in {"settled", "loading", "loading-and-settled"}:
                    raise AuditConfigError(f"{route_id} case has invalid capturePhase")
                route_readiness = str(execution_row.get("readiness", "body"))
                cases.append(
                    AuditCase(
                        id=_text(case.get("id"), "case id"),
                        scenario=case_scenario,
                        states=states,
                        path=(
                            _resolve_path(_text(case["path"], "case path"))
                            if case.get("path") is not None
                            else None
                        ),
                        settle_ms=settle_ms,
                        quick=case.get("quick") is True,
                        expected_request_failures=tuple(
                            str(item)
                            for item in case.get("expectedRequestFailures", [])
                            if isinstance(item, str)
                        ),
                        capture_phase=cast(Any, capture_phase),
                        readiness=str(case.get("readiness", route_readiness)),
                        settled_readiness=str(case.get("settledReadiness", route_readiness)),
                        overrides=tuple(
                            _mapping(item, "case override") for item in case.get("overrides", [])
                        ),
                        setup=tuple(_mapping(item, "case setup") for item in case.get("setup", [])),
                    )
                )
            if not cases:
                raise AuditConfigError(f"{route_id} must define at least one executable case")
            deferred_raw = _mapping(execution_row.get("deferredStates", {}), "deferredStates")
            deferred = {
                _text(state, "deferred state"): _text(reason, "defer reason")
                for state, reason in deferred_raw.items()
            }
            accounted = covered | set(deferred)
            if missing := required_states - accounted:
                raise AuditConfigError(
                    f"{route_id} has unaccounted required states: {', '.join(sorted(missing))}"
                )
            if unknown := accounted - required_states:
                raise AuditConfigError(
                    f"{route_id} accounts for unconfigured states: {', '.join(sorted(unknown))}"
                )
            routes.append(
                RouteDefinition(
                    id=route_id,
                    workspace=workspace,
                    route_group=group_id,
                    path=_resolve_path(_text(route.get("path"), "route path")),
                    cases=tuple(cases),
                    deferred_states=deferred,
                    configured_interactions=tuple(
                        str(item) for item in route.get("interactions", []) if isinstance(item, str)
                    ),
                )
            )
    extra_routes = set(route_execution) - known_route_ids
    if extra_routes:
        raise AuditConfigError(
            f"auditExecution defines unknown routes: {', '.join(sorted(extra_routes))}"
        )
    return AuditConfig(
        path=path,
        digest=config_digest,
        schema_version=int(raw.get("schemaVersion", 0)),
        scenarios=scenarios,
        viewports=tuple(viewports),
        routes=tuple(routes),
        destructive_labels=tuple(
            str(item).lower()
            for item in execution.get("destructiveLabels", [])
            if isinstance(item, str)
        ),
    )


def compile_batches(
    config: AuditConfig,
    *,
    profile: str,
    selection: AuditSelection | None = None,
    source_digest: str = "working-tree",
) -> tuple[AuditBatch, ...]:
    """Compile a deterministic selected/sharded batch list."""
    selection = selection or AuditSelection()
    if profile not in {"quick", "full"}:
        raise AuditConfigError("profile must be quick or full")
    if selection.shard_total < 1 or not 0 <= selection.shard_index < selection.shard_total:
        raise AuditConfigError("shard index must be within the positive shard total")
    rows: list[AuditBatch] = []
    for route in config.routes:
        if selection.workspaces and route.workspace not in selection.workspaces:
            continue
        if selection.route_groups and route.route_group not in selection.route_groups:
            continue
        if selection.routes and route.id not in selection.routes:
            continue
        for case in route.cases:
            if profile == "quick" and not case.quick:
                continue
            if selection.scenarios and case.scenario not in selection.scenarios:
                continue
            for viewport in config.viewports:
                if profile == "quick" and viewport.id not in {"laptop-wide", "mobile"}:
                    continue
                if selection.viewports and viewport.id not in selection.viewports:
                    continue
                key = "/".join((route.workspace, route.route_group, route.id, case.id, viewport.id))
                digest = hashlib.sha256(key.encode()).hexdigest()
                if int(digest, 16) % selection.shard_total != selection.shard_index:
                    continue
                fingerprint = hashlib.sha256(
                    f"{key}:{config.digest}:{source_digest}".encode()
                ).hexdigest()
                rows.append(
                    AuditBatch(
                        id=_artifact_id(key, digest),
                        workspace=route.workspace,
                        route_group=route.route_group,
                        route_id=route.id,
                        path=case.path or route.path,
                        case=case,
                        viewport=viewport,
                        fingerprint=fingerprint,
                    )
                )
    return tuple(sorted(rows, key=lambda item: item.id))


def _artifact_id(key: str, digest: str) -> str:
    """Build a Windows-safe, traversal-proof, collision-resistant artifact name."""
    readable = re.sub(r"[^A-Za-z0-9_-]+", "-", key).strip("-")[:120]
    return f"{readable or 'batch'}--{digest[:16]}"


def _resolve_path(path: str) -> str:
    for placeholder, value in PATH_VALUES.items():
        path = path.replace(placeholder, value)
    if "{" in path or "}" in path:
        raise AuditConfigError(f"audit path contains an unresolved placeholder: {path}")
    return path
