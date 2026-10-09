"""Run a review through the shared agent loop: live AI-mode over HTTP, or the same loop in-process.

Both paths execute the production ``AgentRunner`` with the review prompt set, the read-only
``review.evidence.v1`` tool and the review completion validator. The live path posts the run to
the managed AI-mode host process, so it appears in Activity history and uses the configured
provider. The deterministic path mirrors ``ai validate``: a temporary run store and scripted
checklist decisions, clearly labelled, with no model or network.
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

import httpx
from pydantic import JsonValue

from agent_core import (
    AgentRunner,
    ModelMetrics,
    ModelRole,
    ProviderHealth,
    StructuredModelRequest,
    StructuredModelResult,
    ToolRegistry,
    create_run,
)
from ai_mode.adapters.system import SystemClock, UUID4Generator
from ai_mode.persistence import SQLiteRunStore
from ai_mode.prompts import PromptRegistry, RegistryPromptBuilder
from ai_mode.release_review import (
    ReviewCompletionValidator,
    ReviewEvidenceToolExecutor,
    review_evidence_definition,
)
from ai_mode.services import UnconfiguredToolExecutor
from scripts.devtools.config import REPOSITORY_ROOT
from scripts.devtools.review.deterministic import deterministic_review
from scripts.devtools.service_auth import AI_SERVICE_TOKEN_HEADER
from shared_contracts import AgentRunRequest, RunLimits
from shared_contracts.evidence_review import (
    MAX_REVIEW_OBJECTIVE_CHARS,
    REVIEW_EVIDENCE_TOOL,
    REVIEW_FEATURE_KEY,
    REVIEW_PROMPT_SETS,
    EvidenceCheck,
    EvidenceReviewBundle,
)
from shared_contracts.http import REQUEST_ID_HEADER

DETERMINISTIC_PROVIDER = "deterministic-review"
DETERMINISTIC_MODEL = "checklist-review.v1"
PROMPT_ROOT = REPOSITORY_ROOT / "ai-services/ai-mode/src/ai_mode/prompt_assets"
TERMINAL = frozenset({"succeeded", "failed", "cancelled", "review_required"})
_MAX_RESPONSE_BYTES = 2 * 1024 * 1024


class ReviewLoopError(RuntimeError):
    """The review run could not be started, finished or read; carries the run id if known."""

    def __init__(self, message: str, *, run_id: str | None = None, code: str = "unavailable"):
        super().__init__(message)
        self.run_id = run_id
        self.code = code


@dataclass(frozen=True, slots=True)
class LoopRun:
    """What the loop recorded for one review run, projected from its persisted detail."""

    engine: str
    run_id: str
    request_id: str | None
    status: str
    phases: tuple[str, ...]
    final_result: dict[str, JsonValue] | None
    error: str | None
    invocations: tuple[dict[str, JsonValue], ...]
    tool_evidence: tuple[str, ...]

    @property
    def provider(self) -> str | None:
        """Provider of the final model decision, if any model step ran."""
        return _last_value(self.invocations, "provider")

    @property
    def model(self) -> str | None:
        """Model of the final model decision, if any model step ran."""
        return _last_value(self.invocations, "model")


def bundle_digest(bundle: EvidenceReviewBundle) -> str:
    """Hash the canonical bundle JSON so logs can prove which evidence was reviewed."""
    payload = json.dumps(bundle.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def objective_for(bundle: EvidenceReviewBundle) -> tuple[EvidenceReviewBundle, str]:
    """Fit the bundle into AI-mode's objective budget, compacting only when needed."""
    candidates = (bundle, *_compactions(bundle))
    for candidate in candidates:
        text = candidate.model_dump_json()
        if len(text) <= MAX_REVIEW_OBJECTIVE_CHARS:
            return candidate, text
    raise ReviewLoopError(
        "The evidence bundle is too large for one review run even after compaction; "
        "reduce the number of evidence files",
        code="bundle_too_large",
    )


def _compactions(bundle: EvidenceReviewBundle) -> tuple[EvidenceReviewBundle, ...]:
    without_facts = bundle.evolve(
        facts={"omitted": "Facts exceeded the run budget; see the review report."},
        compacted=True,
    )
    short_checks = without_facts.evolve(
        checks=tuple(
            _short_check(check, keep_detail=check.status.value == "failed")
            for check in bundle.checks
        )
    )
    return (without_facts, short_checks)


def _short_check(check: EvidenceCheck, *, keep_detail: bool) -> dict[str, Any]:
    payload = check.model_dump(mode="json")
    payload["detail"] = check.detail[:160] if keep_detail else "Passed."
    payload["evidence_refs"] = list(check.evidence_refs[:3])
    return payload


