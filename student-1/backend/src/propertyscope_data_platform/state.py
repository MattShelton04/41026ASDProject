"""Explicit and deterministic lifecycle policies."""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from typing import TypeVar

from .domain import ImportStatus, LifecycleStatus, ReleaseStatus, RunStatus, TaskStatus


class InvalidTransitionError(ValueError):
    """Raised when a caller attempts an unregistered lifecycle transition."""


_LIFECYCLE = {
    LifecycleStatus.DRAFT: frozenset({LifecycleStatus.ACTIVE}),
    LifecycleStatus.ACTIVE: frozenset({LifecycleStatus.DISABLED}),
    LifecycleStatus.DISABLED: frozenset({LifecycleStatus.ACTIVE, LifecycleStatus.RETIRED}),
    LifecycleStatus.RETIRED: frozenset(),
}
_RUN = {
    RunStatus.QUEUED: frozenset({RunStatus.PLANNING, RunStatus.CANCELLED}),
    RunStatus.PLANNING: frozenset(
        {RunStatus.DISCOVERING, RunStatus.FAILED, RunStatus.CANCELLED, RunStatus.INTERRUPTED}
    ),
    RunStatus.DISCOVERING: frozenset(
        {RunStatus.ACQUIRING, RunStatus.FAILED, RunStatus.CANCELLED, RunStatus.INTERRUPTED}
    ),
    RunStatus.ACQUIRING: frozenset(
        {RunStatus.STAGING, RunStatus.FAILED, RunStatus.CANCELLED, RunStatus.INTERRUPTED}
    ),
    RunStatus.STAGING: frozenset(
        {RunStatus.NORMALISING, RunStatus.FAILED, RunStatus.CANCELLED, RunStatus.INTERRUPTED}
    ),
    RunStatus.NORMALISING: frozenset(
        {RunStatus.VALIDATING, RunStatus.FAILED, RunStatus.CANCELLED, RunStatus.INTERRUPTED}
    ),
    RunStatus.VALIDATING: frozenset(
        {RunStatus.BUILDING_RELEASE, RunStatus.FAILED, RunStatus.CANCELLED, RunStatus.INTERRUPTED}
    ),
    RunStatus.BUILDING_RELEASE: frozenset(
        {RunStatus.SUCCEEDED, RunStatus.FAILED, RunStatus.CANCELLED, RunStatus.INTERRUPTED}
    ),
    RunStatus.INTERRUPTED: frozenset({RunStatus.QUEUED, RunStatus.CANCELLED}),
    RunStatus.SUCCEEDED: frozenset(),
    RunStatus.FAILED: frozenset(),
    RunStatus.CANCELLED: frozenset(),
}
_RELEASE = {
    ReleaseStatus.DRAFT: frozenset({ReleaseStatus.CANDIDATE}),
    ReleaseStatus.CANDIDATE: frozenset({ReleaseStatus.AWAITING_REVIEW}),
    ReleaseStatus.AWAITING_REVIEW: frozenset({ReleaseStatus.ACCEPTED, ReleaseStatus.REJECTED}),
    ReleaseStatus.ACCEPTED: frozenset({ReleaseStatus.SUPERSEDED}),
    ReleaseStatus.REJECTED: frozenset(),
    ReleaseStatus.SUPERSEDED: frozenset(),
}
_TASK = {
    TaskStatus.PENDING: frozenset({TaskStatus.CLAIMED, TaskStatus.CANCELLED, TaskStatus.SKIPPED}),
    TaskStatus.CLAIMED: frozenset(
        {TaskStatus.RUNNING, TaskStatus.RETRY_WAIT, TaskStatus.FAILED, TaskStatus.CANCELLED}
    ),
    TaskStatus.RUNNING: frozenset(
        {TaskStatus.SUCCEEDED, TaskStatus.RETRY_WAIT, TaskStatus.FAILED, TaskStatus.CANCELLED}
    ),
    TaskStatus.RETRY_WAIT: frozenset({TaskStatus.PENDING, TaskStatus.FAILED, TaskStatus.CANCELLED}),
    TaskStatus.SUCCEEDED: frozenset(),
    TaskStatus.FAILED: frozenset(),
    TaskStatus.CANCELLED: frozenset(),
    TaskStatus.SKIPPED: frozenset(),
}
_IMPORT = {
    ImportStatus.PLANNED: frozenset({ImportStatus.QUEUED, ImportStatus.CANCELLED}),
    ImportStatus.QUEUED: frozenset({ImportStatus.CLAIMED, ImportStatus.CANCELLED}),
    ImportStatus.CLAIMED: frozenset(
        {
            ImportStatus.RUNNING,
            ImportStatus.INTERRUPTED,
            ImportStatus.FAILED,
            ImportStatus.CANCELLED,
        }
    ),
    ImportStatus.RUNNING: frozenset(
        {
            ImportStatus.SUCCEEDED,
            ImportStatus.INTERRUPTED,
            ImportStatus.FAILED,
            ImportStatus.CANCELLED,
        }
    ),
    ImportStatus.INTERRUPTED: frozenset({ImportStatus.QUEUED, ImportStatus.CANCELLED}),
    ImportStatus.SUCCEEDED: frozenset(),
    ImportStatus.FAILED: frozenset(),
    ImportStatus.CANCELLED: frozenset(),
}


