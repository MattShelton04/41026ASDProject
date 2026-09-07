"""Signed capability and neutral tool-policy invariants."""

from uuid import uuid4

import pytest
from shared_tool_runtime.invocation import (
    authorize_invocation,
    sign_invocation,
    validate_service_token,
    verify_invocation,
)

from shared_contracts import ApprovalStatus, SideEffectClass, ToolCall, ToolDefinition

TOKEN = "deterministic-test-service-token-123456"


def invocation() -> ToolCall:
    return ToolCall(
        id=uuid4(),
        run_id=uuid4(),
        step_id=uuid4(),
        tool_name="test.read.v1",
        tool_version="v1",
        arguments={"b": 2, "a": 1},
        approval_status=ApprovalStatus.NOT_REQUIRED,
    )


def test_signature_binds_call_identity_and_canonical_arguments() -> None:
    call = invocation()
    signed = sign_invocation(
        call, feature_key="feature-1", service_token=TOKEN, timeout_ms=1000, now=10
    )
    context = verify_invocation(
        signed, service_token=TOKEN, tool_name=call.tool_name, arguments={"a": 1, "b": 2}, now=10.5
    )
    assert context.call.id == call.id
    assert context.call.run_id == call.run_id
    assert context.call.arguments == {}
    assert context.deadline == 11


@pytest.mark.parametrize("signed", ["invalid", "a.b", "a" * 16385, "%%%%.signature"])
def test_malformed_context_is_rejected(signed: str) -> None:
    with pytest.raises(ValueError, match="invalid invocation"):
        verify_invocation(signed, service_token=TOKEN, tool_name="test.read.v1", arguments={})


def test_signature_rejects_future_and_expired_context() -> None:
    call = invocation()
    signed = sign_invocation(
        call, feature_key="feature-1", service_token=TOKEN, timeout_ms=1000, now=10
    )
    for now in [9, 11, 100]:
        with pytest.raises(ValueError, match="expired"):
            verify_invocation(
                signed,
                service_token=TOKEN,
                tool_name=call.tool_name,
                arguments=call.arguments,
                now=now,
            )


def test_short_service_secret_is_rejected() -> None:
    with pytest.raises(ValueError, match="32"):
        validate_service_token("short")


@pytest.mark.parametrize(
    "effect,approval,key,accepted",
    [
        (SideEffectClass.READ_ONLY, ApprovalStatus.NOT_REQUIRED, None, True),
        (SideEffectClass.REVERSIBLE_WRITE, ApprovalStatus.NOT_REQUIRED, None, False),
        (SideEffectClass.REVERSIBLE_WRITE, ApprovalStatus.NOT_REQUIRED, "idempotency-key", True),
        (SideEffectClass.DESTRUCTIVE_WRITE, ApprovalStatus.PENDING, "idempotency-key", False),
        (SideEffectClass.DESTRUCTIVE_WRITE, ApprovalStatus.REJECTED, "idempotency-key", False),
        (SideEffectClass.DESTRUCTIVE_WRITE, ApprovalStatus.APPROVED, "idempotency-key", True),
        (SideEffectClass.EXTERNAL_EFFECT, ApprovalStatus.APPROVED, "idempotency-key", False),
    ],
)
def test_neutral_policy_preserves_orchestrator_boundary(effect, approval, key, accepted) -> None:
    definition = ToolDefinition(
        name="test.read.v1",
        version="v1",
        feature_key="feature-1",
        description="test",
        input_schema={},
        output_schema={},
        side_effect=effect,
    )
    call = invocation().model_copy(update={"approval_status": approval, "idempotency_key": key})
    if accepted:
        authorize_invocation(call, definition)
    else:
        with pytest.raises(ValueError):
            authorize_invocation(call, definition)
