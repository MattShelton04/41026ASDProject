"""Cloud AI bonus-tier probe against an in-memory edge (httpx.MockTransport); no network."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from scripts import cloud_ai_probe
from scripts.cloud_ai_probe import API, FEATURE_KEY, MCP_QUESTION, Probe, main

PASSWORD = "operator-test-password"  # pragma: allowlist secret
ENVIRONMENT = {"PROPERTYSCOPE_OPERATOR_PASSWORD": PASSWORD}
VERSION = "a" * 64
MCP_RUN = "11111111-1111-4111-8111-111111111111"
RAG_RUN = "22222222-2222-4222-8222-222222222222"
REVIEW_RUN = "33333333-3333-4333-8333-333333333333"
BASE = "https://cloud.test"


def _citation() -> dict[str, Any]:
    return {
        "citation_id": "c1",
        "feature_key": FEATURE_KEY,
        "corpus_id": "operator-guidance",
        "corpus_version": VERSION,
        "document_id": "d1",
        "chunk_id": "k1",
        "title": "Sales matching",
        "excerpt": "Sales match only exact addresses.",
        "source_uri": "docs/guide.md",
        "content_hash": "b" * 64,
        "score": 0.9,
    }


def _turn_detail(run_id: str, *, rag: bool, mcp_transport: bool = True) -> dict[str, Any]:
    citations = [_citation()] if rag else []
    calls = [{"id": "call-r", "tool_name": "context.retrieve.v1", "tool_version": "1"}]
    results: list[dict[str, Any]] = [
        {
            "call_id": "call-r",
            "outcome": "succeeded",
            "retrieval": {
                "feature_key": FEATURE_KEY,
                "corpus_id": "operator-guidance",
                "corpus_version": VERSION,
                "status": "ready",
                "citations": citations,
            },
        }
    ]
    findings: list[dict[str, Any]]
    if rag:
        findings = [{"kind": "guidance", "citation_ids": ["c1"], "tool_call_ids": []}]
    else:
        calls.append({"id": "call-1", "tool_name": "data.releases.v1", "tool_version": "1"})
        results.append(
            {
                "call_id": "call-1",
                "outcome": "succeeded",
                "evidence_references": ["transport:mcp"] if mcp_transport else [],
                "content": {"datasets": 5},
            }
        )
        findings = [{"kind": "tool_fact", "citation_ids": [], "tool_call_ids": ["call-1"]}]
    return {
        "run": {
            "id": run_id,
            "status": "succeeded",
            "feature_key": FEATURE_KEY,
            "request_id": "req-" + run_id[:8],
            "model_profile": "remote-standard.v1",
            "grounding": {"corpus_id": "operator-guidance"},
            "final_result": {
                "summary": "Five datasets are published.",
                "confidence": "high" if not rag else "moderate",
                "confidence_reason": "From the release register.",
                "corpus_version": VERSION,
                "grounding_status": "grounded",
                "citations": citations,
                "findings": findings,
            },
        },
        "steps": [
            {
                "input": {"tool_calls": calls},
                "output": {
                    "tool_results": results,
                    "model_invocation": {"provider": "openai", "model": "gpt-5.6-luna"},
                },
            }
        ],
    }


def _workflow(state: str, provider_mode: str = "model") -> dict[str, Any]:
    done = state not in {"planning", "working", "reviewing"}
    attribution = {"provider": "openai", "model": "gpt-5.6-terra"}
    return {
        "id": REVIEW_RUN,
        "template_id": "f1-release-readiness-review",
        "state": state,
        "provider_mode": provider_mode,
        "stages": [
            {"stage": role, "round": 1, "status": "completed" if done else "running"}
            for role in ("planner", "worker", "reviewer")
        ],
        "plan": {"steps": [{"id": "s1"}], "produced_by": {"role": "planner", **attribution}},
        "worker_output": {
            "evidence": [{"transport": "mcp"}, {"transport": "http"}],
            "produced_by": {"role": "worker", **attribution},
        },
        "review": {
            "recommendation": "approve",
            "findings": [{"id": "f-1"}],
            "produced_by": {"role": "reviewer", **attribution},
        }
        if done
        else None,
    }


class FakeEdge:
    """The operator's view of the edge with the AI tier on; each run needs one extra poll."""

    def __init__(
        self,
        *,
        tier: int = 204,
        mcp_transport: bool = True,
        provider_mode: str = "model",
        releases: list[dict[str, Any]] | None = None,
    ) -> None:
        self.tier = tier
        self.mcp_transport = mcp_transport
        self.provider_mode = provider_mode
        self.releases = releases or [
            {"id": "r-accepted", "dataset_id": "gnaf-nsw", "status": "accepted"}
        ]
        self.requests: list[tuple[str, str, Any]] = []
        self.polls: dict[str, int] = {}

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        body = json.loads(request.content) if request.content else None
        self.requests.append((request.method, path, body))
        assert request.headers["Authorization"].startswith("Basic ")
        assert request.headers["X-Request-ID"]
        turns = f"{API}/assistant/turns"
        reviews = f"{API}/release-reviews"
        if path == "/__propertyscope/ai-tier":
            return httpx.Response(self.tier)
        if path == "/api/shared-health/ai-mode":
            return httpx.Response(200, json={"status": "ready"})
        if path == "/api/ai-mode/capabilities":
            return httpx.Response(
                200,
                json={
                    "services": [
                        {"id": "mcp", "enabled": True, "status": "ready"},
                        {"id": "rag", "enabled": True, "status": "ready"},
                        {"id": "multi-agent", "enabled": True, "status": "ready"},
                    ],
                    "grounding_features": [FEATURE_KEY],
                },
            )
        if request.method == "POST" and path == turns:
            run_id = MCP_RUN if body["message"] == MCP_QUESTION else RAG_RUN
            return httpx.Response(202, json={"id": run_id, "status": "queued"})
        for run_id, rag in ((MCP_RUN, False), (RAG_RUN, True)):
            detail = _turn_detail(run_id, rag=rag, mcp_transport=self.mcp_transport)
            if path == f"{turns}/{run_id}":
                if self._first_poll(path):
                    return httpx.Response(200, json={"run": {"id": run_id, "status": "acting"}})
                return httpx.Response(200, json=detail)
            if path == f"/api/v1/agent-runs/{run_id}":
                return httpx.Response(200, json=detail)
        if path == f"{API}/dataset-releases":
            return httpx.Response(200, json={"items": self.releases})
        if request.method == "POST" and path == reviews:
            return httpx.Response(202, json=_workflow("planning", self.provider_mode))
        if path == f"{reviews}/{REVIEW_RUN}":
            state = "working" if self._first_poll(path) else "awaiting_human"
            return httpx.Response(200, json=_workflow(state, self.provider_mode))
        return httpx.Response(404, json={"code": "not_found"})

    def _first_poll(self, path: str) -> bool:
        self.polls[path] = self.polls.get(path, 0) + 1
        return self.polls[path] == 1


