"""Bonus-tier probe for a deployed PropertyScope stack with the AI tier on (Release 2, B1-B4).

Run it after ``deploy.sh ai on`` (``.github/workflows/cloud-ai.yml`` does both):

    PROPERTYSCOPE_OPERATOR_PASSWORD=... uv run python scripts/cloud_ai_probe.py \\
        --base-url https://<label>.<region>.cloudapp.azure.com --output-dir out/

Every request goes through the public edge, signed in as the operator
(``PROPERTYSCOPE_EDGE_USER``, default ``propertyscope-operator``, and
``PROPERTYSCOPE_OPERATOR_PASSWORD`` from the environment, never the command line). The operator
credentials pass both the site-wide login and the operator realm that guards the AI routes. It
makes one real interaction per cumulative bonus tier (docs/release-2/requirements.md) through
Feature 1, the only feature with a Multi-Agent proxy:

- **B1 AI-mode:** an assistant turn (``POST /api/data-platform/v1/assistant/turns``) succeeds
  with a substantive answer, and the feature's projection matches the shared durable run;
- **B2 MCP:** that turn called ``data.releases.v1`` over MCP (``transport:mcp``) and the answer
  cites the result as a tool fact;
- **B3 RAG:** a guidance question is answered from retrieved ``operator-guidance`` citations
  whose corpus version matches the retrieval;
- **B4 Multi-Agent:** a Feature 1 release readiness review
  (``POST /api/data-platform/v1/release-reviews``) runs Planner, Worker and Reviewer with a
  model provider and stops at ``awaiting_human``. The probe never records a decision.

B1-B3 reuse the Release 1 evidence rules (``scripts/release1_capture_evidence.py``), which keep
only allowlisted fields: no prompts, tool arguments, record text or private reasoning. Results are
written as ``cloud-ai-probe.json`` and ``cloud-ai-probe.md``; the exit status is 0 only when every
tier passed. Keep these files out of ``docs/release-2/evidence/cloud/``: the AI-off cloud review
requires ``ai_enabled=false`` there. They belong in ``docs/release-2/evidence/bonus/``.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.release1_capture_evidence import CaptureError, correlate_run, verified_evidence

SCHEMA_VERSION = 1
OPERATOR_USER_ENV = "PROPERTYSCOPE_EDGE_USER"
OPERATOR_PASSWORD_ENV = (
    "PROPERTYSCOPE_OPERATOR_PASSWORD"  # pragma: allowlist secret  # noqa: S105 - name
)
DEFAULT_OPERATOR_USER = "propertyscope-operator"
API = "/api/data-platform/v1"
FEATURE_KEY = "student-1-propertyscope-data-platform"
CORPUS_ID = "operator-guidance"
MCP_TOOL = "data.releases.v1"
MCP_QUESTION = "Which datasets are published at the moment, and how many records does each have?"
RAG_QUESTION = "Why can a property show no recorded sales even though it has sold before?"
REVIEW_ACTOR = "cloud-ai-probe"
TERMINAL_RUN_STATUSES = frozenset({"succeeded", "failed", "cancelled"})
ACTIVE_WORKFLOW_STATES = frozenset({"planning", "working", "reviewing"})
FAILED_WORKFLOW_STATES = frozenset({"failed", "cancelled"})
WORKFLOW_ROLES = ("planner", "worker", "reviewer")
# Prefer a release still awaiting a decision; an accepted release is reviewable too.
RELEASE_PREFERENCE = ("awaiting_review", "candidate", "accepted")


class ProbeError(RuntimeError):
    """A request through the edge did not answer as the probe requires."""


@dataclass
class TierResult:
    tier: str
    title: str
    passed: bool
    detail: str
    evidence: dict[str, Any] = field(default_factory=dict)


class Probe:
    """Drives the public edge; ``sleep`` and ``clock`` are injectable for tests."""

    def __init__(
        self,
        client: httpx.Client,
        *,
        base_url: str,
        run_timeout: float = 300.0,
        poll_interval: float = 5.0,
        allow_deterministic: bool = False,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.client = client
        self.base_url = base_url.rstrip("/")
        self.run_timeout = run_timeout
        self.poll_interval = poll_interval
        self.allow_deterministic = allow_deterministic
        self._sleep = sleep
        self._clock = clock

    def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        headers = {"Accept": "application/json", "X-Request-ID": str(uuid.uuid4())}
        try:
            return self.client.request(method, self.base_url + path, headers=headers, **kwargs)
        except httpx.HTTPError as exc:
            raise ProbeError(f"{method} {path}: {type(exc).__name__}") from exc

    def _json(
        self, method: str, path: str, *, expected: Sequence[int] = (200,), **kwargs: Any
    ) -> dict[str, Any]:
        response = self._request(method, path, **kwargs)
        if response.status_code not in expected:
            raise ProbeError(f"{method} {path} answered {response.status_code}{_problem(response)}")
        try:
            payload = response.json()
        except ValueError as exc:
            raise ProbeError(f"{method} {path} did not answer JSON") from exc
        if not isinstance(payload, dict):
            raise ProbeError(f"{method} {path} did not answer a JSON object")
        return payload

    def _poll(self, path: str, done: Callable[[dict[str, Any]], bool]) -> dict[str, Any]:
        deadline = self._clock() + self.run_timeout
        while True:
            payload = self._json("GET", path)
            if done(payload):
                return payload
            if self._clock() >= deadline:
                raise ProbeError(f"{path} still running after {self.run_timeout:.0f}s")
            self._sleep(self.poll_interval)

    def preflight(self) -> tuple[dict[str, Any], dict[str, Any]]:
        """The AI tier is on at the edge, AI-mode is ready and MCP/RAG are enabled."""
        marker = self._request("GET", "/__propertyscope/ai-tier")
        health = self._request("GET", "/api/shared-health/ai-mode")
        capabilities = self._json("GET", "/api/ai-mode/capabilities")
        services = {
            str(item.get("id")): {"enabled": item.get("enabled"), "status": item.get("status")}
            for item in capabilities.get("services", [])
            if isinstance(item, dict)
        }
        summary = {
            "ai_tier_marker": marker.status_code,
            "ai_mode_health": health.status_code,
            "services": services,
            "grounding_feature": FEATURE_KEY in capabilities.get("grounding_features", []),
        }
        if marker.status_code != 204:
            raise ProbeError(
                f"the edge reports the AI tier off (/__propertyscope/ai-tier answered "
                f"{marker.status_code}); run deploy.sh ai on first"
            )
        if health.status_code != 200:
            raise ProbeError(f"AI-mode is not ready (health answered {health.status_code})")
        return summary, capabilities

    def assistant_turn(self, question: str) -> dict[str, Any]:
        """Ask Feature 1's assistant; the correlated shared run detail once it is terminal."""
        turns = f"{API}/assistant/turns"
        started = self._json("POST", turns, expected=(200, 201, 202), json={"message": question})
        run = started.get("run", started)
        run_id = str(run.get("id", "")) if isinstance(run, dict) else ""
        try:
            uuid.UUID(run_id)
        except ValueError as exc:
            raise ProbeError("the assistant turn answered without a run id") from exc
        owning = self._poll(
            f"{turns}/{run_id}",
            lambda detail: (
                isinstance(detail.get("run"), dict)
                and detail["run"].get("status") in TERMINAL_RUN_STATUSES
            ),
        )
        shared = self._json("GET", f"/api/v1/agent-runs/{run_id}")
        try:
            return dict(correlate_run(owning, shared))
        except CaptureError as exc:
            raise ProbeError(str(exc)) from exc

    def mcp_tiers(self, capabilities: Mapping[str, Any]) -> list[TierResult]:
        b1 = "B1", "AI-mode interaction through the app"
        b2 = "B2", f"MCP tool call ({MCP_TOOL})"
        try:
            detail = self.assistant_turn(MCP_QUESTION)
        except ProbeError as exc:
            return [TierResult(*b1, False, str(exc)), TierResult(*b2, False, str(exc))]
        run = detail.get("run", {})
        run_id = str(run.get("id"))
        final = _mapping(run.get("final_result"))
        summary = final.get("summary")
        answered = run.get("status") == "succeeded" and isinstance(summary, str) and summary.strip()
        first = TierResult(
            *b1,
            bool(answered),
            f"run {run_id} {run.get('status')}"
            + ("" if answered else " without a substantive answer"),
            {
                "run_id": run_id,
                "route": f"{API}/assistant/turns",
                "status": run.get("status"),
                "model_profile": run.get("model_profile"),
                "models": _models(detail),
                "answer_characters": len(summary) if isinstance(summary, str) else 0,
                "shared_run_matches": True,
            },
        )
        try:
            evidence = verified_evidence(
                detail,
                feature_key=FEATURE_KEY,
                corpus_id=CORPUS_ID,
                mode="mcp",
                expected_tool=MCP_TOOL,
                run_id=run_id,
                capabilities=capabilities,
            )
        except CaptureError as exc:
            return [first, TierResult(*b2, False, f"run {run_id}: {exc}")]
        names = sorted(
            {tool["tool_name"] for tool in evidence["tools"] if tool["transport"] == "mcp"}
        )
        return [
            first,
            TierResult(
                *b2,
                True,
                f"run {run_id} called {', '.join(names)} over MCP",
                evidence,
            ),
        ]

    def rag_tier(self, capabilities: Mapping[str, Any]) -> TierResult:
        b3 = "B3", f"grounded RAG answer ({CORPUS_ID})"
        try:
            detail = self.assistant_turn(RAG_QUESTION)
            run_id = str(detail.get("run", {}).get("id"))
            evidence = verified_evidence(
                detail,
                feature_key=FEATURE_KEY,
                corpus_id=CORPUS_ID,
                mode="rag",
                expected_tool=MCP_TOOL,
                run_id=run_id,
                capabilities=capabilities,
            )
        except (ProbeError, CaptureError) as exc:
            return TierResult(*b3, False, str(exc))
        return TierResult(
            *b3,
            True,
            f"run {run_id}: {evidence['citation_count']} citation(s), "
            f"grounding {evidence['grounding_status']}, confidence {evidence['confidence']}",
            evidence,
        )

    def choose_release(self) -> dict[str, Any]:
        items = self._json("GET", f"{API}/dataset-releases?limit=50").get("items", [])
        releases = [item for item in items if isinstance(item, dict) and item.get("id")]
        for status in RELEASE_PREFERENCE:
            for release in releases:
                if release.get("status") == status and release.get("dataset_id"):
                    return release
        raise ProbeError("Feature 1 has no candidate or accepted release to review")

    def multi_agent_tier(self) -> TierResult:
        b4 = "B4", "Planner -> Worker -> Reviewer workflow (Feature 1 release review)"
        reviews = f"{API}/release-reviews"
        try:
            release = self.choose_release()
            started = self._json(
                "POST",
                reviews,
                expected=(202,),
                json={
                    "input": {
                        "release_id": release["id"],
                        "dataset_id": release["dataset_id"],
                        "reviewer_note": "Cloud AI probe (scripts/cloud_ai_probe.py): bonus B4",
                    },
                    "requested_by": REVIEW_ACTOR,
                },
            )
            run_id = str(started.get("id", ""))
            uuid.UUID(run_id)
            run = self._poll(
                f"{reviews}/{run_id}",
                lambda payload: payload.get("state") not in ACTIVE_WORKFLOW_STATES,
            )
        except (ProbeError, ValueError) as exc:
            return TierResult(*b4, False, str(exc))
        evidence = _workflow_evidence(run, release)
        problems = []
        if run.get("state") in FAILED_WORKFLOW_STATES:
            problems.append(f"workflow ended {run.get('state')}")
        missing = [role for role in WORKFLOW_ROLES if role not in evidence["completed_roles"]]
        if missing:
            problems.append(f"no completed {', '.join(missing)} stage")
        if not evidence["plan_steps"] or evidence["review_recommendation"] is None:
            problems.append("no plan or review in the run")
        if run.get("provider_mode") != "model" and not self.allow_deterministic:
            problems.append(f"provider_mode is {run.get('provider_mode')}, not model")
        detail = f"run {run_id} {run.get('state')} on {release['dataset_id']} release"
        if problems:
            return TierResult(*b4, False, f"{detail}: {'; '.join(problems)}", evidence)
        return TierResult(
            *b4,
            True,
            f"{detail}; recommendation {evidence['review_recommendation']}",
            evidence,
        )

    def run(self) -> tuple[dict[str, Any], list[TierResult]]:
        try:
            preflight, capabilities = self.preflight()
        except ProbeError as exc:
            reason = f"preflight: {exc}"
            return {"error": str(exc)}, [
                TierResult(tier, title, False, reason) for tier, title in _TIERS
            ]
        results = self.mcp_tiers(capabilities)
        results.append(self.rag_tier(capabilities))
        results.append(self.multi_agent_tier())
        return preflight, results