def run_request(bundle: EvidenceReviewBundle, *, time_budget_ms: int) -> AgentRunRequest:
    """Build the bounded, single-tool run request for one review mode."""
    _, objective = objective_for(bundle)
    return AgentRunRequest(
        feature_key=REVIEW_FEATURE_KEY,
        objective=objective,
        title=f"Release 2 {bundle.mode} evidence review",
        prompt_set=REVIEW_PROMPT_SETS[bundle.mode],
        tool_allowlist=(REVIEW_EVIDENCE_TOOL,),
        limits=RunLimits(
            max_iterations=4,
            max_tool_calls=3,
            time_budget_ms=max(1_000, min(time_budget_ms, 900_000)),
            max_parallel_tools=1,
            max_model_repairs=2,
        ),
    )


class ChecklistReviewProvider:
    """Scripted decisions: plan the evidence tool, then return the checklist-derived review."""

    def __init__(self, bundle: EvidenceReviewBundle) -> None:
        self.bundle = bundle

    def health(self) -> ProviderHealth:
        return ProviderHealth(reachable=True, detail="Deterministic checklist review decisions")

    def generate_structured(self, request: StructuredModelRequest) -> StructuredModelResult:
        if request.role is ModelRole.PLANNER:
            content: dict[str, JsonValue] = {
                "goal": f"Review the attached {self.bundle.mode} release evidence",
                "actions": [
                    {
                        "sequence": 1,
                        "tool_name": REVIEW_EVIDENCE_TOOL,
                        "arguments": {},
                        "purpose": "Read the schema-validated evidence bundle for this run",
                    }
                ],
                "success_criteria": ["Every failed checklist item is reported as a finding"],
                "risk_level": "low",
                "assumptions": [],
            }
        else:
            review = deterministic_review(self.bundle)
            content = {
                "decision": "complete",
                "justification": "Deterministic checklist review of the recorded bundle",
                "final_result": review.model_dump(mode="json"),
            }
        return StructuredModelResult(
            content=content,
            provider=DETERMINISTIC_PROVIDER,
            model=DETERMINISTIC_MODEL,
            metrics=ModelMetrics(total_duration_ms=0),
        )


def run_deterministic(bundle: EvidenceReviewBundle, *, time_budget_ms: int = 60_000) -> LoopRun:
    """Execute the production loop in-process with scripted checklist decisions."""
    request = run_request(bundle, time_budget_ms=time_budget_ms)
    compact, _ = objective_for(bundle)
    clock, ids = SystemClock(), UUID4Generator()
    with TemporaryDirectory(prefix="propertyscope-r2-review-") as directory:
        store = SQLiteRunStore(Path(directory) / "review.sqlite3")
        store.initialize()
        run = create_run(
            request,
            run_id=ids.new(),
            request_id=f"r2-review-{bundle.mode}-{uuid.uuid4().hex[:12]}",
            now=clock.now(),
        )
        store.create(run)
        runner = AgentRunner(
            store=store,
            provider=ChecklistReviewProvider(compact),
            prompt_builder=RegistryPromptBuilder(PromptRegistry(PROMPT_ROOT)),
            tools=ToolRegistry((review_evidence_definition(),)),
            tool_executor=ReviewEvidenceToolExecutor(UnconfiguredToolExecutor(), store),
            clock=clock,
            ids=ids,
            completion_validator=ReviewCompletionValidator(),
        )
        runner.run_until_blocked(run.id)
        detail = store.get(run.id)
        if detail is None:
            raise RuntimeError(f"deterministic review run {run.id} was not persisted")
        return project_detail(detail.model_dump(mode="json"), engine="deterministic")