def _main(edge: FakeEdge, tmp_path: Path, *extra: str) -> tuple[int, dict[str, Any]]:
    code = main(
        ["--base-url", BASE, "--output-dir", str(tmp_path), *extra],
        transport=httpx.MockTransport(edge),
        environment=ENVIRONMENT,
        sleep=lambda _seconds: None,
    )
    return code, json.loads((tmp_path / "cloud-ai-probe.json").read_text(encoding="utf-8"))


def test_every_tier_passes_and_the_reports_hold_no_secret(tmp_path: Path) -> None:
    edge = FakeEdge()

    code, document = _main(edge, tmp_path, "--commit-sha", "0" * 40)

    assert code == 0
    assert document["passed"] and document["summary"] == {"passed": 4, "failed": 0, "total": 4}
    assert [tier["tier"] for tier in document["tiers"]] == ["B1", "B2", "B3", "B4"]
    b2, b3, b4 = (document["tiers"][index]["evidence"] for index in (1, 2, 3))
    assert {tool["transport"] for tool in b2["tools"]} == {"rag", "mcp"}
    assert b3["citation_count"] == 1 and b3["retrieval_status"] == "ready"
    assert b4["completed_roles"] == ["planner", "reviewer", "worker"]
    assert b4["state"] == "awaiting_human" and b4["provider_mode"] == "model"
    assert b4["worker_evidence_transports"] == {"http": 1, "mcp": 1}
    # The probe never records a human decision on the review.
    assert not any(path.endswith("/decision") for _, path, _ in edge.requests)
    review = next(body for method, path, body in edge.requests if path.endswith("release-reviews"))
    assert review["input"]["release_id"] == "r-accepted"
    assert review["requested_by"] == "cloud-ai-probe"
    for name in ("cloud-ai-probe.json", "cloud-ai-probe.md"):
        text = (tmp_path / name).read_text(encoding="utf-8")
        assert PASSWORD not in text
        assert "Sales match only exact addresses." not in text  # no record or excerpt text
    assert "| B4 |" in (tmp_path / "cloud-ai-probe.md").read_text(encoding="utf-8")