TState = TypeVar("TState", bound=StrEnum)


def _transition(  # noqa: UP047
    current: TState, target: TState, graph: Mapping[TState, frozenset[TState]]
) -> TState:
    if target not in graph[current]:
        raise InvalidTransitionError(f"cannot transition {current.value} to {target.value}")
    return target


def transition_run(current: RunStatus, target: RunStatus) -> RunStatus:
    return _transition(current, target, _RUN)


def transition_release(current: ReleaseStatus, target: ReleaseStatus) -> ReleaseStatus:
    return _transition(current, target, _RELEASE)


def transition_source(current: LifecycleStatus, target: LifecycleStatus) -> LifecycleStatus:
    return _transition(current, target, _LIFECYCLE)


def transition_job(current: LifecycleStatus, target: LifecycleStatus) -> LifecycleStatus:
    return _transition(current, target, _LIFECYCLE)


def transition_task(current: TaskStatus, target: TaskStatus) -> TaskStatus:
    return _transition(current, target, _TASK)


def transition_import(current: ImportStatus, target: ImportStatus) -> ImportStatus:
    return _transition(current, target, _IMPORT)


def allowed_actions(kind: str, status: StrEnum) -> frozenset[str]:
    """Return UI/API actions derived from lifecycle policy, never presentation guesses."""
    policies: dict[str, dict[StrEnum, frozenset[str]]] = {
        "run": {
            **{
                value: frozenset({"cancel"})
                for value in RunStatus
                if _RUN[value] and RunStatus.CANCELLED in _RUN[value]
            },
            RunStatus.INTERRUPTED: frozenset({"resume", "retry", "cancel"}),
            RunStatus.FAILED: frozenset({"retry", "reprocess_cached"}),
            RunStatus.SUCCEEDED: frozenset({"reprocess_cached"}),
        },
        "release": {
            ReleaseStatus.DRAFT: frozenset({"edit", "delete", "promote_candidate"}),
            ReleaseStatus.CANDIDATE: frozenset({"submit_review", "reject"}),
            ReleaseStatus.AWAITING_REVIEW: frozenset({"publish", "reject"}),
            ReleaseStatus.ACCEPTED: frozenset({"supersede"}),
            ReleaseStatus.REJECTED: frozenset({"delete"}),
        },
        "source": {
            LifecycleStatus.DRAFT: frozenset({"edit", "delete", "activate"}),
            LifecycleStatus.ACTIVE: frozenset({"edit", "disable", "retire"}),
            LifecycleStatus.DISABLED: frozenset({"edit", "activate", "retire"}),
        },
        "job": {
            LifecycleStatus.DRAFT: frozenset({"edit", "delete", "activate"}),
            LifecycleStatus.ACTIVE: frozenset({"edit", "disable", "run", "plan", "retire"}),
            LifecycleStatus.DISABLED: frozenset({"edit", "activate", "retire"}),
        },
        "task": {
            TaskStatus.PENDING: frozenset({"claim", "cancel", "skip"}),
            TaskStatus.CLAIMED: frozenset({"start", "fail", "cancel"}),
            TaskStatus.RUNNING: frozenset({"complete", "retry", "fail", "cancel"}),
            TaskStatus.RETRY_WAIT: frozenset({"requeue", "fail", "cancel"}),
        },
        "import": {
            ImportStatus.PLANNED: frozenset({"enqueue", "cancel"}),
            ImportStatus.QUEUED: frozenset({"claim", "cancel"}),
            ImportStatus.CLAIMED: frozenset({"start", "interrupt", "fail", "cancel"}),
            ImportStatus.RUNNING: frozenset(
                {"complete", "heartbeat", "interrupt", "fail", "cancel"}
            ),
            ImportStatus.INTERRUPTED: frozenset({"enqueue", "cancel"}),
        },
    }
    if kind not in policies:
        raise ValueError(f"unknown lifecycle kind: {kind}")
    return policies[kind].get(status, frozenset())


# Compatibility alias kept for callers that imported the first public name.
InvalidTransition = InvalidTransitionError
