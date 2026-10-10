# ADR-047: Add a host Multi-Agent Server for Planner, Worker and Reviewer workflows

- Status: Accepted
- Date: 9 October 2026
- Owner: Shared platform (Matthew Shelton)
- Extends: [ADR-046](ADR-046-non-containerised-ai-tier.md) (same non-containerised AI tier)
- Plan: [Release 2 shared plan, section A](../../release-2/parts/shared.md)

## Context

Release 2 asks every feature for a multi-agent workflow. A Planner breaks a feature-specific task
into steps. A Worker gathers evidence with the feature's tools. A Reviewer checks the result and
recommends what a human should decide. A person then approves, corrects (once), partially accepts
or rejects. AI-mode already runs one bounded agent loop per chat request, with its own state
machine and approval policy. Folding a three-role, human-gated workflow into it would mix two
lifecycles in one store and one HTTP surface. Five features need the workflow, so it must be shared
and domain-neutral. Each feature still supplies its own task, tools and review rules.

## Decision

1. **A separate host service.** `ai-services/multi-agent-server` is a Flask application served by
   waitress. Like AI-mode, MCP and RAG, it runs only as a host process on `MULTI_AGENT_PORT`
   (default 5013), started by `dev.py ai start` / `stack up` (ADR-046). It has no Dockerfile and
   no Compose service, and it never starts in CI. It binds `0.0.0.0` so backends can reach it
   through `host.docker.internal`. Every route except `/health` and `/health/live` requires
   `Authorization: Bearer $MULTI_AGENT_SERVICE_TOKEN`. The host runtime issues that token and
   shares it only with feature backends.
2. **Contracts first.** Request, run, decision, history and audit models live in
   `shared_contracts.multi_agent`. JSON Schemas and `shared/contracts/openapi/multi-agent.v1.openapi.json`
   are generated from them, and so are the API and the testkit fake.
3. **Explicit state machine with one correction round.** The states are
   `planning → working → reviewing → awaiting_human`, then `approved | corrected |
   partially_accepted | rejected`. `cancelled` can be reached from every unfinished state;
   `failed` only while an agent is working. The first `correct` decision supersedes the round, keeps the plan, and sends the run back
   to `working` with the human note. A `correct` decision in round 2 ends in `corrected`. Agents
   never choose a terminal outcome.
4. **Feature-owned templates.** Each feature declares its workflow in
   `student-N/config/multi-agent/workflow.yaml`. A template has inputs, a tool allowlist, required
   steps and declarative reviewer checks. The server registers templates only for features enabled
   in `deployment/enabled-features.v1.json`, and only when `feature_id` matches the owning slice.
   The architecture gate validates enabled manifests against the contract, and
   `multi-agent-server validate` also checks them against the tool catalogues.
5. **Read-only tools through MCP.** The Worker calls only the template's allowlisted tools. Each
   must be registered, `read_only`, approval-free, and owned by the feature or `shared`. Calls go
   through MCP when MCP is enabled; in `direct` mode they go to the catalogue's HTTP endpoints.
   Every call and rejection is stored as evidence with a result digest and a bounded excerpt.
6. **Reuse AI-mode's model plumbing, not its loop.** Model calls use agent-core's provider port,
   with AI-mode's provider factory and model registry (`build_provider`,
   `configured_model_registry`). This gives the same credentials, profiles and offline rules.
   Role prompts are versioned assets with content hashes. Model output is schema-validated, then
   policy-checked, retried a bounded number of times, and then either falls back to a
   deterministic provider or fails the run with a structured error. Without a real credential the
   deterministic provider runs, so tests and offline stacks need no key. Reviewer checks are
   deterministic. A model may add findings, but it cannot recommend `approve` over a failed high
   or critical check.
7. **Durable, exportable evidence.** Runs live in SQLite under
   `.propertyscope-runtime/host/multi-agent/`, with optimistic versioning. Every state transition
   and every agent handoff, model invocation, tool call and decision is appended to
   `workflow_history.jsonl` and `coordination_audit.jsonl`. `multi-agent-server export <run>` writes
   those files plus `run.json` and `summary.md` for the report.
8. **Dependency boundary.** The server may depend on `shared-contracts`, `agent-core`, `ai-mode`
   and `shared-tool-runtime`. It must not import `shared_testkit`, `mcp_server` or `rag_server`.
   No other shared package may import it. Student code, including tests, must not import
   `multi_agent_server`. Students call the HTTP API and test against
   `shared_testkit.FakeMultiAgentServer`, which a parity test keeps aligned with the real API.
9. **Browsers reach workflows only through their feature backend.** The service token never
   reaches a browser. Each feature that shows workflows adds proxy routes under its own API root
   (`GET {root}/template`, `POST {root}`, `GET {root}`, `GET {root}/{run}`,
   `POST {root}/{run}/decision`, `POST {root}/{run}/cancel`, `GET {root}/{run}/history`). The
   backend fixes its own `template_id`, returns 404 for runs of other features or templates,
   relays the server's Problem Details unchanged, and returns 503 `multi_agent_unavailable` when
   the server is unreachable or unconfigured. The domain-neutral panel
   `shared/frontend/multi-agent/` renders any template against that contract: the input form, a
   polled stage timeline, the plan, the Worker evidence, the Reviewer findings and the decision
   controls allowed by `available_actions`. Feature 1's release readiness review
   (`/api/data-platform/v1/release-reviews` and the "Readiness review" action) is the reference
   integration. (Added 10 October 2026, Release 2 Phase 2.)

## Consequences

- Features get a shared, auditable human-in-the-loop workflow by adding a manifest, the proxy
  routes in decision 9 and a panel mount. They change no shared code.
- The AI tier gains a fourth host process and a fourth token. `ai status`, `ai logs` and `ai probe`
  cover it, and `stack doctor` reports its port.
- Backends need `MULTI_AGENT_BASE_URL` and `MULTI_AGENT_SERVICE_TOKEN`. Compose passes both to the
  feature backends through the host gateway. The validator rejects non-gateway URLs and literal
  tokens.
- Runs in flight when the server stops are marked `failed` (`interrupted`) on the next start;
  agents are not resumed mid-stage. Execution is in-process with a bounded queue, so one server
  process is the deployment unit.
- Cloud hosting follows the AI-tier decision for Release 2 (implementation plan D1). It does not
  change this boundary.
