"""Bounded client for optional shared AI-mode research explanations."""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlsplit

import httpx

FEATURE_KEY = "propertyscope-integration-poc"
TOOL_ALLOWLIST = (
    "integration.provider_readiness.v1",
    "integration.research_compose.v1",
)
_FORWARDED = frozenset({"x-request-id", "x-agent-run-id", "traceparent", "idempotency-key"})


class AiModeUnavailableError(RuntimeError):
    def __init__(self, detail: str, *, status_code: int = 503) -> None:
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code


class AiModeClient:
    """Expose only POC run creation/read operations, never a general AI proxy."""

    def __init__(
        self,
        origin: str,
        *,
        client: httpx.Client | None = None,
        timeout_seconds: float = 10.0,
    ) -> None:
        self.origin = _validated_origin(origin)
        self._client = client or httpx.Client(
            timeout=httpx.Timeout(timeout_seconds, connect=min(timeout_seconds, 1.0)),
            follow_redirects=False,
        )

    def ready(self) -> bool:
        return bool(self.readiness()["ready"])

    def readiness(self) -> dict[str, Any]:
        """Project AI-mode's body-level health without treating degraded as ready."""
        try:
            response = self._client.get(
                self.origin + "/health/ready", timeout=2, follow_redirects=False
            )
        except httpx.TransportError:
            return {
                "ready": False,
                "state": "unavailable",
                "detail": "AI mode is unreachable; deterministic research remains usable.",
            }
        if response.status_code != 200:
            return {
                "ready": False,
                "state": "unavailable",
                "detail": f"AI mode readiness returned HTTP {response.status_code}.",
            }
        try:
            payload = response.json()
        except ValueError:
            payload = None
        if not isinstance(payload, Mapping):
            return {
                "ready": False,
                "state": "unavailable",
                "detail": "AI mode readiness returned invalid JSON.",
            }
        health_status = payload.get("status")
        if health_status == "healthy":
            return {
                "ready": True,
                "state": "ready",
                "detail": "AI explanations are available.",
            }
        checks = payload.get("checks")
        provider = checks.get("llm_provider") if isinstance(checks, Mapping) else None
        provider_detail = provider.get("detail") if isinstance(provider, Mapping) else None
        if health_status == "degraded":
            return {
                "ready": False,
                "state": "degraded",
                "detail": str(provider_detail or "AI mode is degraded."),
            }
        return {
            "ready": False,
            "state": "unavailable",
            "detail": "AI mode returned an unrecognised readiness state.",
        }

    def create_research_run(
        self,
        property_ref: uuid.UUID,
        question: str,
        *,
        idempotency_key: str,
        headers: Mapping[str, str] | None = None,
    ) -> Mapping[str, Any]:
        question = question.strip()
        if not 1 <= len(question) <= 2_000:
            raise ValueError("AI research question must contain 1 to 2000 characters")
        if not 8 <= len(idempotency_key) <= 200:
            raise ValueError("Idempotency-Key must contain 8 to 200 characters")
        objective = (
            f"property_ref: {property_ref}. Use exactly this trusted identifier. "
            "Explain only the evidence returned by the allowlisted integration POC tools. "
            "Preserve unavailable and needs-verification states; do not estimate property value, "
            "certify due diligence, rank safety, infer missing facts, or recommend whether to buy. "
            f"User question: {question}"
        )
        payload = {
            "feature_key": FEATURE_KEY,
            "objective": objective,
            "prompt_set": "default.v6",
            "limits": {
                "max_iterations": 4,
                "max_tool_calls": 4,
                "time_budget_ms": 60_000,
                "max_model_repairs": 1,
            },
            "tool_allowlist": list(TOOL_ALLOWLIST),
            "trusted_identifiers": [{"kind": "property_ref", "value": str(property_ref)}],
        }
        request_headers = _safe_headers(headers)
        request_headers["Idempotency-Key"] = idempotency_key
        result = self._request("POST", "/api/v1/agent-runs", json=payload, headers=request_headers)
        if result.get("feature_key") != FEATURE_KEY:
            raise AiModeUnavailableError("AI mode returned a run for another feature")
        return result

    def get_run(
        self, run_id: uuid.UUID, *, headers: Mapping[str, str] | None = None
    ) -> Mapping[str, Any]:
        payload = self._request(
            "GET", f"/api/v1/agent-runs/{run_id}", headers=_safe_headers(headers)
        )
        run = payload.get("run")
        if not isinstance(run, Mapping) or run.get("feature_key") != FEATURE_KEY:
            raise AiModeUnavailableError("AI run does not belong to this POC", status_code=404)
        return payload

    def _request(
        self,
        method: str,
        path: str,
        *,
        json: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> Mapping[str, Any]:
        try:
            response = self._client.request(
                method,
                self.origin + path,
                json=json,
                headers=headers,
                follow_redirects=False,
            )
        except httpx.TransportError as exc:
            raise AiModeUnavailableError(
                "AI mode is unavailable; deterministic research remains usable"
            ) from exc
        if 300 <= response.status_code < 400:
            raise AiModeUnavailableError("AI-mode redirects are forbidden")
        if response.status_code >= 400:
            raise _upstream_error(response)
        try:
            payload = response.json()
        except ValueError as exc:
            raise AiModeUnavailableError("AI mode returned invalid JSON") from exc
        if not isinstance(payload, Mapping):
            raise AiModeUnavailableError("AI-mode response must be a JSON object")
        return payload


def _validated_origin(origin: str) -> str:
    parsed = urlsplit(origin)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("AI-mode origin must be an HTTP origin")
    return origin.rstrip("/")


def _safe_headers(headers: Mapping[str, str] | None) -> dict[str, str]:
    return {key: value for key, value in (headers or {}).items() if key.lower() in _FORWARDED}


def _upstream_error(response: httpx.Response) -> AiModeUnavailableError:
    try:
        payload = response.json()
    except ValueError:
        payload = None
    detail = (
        str(payload.get("detail"))
        if isinstance(payload, Mapping) and payload.get("detail")
        else f"AI mode returned HTTP {response.status_code}"
    )
    status = response.status_code if response.status_code in {404, 409, 422} else 503
    return AiModeUnavailableError(detail, status_code=status)