_TIERS = (
    ("B1", "AI-mode interaction through the app"),
    ("B2", f"MCP tool call ({MCP_TOOL})"),
    ("B3", f"grounded RAG answer ({CORPUS_ID})"),
    ("B4", "Planner -> Worker -> Reviewer workflow (Feature 1 release review)"),
)


def _problem(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return ""
    if isinstance(payload, dict):
        code = payload.get("code") or payload.get("type") or payload.get("title")
        if isinstance(code, str) and code:
            return f" ({code[:120]})"
    return ""


def _mapping(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _models(detail: Mapping[str, Any]) -> list[dict[str, Any]]:
    models = []
    for step in detail.get("steps", []) or []:
        output = step.get("output") if isinstance(step, dict) else None
        invocation = output.get("model_invocation") if isinstance(output, dict) else None
        if isinstance(invocation, dict):
            models.append({key: invocation.get(key) for key in ("provider", "model")})
    return models


def _workflow_evidence(run: Mapping[str, Any], release: Mapping[str, Any]) -> dict[str, Any]:
    """Allowlisted fields of a WorkflowRun: identities, stage timeline, counts and attributions."""
    stages = [
        {key: stage.get(key) for key in ("stage", "round", "status")}
        for stage in run.get("stages", []) or []
        if isinstance(stage, dict)
    ]
    plan = _mapping(run.get("plan"))
    worker = _mapping(run.get("worker_output"))
    review = _mapping(run.get("review"))
    attributions = [
        {key: part["produced_by"].get(key) for key in ("role", "provider", "model")}
        for part in (plan, worker, review)
        if isinstance(part.get("produced_by"), dict)
    ]
    transports = Counter(
        str(item.get("transport"))
        for item in worker.get("evidence", []) or []
        if isinstance(item, dict)
    )
    return {
        "run_id": run.get("id"),
        "template_id": run.get("template_id"),
        "route": f"{API}/release-reviews",
        "release_id": release.get("id"),
        "dataset_id": release.get("dataset_id"),
        "release_status": release.get("status"),
        "state": run.get("state"),
        "provider_mode": run.get("provider_mode"),
        "stages": stages,
        "completed_roles": sorted(
            {str(stage["stage"]) for stage in stages if stage.get("status") == "completed"}
        ),
        "plan_steps": len(plan.get("steps", []) or []),
        "worker_evidence_transports": dict(sorted(transports.items())),
        "review_recommendation": review.get("recommendation"),
        "review_findings": len(review.get("findings", []) or []),
        "models": attributions,
    }


def build_document(
    *,
    base_url: str,
    commit_sha: str | None,
    started_at: datetime,
    preflight: Mapping[str, Any],
    results: Sequence[TierResult],
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "base_url": base_url,
        "commit_sha": commit_sha,
        "started_at": started_at.isoformat(),
        "finished_at": datetime.now(UTC).isoformat(),
        "passed": bool(results) and all(result.passed for result in results),
        "summary": {
            "passed": sum(result.passed for result in results),
            "failed": sum(not result.passed for result in results),
            "total": len(results),
        },
        "preflight": dict(preflight),
        "tiers": [asdict(result) for result in results],
    }


def render_markdown(document: Mapping[str, Any]) -> str:
    summary = document["summary"]
    lines = [
        "# Cloud AI bonus-tier probe",
        "",
        f"- Site: {document['base_url']}",
        f"- Commit: {document.get('commit_sha') or 'not recorded'}",
        f"- Started: {document['started_at']}; finished: {document['finished_at']}",
        f"- Result: **{'PASS' if document['passed'] else 'FAIL'}** "
        f"({summary['passed']}/{summary['total']} tiers)",
        "",
        "| Tier | What was demonstrated | Result | Detail |",
        "|---|---|---|---|",
    ]
    for tier in document["tiers"]:
        detail = str(tier["detail"]).replace("|", "\\|")
        lines.append(
            f"| {tier['tier']} | {tier['title']} | {'PASS' if tier['passed'] else 'FAIL'} "
            f"| {detail} |"
        )
    lines += ["", "## Preflight", "", "```json", json.dumps(document["preflight"], indent=2), "```"]
    for tier in document["tiers"]:
        if tier["evidence"]:
            lines += [
                "",
                f"## {tier['tier']} evidence",
                "",
                "```json",
                json.dumps(tier["evidence"], indent=2, sort_keys=True),
                "```",
            ]
    return "\n".join(lines) + "\n"


def write_reports(output_dir: Path, document: Mapping[str, Any]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "cloud-ai-probe.json").write_text(
        json.dumps(document, indent=2) + "\n", encoding="utf-8"
    )
    (output_dir / "cloud-ai-probe.md").write_text(render_markdown(document), encoding="utf-8")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--base-url", required=True, help="public site, e.g. https://<fqdn>")
    parser.add_argument("--output-dir", type=Path, default=Path("cloud-ai-probe"))
    parser.add_argument("--commit-sha", default=None, help="the deployed commit, for the report")
    parser.add_argument("--run-timeout", type=float, default=300.0, help="seconds per AI run")
    parser.add_argument("--poll-interval", type=float, default=5.0, help="seconds between polls")
    parser.add_argument("--timeout", type=float, default=60.0, help="seconds per HTTP request")
    parser.add_argument(
        "--allow-deterministic",
        action="store_true",
        help="accept a Multi-Agent run without a model provider (local rehearsal only)",
    )
    parser.add_argument("--insecure", action="store_true", help="skip TLS verification")
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    transport: httpx.BaseTransport | None = None,
    environment: Mapping[str, str] | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    arguments = _parser().parse_args(argv)
    base_url = arguments.base_url.rstrip("/")
    if not base_url.startswith(("http://", "https://")):
        print("--base-url must start with http:// or https://", file=sys.stderr)
        return 2
    if arguments.commit_sha is not None and (
        len(arguments.commit_sha) != 40
        or any(char not in "0123456789abcdef" for char in arguments.commit_sha)
    ):
        print("--commit-sha must be a 40-character lower-case hex commit", file=sys.stderr)
        return 2
    settings = os.environ if environment is None else environment
    password = settings.get(OPERATOR_PASSWORD_ENV, "")
    if not password:
        print(
            f"set ${OPERATOR_PASSWORD_ENV} (the operator login) in the environment", file=sys.stderr
        )
        return 2
    user = settings.get(OPERATOR_USER_ENV) or DEFAULT_OPERATOR_USER
    started_at = datetime.now(UTC)
    with httpx.Client(
        timeout=arguments.timeout,
        verify=not arguments.insecure,
        follow_redirects=False,
        transport=transport,
        auth=httpx.BasicAuth(user, password),
        headers={"User-Agent": "propertyscope-cloud-ai-probe/1"},
    ) as client:
        probe = Probe(
            client,
            base_url=base_url,
            run_timeout=arguments.run_timeout,
            poll_interval=arguments.poll_interval,
            allow_deterministic=arguments.allow_deterministic,
            sleep=sleep,
        )
        preflight, results = probe.run()
    document = build_document(
        base_url=base_url,
        commit_sha=arguments.commit_sha,
        started_at=started_at,
        preflight=preflight,
        results=results,
    )
    write_reports(arguments.output_dir, document)
    for result in results:
        print(f"{result.tier} {'PASS' if result.passed else 'FAIL'}: {result.detail}", flush=True)
    summary = document["summary"]
    print(
        f"\n{summary['passed']}/{summary['total']} tiers passed; reports in {arguments.output_dir}"
    )
    return 0 if document["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
