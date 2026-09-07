"""Authenticated invocation context kept outside model-controlled tool arguments."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time

from pydantic import BaseModel, ConfigDict, Field

from shared_contracts import ApprovalStatus, SideEffectClass, ToolCall, ToolDefinition

INVOCATION_META_KEY = "propertyscope/invocation"
MAX_INVOCATION_SECONDS = 120


class InvocationContext(BaseModel):
    """A short-lived, signed capability for exactly one validated invocation."""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)
    feature_key: str = Field(min_length=1, max_length=100)
    call: ToolCall
    arguments_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    issued_at: float
    deadline: float


def validate_service_token(service_token: str) -> None:
    """Refuse accidentally unprotected service startup."""
    if len(service_token) < 32:
        raise ValueError("service token must contain at least 32 characters")


def arguments_digest(arguments: object) -> str:
    """Bind the exact canonical JSON argument value, independent of key ordering."""
    raw = json.dumps(arguments, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode()).hexdigest()


def sign_invocation(
    call: ToolCall,
    *,
    feature_key: str,
    service_token: str,
    timeout_ms: int,
    now: float | None = None,
) -> str:
    """Mint metadata only after the orchestrator's deterministic authorization."""
    validate_service_token(service_token)
    issued = time.time() if now is None else now
    context = InvocationContext(
        feature_key=feature_key,
        call=call.model_copy(update={"arguments": {}}),
        arguments_sha256=arguments_digest(call.arguments),
        issued_at=issued,
        deadline=issued + min(max(timeout_ms, 1) / 1000, MAX_INVOCATION_SECONDS),
    )
    payload = base64.urlsafe_b64encode(context.model_dump_json().encode()).decode()
    signature = hmac.new(service_token.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}.{signature}"


def verify_invocation(
    signed: str,
    *,
    service_token: str,
    tool_name: str,
    arguments: object,
    now: float | None = None,
) -> InvocationContext:
    """Reject conflicting, expired, modified or malformed protocol metadata."""
    try:
        if len(signed) > 16_384:
            raise ValueError("invocation metadata is too large")
        payload, signature = signed.rsplit(".", 1)
        expected = hmac.new(service_token.encode(), payload.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            raise ValueError("invalid invocation signature")
        context = InvocationContext.model_validate_json(base64.urlsafe_b64decode(payload))
    except (ValueError, UnicodeError) as exc:
        raise ValueError("invalid invocation context") from exc
    current = time.time() if now is None else now
    if (
        not context.issued_at <= current < context.deadline
        or context.deadline - context.issued_at > MAX_INVOCATION_SECONDS
        or context.call.tool_name != tool_name
        or context.call.arguments
        or context.arguments_sha256 != arguments_digest(arguments)
    ):
        raise ValueError("invocation context conflicts or has expired")
    return context


def authorize_invocation(call: ToolCall, definition: ToolDefinition) -> None:
    """Reapply the existing conservative approval policy at the MCP boundary."""
    if definition.side_effect is SideEffectClass.EXTERNAL_EFFECT:
        raise ValueError("external effects are disabled")
    if definition.side_effect is not SideEffectClass.READ_ONLY and not call.idempotency_key:
        raise ValueError("write tools require an idempotency key")
    requires_review = (
        definition.requires_approval or definition.side_effect is SideEffectClass.DESTRUCTIVE_WRITE
    )
    if requires_review and call.approval_status is not ApprovalStatus.APPROVED:
        raise ValueError("tool invocation requires human approval")
