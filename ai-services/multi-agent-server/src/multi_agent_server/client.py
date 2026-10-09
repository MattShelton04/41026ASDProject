"""Small typed HTTP client for the Multi-Agent Server API (used by the CLI's ``--server`` mode)."""

from __future__ import annotations

import time
from typing import Any
from uuid import UUID

import httpx

from shared_contracts.multi_agent import (
    ACTIVE_WORKFLOW_STATES,
    MULTI_AGENT_API_PREFIX,
    HumanDecisionRequest,
    WorkflowRun,
    WorkflowRunHistory,
    WorkflowRunPage,
    WorkflowRunRequest,
    WorkflowTemplateList,
)


class MultiAgentClientError(RuntimeError):
    """The server returned a Problem Details error or could not be reached."""

    def __init__(self, status: int | None, code: str, detail: str) -> None:
        super().__init__(
            f"{code}: {detail}" if status is None else f"HTTP {status} {code}: {detail}"
        )
        self.status = status
        self.code = code
        self.detail = detail


class MultiAgentClient:
    """Bearer-authenticated JSON client; never logs or echoes the token."""

    def __init__(
        self,
        base_url: str,
        token: str,
        *,
        timeout: float = 30.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {token}"},
            timeout=timeout,
            follow_redirects=False,
            trust_env=False,
            transport=transport,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> MultiAgentClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        try:
            response = self._client.request(method, f"{MULTI_AGENT_API_PREFIX}{path}", **kwargs)
        except httpx.HTTPError as exc:
            raise MultiAgentClientError(
                None, "unreachable", f"Multi-Agent Server is unreachable ({type(exc).__name__})"
            ) from exc
        if response.status_code >= 400:
            try:
                body = response.json()
            except ValueError:
                body = {}
            raise MultiAgentClientError(
                response.status_code,
                str(body.get("code", "http_error")),
                str(body.get("detail", response.reason_phrase)),
            )
        return response.json()

    def templates(self) -> WorkflowTemplateList:
        return WorkflowTemplateList.model_validate(self._request("GET", "/templates"))

    def start(self, request: WorkflowRunRequest) -> WorkflowRun:
        return WorkflowRun.model_validate(
            self._request("POST", "/runs", json=request.model_dump(mode="json"))
        )

    def run(self, run_id: UUID | str) -> WorkflowRun:
        return WorkflowRun.model_validate(self._request("GET", f"/runs/{run_id}"))

    def runs(self, **filters: str | int) -> WorkflowRunPage:
        return WorkflowRunPage.model_validate(self._request("GET", "/runs", params=filters))

    def decide(self, run_id: UUID | str, request: HumanDecisionRequest) -> WorkflowRun:
        return WorkflowRun.model_validate(
            self._request("POST", f"/runs/{run_id}/decision", json=request.model_dump(mode="json"))
        )

    def cancel(self, run_id: UUID | str, *, actor: str) -> WorkflowRun:
        return WorkflowRun.model_validate(
            self._request("POST", f"/runs/{run_id}/cancel", json={"actor": actor})
        )

    def history(self, run_id: UUID | str) -> WorkflowRunHistory:
        return WorkflowRunHistory.model_validate(self._request("GET", f"/runs/{run_id}/history"))

    def wait(
        self, run_id: UUID | str, *, timeout: float = 300.0, interval: float = 0.5
    ) -> WorkflowRun:
        """Poll until no agent is working on the run (or the timeout passes)."""
        deadline = time.monotonic() + timeout
        run = self.run(run_id)
        while run.state in ACTIVE_WORKFLOW_STATES and time.monotonic() < deadline:
            time.sleep(interval)
            run = self.run(run_id)
        return run