def test_an_edge_with_the_ai_tier_off_fails_every_tier(tmp_path: Path) -> None:
    edge = FakeEdge(tier=503)

    code, document = _main(edge, tmp_path)

    assert code == 1
    assert document["summary"]["failed"] == 4
    assert all("deploy.sh ai on" in tier["detail"] for tier in document["tiers"])
    assert not any(method == "POST" for method, _, _ in edge.requests)


def test_a_tool_result_not_carried_over_mcp_fails_only_b2(tmp_path: Path) -> None:
    code, document = _main(FakeEdge(mcp_transport=False), tmp_path)

    assert code == 1
    outcomes = {tier["tier"]: tier["passed"] for tier in document["tiers"]}
    assert outcomes == {"B1": True, "B2": False, "B3": True, "B4": True}
    assert "MCP" in document["tiers"][1]["detail"]


def test_a_deterministic_multi_agent_run_needs_an_explicit_allowance(tmp_path: Path) -> None:
    code, document = _main(FakeEdge(provider_mode="deterministic"), tmp_path)
    assert code == 1
    assert "provider_mode is deterministic" in document["tiers"][3]["detail"]

    code, document = _main(
        FakeEdge(provider_mode="deterministic"), tmp_path / "allowed", "--allow-deterministic"
    )
    assert code == 0


def test_a_release_awaiting_review_is_preferred(tmp_path: Path) -> None:
    edge = FakeEdge(
        releases=[
            {"id": "r-accepted", "dataset_id": "gnaf-nsw", "status": "accepted"},
            {"id": "r-open", "dataset_id": "nsw-psi-sales", "status": "awaiting_review"},
        ]
    )

    code, document = _main(edge, tmp_path)

    assert code == 0
    assert document["tiers"][3]["evidence"]["release_id"] == "r-open"


def test_a_run_that_never_finishes_times_out() -> None:
    class Stuck(FakeEdge):
        def _first_poll(self, path: str) -> bool:
            return True

    ticks = iter(range(0, 10_000, 10))
    with httpx.Client(transport=httpx.MockTransport(Stuck())) as client:
        client.headers["Authorization"] = "Basic eDp5"
        probe = Probe(
            client,
            base_url=BASE,
            run_timeout=60,
            sleep=lambda _seconds: None,
            clock=lambda: float(next(ticks)),
        )
        preflight, results = probe.run()

    assert preflight["ai_tier_marker"] == 204
    assert not any(result.passed for result in results)
    assert "still running after 60s" in results[0].detail


@pytest.mark.parametrize(
    ("argv", "environment", "message"),
    [
        (["--base-url", BASE], {}, "PROPERTYSCOPE_OPERATOR_PASSWORD"),
        (["--base-url", "cloud.test"], ENVIRONMENT, "--base-url"),
        (["--base-url", BASE, "--commit-sha", "abc"], ENVIRONMENT, "--commit-sha"),
    ],
)
def test_invalid_invocations_exit_2(
    argv: list[str],
    environment: dict[str, str],
    message: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(argv, environment=environment) == 2
    assert message in capsys.readouterr().err


def test_the_markdown_escapes_table_cells() -> None:
    document = cloud_ai_probe.build_document(
        base_url=BASE,
        commit_sha=None,
        started_at=cloud_ai_probe.datetime.now(cloud_ai_probe.UTC),
        preflight={},
        results=[cloud_ai_probe.TierResult("B1", "t", False, "a|b")],
    )

    assert "a\\|b" in cloud_ai_probe.render_markdown(document)
