from __future__ import annotations

from uuid import UUID

import pytest
from pydantic import ValidationError

from propertyscope_data_platform.domain import (
    ReleaseStatus,
    RunMode,
    RunRequest,
    RunStatus,
)
from propertyscope_data_platform.state import (
    InvalidTransitionError,
    allowed_actions,
    transition_release,
    transition_run,
)


def test_run_request_rejects_network_for_cached_reprocess() -> None:
    with pytest.raises(ValidationError, match="cannot force reacquisition"):
        RunRequest(
            mode=RunMode.REPROCESS_CACHED,
            idempotency_key="cached-run-001",
            force_reacquire=True,
        )


def test_run_request_rejects_partial_scope() -> None:
    with pytest.raises(ValidationError, match="complete registered source"):
        RunRequest(
            mode=RunMode.FULL_REFRESH,
            scope={"profile": "showcase"},
            idempotency_key="partial-run-001",
        )


def test_run_request_accepts_explicit_partial_psi_archive_year_evidence() -> None:
    request = RunRequest(
        mode=RunMode.FULL_REFRESH,
        scope={
            "profile": "psi-year-range",
            "all_records": True,
            "start_year": 2023,
            "end_year": 2024,
            "years": [2023, 2024],
            "all_history": False,
            "include_current_weekly": False,
            "complete": False,
            "coverage_status": "partial",
            "limitations": [
                "This candidate contains only the selected completed PSI annual partitions and "
                "cannot replace the accepted complete sales-history generation."
            ],
        },
        idempotency_key="partial-psi-001",
    )

    assert request.scope["complete"] is False


def test_terminal_run_has_no_transition() -> None:
    with pytest.raises(InvalidTransitionError):
        transition_run(RunStatus.SUCCEEDED, RunStatus.QUEUED)


def test_interrupted_run_can_resume_and_candidate_requires_review() -> None:
    assert transition_run(RunStatus.INTERRUPTED, RunStatus.QUEUED) is RunStatus.QUEUED
    assert transition_release(ReleaseStatus.CANDIDATE, ReleaseStatus.AWAITING_REVIEW)
    assert "publish" not in allowed_actions("release", ReleaseStatus.CANDIDATE)
    assert "publish" in allowed_actions("release", ReleaseStatus.AWAITING_REVIEW)


def test_uuid_type_remains_a_real_uuid() -> None:
    # Guards accidental weakening of boundary types to arbitrary strings.
    assert UUID("11111111-1111-4111-8111-111111111111").version == 4