class AiModeReviewClient:
    """Start a review run on the managed AI-mode host process and wait for it to finish."""

    def __init__(
        self,
        base_url: str,
        token: str,
        *,
        client: httpx.Client | None = None,
        poll_interval: float = 1.0,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.client = client or httpx.Client(follow_redirects=False, timeout=15)
        self._owns_client = client is None
        self.headers = {AI_SERVICE_TOKEN_HEADER: token}
        self.poll_interval = poll_interval
        self.sleep = sleep
        self.monotonic = monotonic

    def close(self) -> None:
        if self._owns_client:
            self.client.close()

    def run(self, bundle: EvidenceReviewBundle, *, timeout_seconds: float) -> LoopRun:
        """Create the run, poll its durable detail and return its projection."""
        request = run_request(bundle, time_budget_ms=int(timeout_seconds * 1000))
        request_id = f"r2-review-{bundle.mode}-{uuid.uuid4().hex[:12]}"
        created = self._json(
            "POST",
            "/api/v1/agent-runs",
            json=request.model_dump(mode="json", exclude_none=True),
            headers={REQUEST_ID_HEADER: request_id},
            expected=202,
        )
        run_id = created.get("id")
        if not isinstance(run_id, str):
            raise ReviewLoopError("AI-mode accepted the review but returned no run id")
        deadline = self.monotonic() + timeout_seconds
        while True:
            detail = self._json("GET", f"/api/v1/agent-runs/{run_id}", expected=200, run=run_id)
            run = detail.get("run")
            status = run.get("status") if isinstance(run, dict) else None
            if status in TERMINAL:
                return project_detail(detail, engine="ai-mode")
            if self.monotonic() >= deadline:
                raise ReviewLoopError(
                    f"AI-mode review run {run_id} did not finish within {timeout_seconds:g}s "
                    f"(status {status}); it continues in Activity history",
                    run_id=run_id,
                    code="timeout",
                )
            self.sleep(self.poll_interval)

    def _json(
        self,
        method: str,
        path: str,
        *,
        expected: int,
        json: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
        run: str | None = None,
    ) -> dict[str, Any]:
        try:
            response = self.client.request(
                method,
                self.base_url + path,
                json=json,
                headers={**self.headers, **(headers or {})},
            )
        except httpx.HTTPError as exc:
            raise ReviewLoopError(
                f"AI-mode is unreachable at {self.base_url} ({type(exc).__name__})", run_id=run
            ) from exc
        if response.status_code != expected:
            code = "unauthorized" if response.status_code == 401 else "rejected"
            detail = _problem_detail(response)
            raise ReviewLoopError(
                f"AI-mode returned HTTP {response.status_code} for {method} {path}: {detail}",
                run_id=run,
                code=code,
            )
        if len(response.content) > _MAX_RESPONSE_BYTES:
            raise ReviewLoopError("AI-mode response exceeded the review size limit", run_id=run)
        try:
            body = response.json()
        except ValueError as exc:
            raise ReviewLoopError("AI-mode returned a non-JSON response", run_id=run) from exc
        if not isinstance(body, dict):
            raise ReviewLoopError("AI-mode returned an unexpected response shape", run_id=run)
        return body


def project_detail(detail: Mapping[str, Any], *, engine: str) -> LoopRun:
    """Project an ``AgentRunDetail`` JSON document onto what the review records."""
    run = detail.get("run")
    if not isinstance(run, dict) or not isinstance(run.get("id"), str):
        raise ReviewLoopError("AI-mode run detail has no run object")
    steps = [step for step in detail.get("steps", []) if isinstance(step, dict)]
    invocations: list[dict[str, JsonValue]] = []
    evidence: list[str] = []
    for step in steps:
        output = step.get("output")
        if not isinstance(output, dict):
            continue
        invocation = output.get("model_invocation")
        if isinstance(invocation, dict):
            invocations.append(
                {
                    "phase": step.get("phase"),
                    **{
                        key: invocation.get(key)
                        for key in (
                            "provider",
                            "model",
                            "prompt_id",
                            "prompt_version",
                            "prompt_hash",
                            "repair_count",
                        )
                    },
                }
            )
        results = output.get("tool_results")
        if results is None and isinstance(output.get("tool_result"), dict):
            results = [output["tool_result"]]
        if isinstance(results, list):
            for result in results:
                if isinstance(result, dict):
                    references = result.get("evidence_references")
                    if isinstance(references, list):
                        evidence.extend(str(item) for item in references)
    error = run.get("error")
    final = run.get("final_result")
    return LoopRun(
        engine=engine,
        run_id=run["id"],
        request_id=run.get("request_id") if isinstance(run.get("request_id"), str) else None,
        status=str(run.get("status")),
        phases=tuple(str(step.get("phase")) for step in steps),
        final_result=final if isinstance(final, dict) else None,
        error=(f"{error.get('code')}: {error.get('message')}" if isinstance(error, dict) else None),
        invocations=tuple(invocations),
        tool_evidence=tuple(dict.fromkeys(evidence)),
    )


def _problem_detail(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return "no problem detail"
    if isinstance(body, dict):
        return str(body.get("detail") or body.get("code") or "no problem detail")[:300]
    return "no problem detail"


def _last_value(items: tuple[dict[str, JsonValue], ...], key: str) -> str | None:
    for item in reversed(items):
        value = item.get(key)
        if isinstance(value, str):
            return value
    return None
