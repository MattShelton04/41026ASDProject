"""Pure run-planning rules shared by datastore transaction methods."""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from propertyscope_data_store.errors import ConflictError

TERMINAL_RUN_STATES = frozenset({"succeeded", "failed", "cancelled"})
RUN_STAGES = (
    "discover",
    "acquire",
    "validate_artifact",
    "import",
    "normalise",
    "quality",
    "build_release",
)
_CACHED_PREREQUISITE_STAGES = frozenset({"discover", "acquire", "validate_artifact"})
_RUN_STATUS_BY_STAGE = {
    "discover": "discovering",
    "acquire": "acquiring",
    "validate_artifact": "acquiring",
    "import": "staging",
    "normalise": "normalising",
    "quality": "validating",
    "build_release": "building_release",
}


@dataclass(frozen=True, slots=True)
class RunTaskPlan:
    index: int
    stage: str
    logical_key: str
    skipped: bool


def validate_retry_parent(job_id: uuid.UUID, mode: str, parent: Mapping[str, Any]) -> int:
    """Validate retry lineage and return the next attempt number."""
    if str(parent.get("job_definition_id")) != str(job_id):
        raise ConflictError("retry parent belongs to a different job")
    status = parent.get("status")
    if mode == "full_refresh" and status not in {"failed", "cancelled"}:
        raise ConflictError("full pipeline retry requires a failed or cancelled parent")
    if mode == "reprocess_cached" and status not in TERMINAL_RUN_STATES:
        raise ConflictError("cached reprocessing requires a terminal parent")
    return int(parent["attempt_number"]) + 1


def task_plan(mode: str) -> tuple[RunTaskPlan, ...]:
    """Describe the stable pipeline and cached-reprocess skip policy."""
    return tuple(
        RunTaskPlan(
            index=index,
            stage=stage,
            logical_key=f"{index:02d}/{stage}",
            skipped=mode == "reprocess_cached" and stage in _CACHED_PREREQUISITE_STAGES,
        )
        for index, stage in enumerate(RUN_STAGES)
    )


def run_status_for_stage(stage: str) -> str:
    """Project the currently claimed task stage onto the public run lifecycle."""
    return _RUN_STATUS_BY_STAGE.get(stage, "planning")
