# Multi-Agent Server

A host-local service that runs feature-owned **Planner → Worker → Reviewer → human** workflows
([ADR-047](../../docs/architecture/decisions/ADR-047-multi-agent-server.md)). A feature declares a
template in `student-N/config/multi-agent/workflow.yaml`. A backend starts a run over HTTP. The
agents plan, gather evidence with the template's read-only tools and review it, and then a person
approves, corrects once, partially accepts or rejects.

Like AI-mode, MCP and RAG, it runs only as a host process (ADR-046). It has no Dockerfile, no
Compose service, and it never runs in CI. Feature backends reach it at
`http://host.docker.internal:${MULTI_AGENT_PORT:-5013}`.

| | |
|---|---|
| Port | `MULTI_AGENT_PORT`, default **5013** (bound to `0.0.0.0`; every non-liveness route needs the token) |
| Auth | `Authorization: Bearer $MULTI_AGENT_SERVICE_TOKEN` |
| State | `.propertyscope-runtime/host/multi-agent/` (`multi-agent.sqlite3`, `workflow_history.jsonl`, `coordination_audit.jsonl`, `exports/`) |
| Contracts | `shared_contracts.multi_agent`, `shared/contracts/schemas/workflow-*.v1.schema.json`, `shared/contracts/openapi/multi-agent.v1.openapi.json` |
| Test double | `shared_testkit.FakeMultiAgentServer` (same API, in memory) |

## Running it

`uv run scripts/dev.py stack up` and `uv run scripts/dev.py ai start [--mode ...]` start it with
AI-mode, MCP and RAG. In `mcp` and `combined` modes the Worker calls tools through MCP; in
`direct` (and `--offline`) mode it calls the feature tool endpoints directly. `ai status`,
`ai logs multi-agent`, `ai stop multi-agent` and `ai probe` cover it. The host runtime writes the
token to `.propertyscope-runtime/host/multi-agent.token` and passes it to Compose as
`MULTI_AGENT_SERVICE_TOKEN`.

The agents use a model when AI-mode would: when a real `OPENAI_API_KEY` (or the Gemini equivalent)
is configured. They use the same model registry and profile. Otherwise, and always with
`MULTI_AGENT_PROVIDER=deterministic`, a rule-based provider produces the plan, Worker summary and
review, so offline stacks and tests need no key.

| Variable | Default | Meaning |
|---|---|---|
| `MULTI_AGENT_SERVICE_TOKEN` | required to serve | 32–128 URL-safe characters |
| `MULTI_AGENT_STATE_DIR` | `.propertyscope-runtime/host/multi-agent` | SQLite + JSONL location |
| `MULTI_AGENT_REPOSITORY_ROOT` | current directory | Where enabled features and manifests are discovered |
| `MULTI_AGENT_TEMPLATE_PATHS` | discovery | Comma-separated manifests that replace discovery |
| `MULTI_AGENT_PROVIDER` | `auto` | `auto`, `deterministic` or `model` |
| `MULTI_AGENT_MODEL_PROFILE` | AI-mode default | Model registry profile for the agents |
| `MULTI_AGENT_MODEL_ATTEMPTS` | `2` | Attempts per agent stage (1–3) before fallback |
| `MULTI_AGENT_MODEL_TIMEOUT_SECONDS` | `60` | Per-call deadline |
| `MULTI_AGENT_MODEL_FALLBACK` | `deterministic` | `deterministic`, or `fail` to fail the run instead |
| `MULTI_AGENT_TOOL_TRANSPORT` | `auto` | `auto` (MCP if enabled, else HTTP when catalogues are explicit), `mcp`, `http`, `none` |
| `MULTI_AGENT_TOOL_CATALOG_PATHS` | `MCP_TOOL_CATALOG_PATHS` | Tool catalogues (the host runtime projects host URLs) |
| `MULTI_AGENT_MCP_ENABLED`, `MCP_SERVER_URL`, `MCP_SERVICE_TOKEN` | from AI-mode settings | MCP transport |
| `MULTI_AGENT_TOOL_FIXTURES` | unset | JSON tool fixture (tests and demos only) |
| `MULTI_AGENT_WORKERS`, `MULTI_AGENT_QUEUE_CAPACITY` | `2`, `20` | Background stage execution bounds |

## Workflow states

```text
planning ─▶ working ─▶ reviewing ─▶ awaiting_human ─┬─▶ approved
    │          │  ▲         │             │          ├─▶ partially_accepted
    │          │  └─────────┼─────────────┘ correct  ├─▶ rejected
    │          │            │          (round 1 only)└─▶ corrected (correct in round 2)
    └──────────┴────────────┴──▶ failed | cancelled   (cancelled also from awaiting_human)
```

- Agents never pick an outcome. Only a human decision leaves `awaiting_human`.
- **Correction rule:** the first `correct` moves round 1 into `superseded`, keeps the plan, and
  re-runs the Worker and Reviewer with the human's note. A `correct` decision in round 2 ends the
  run as `corrected`.
- `partial` needs `accepted_step_ids` (plan step IDs). Every decision except `approve` needs a
  `note`.
- A stage that cannot produce valid output, after bounded retries and the configured fallback,
  moves the run to `failed` with `error.code` (for example `planner_output_unavailable`). Runs
  left in flight when the server stops are marked `failed` with `interrupted` on the next start.
- `available_actions` on every run says which buttons a UI should offer.

## HTTP API

Every path is under `/api/v1/multi-agent` except health. Requests and responses are JSON.
`X-Request-ID` is echoed back, or generated when absent or unsafe. A malformed `traceparent` is
rejected. Run responses carry `X-Workflow-Run-ID`. Errors are Problem Details
(`application/problem+json`) with a stable `code`, `request_id` and optional field `errors`.
Responses are `Cache-Control: no-store`.

| Method and path | Body / query | Success | Errors (`code`) |
|---|---|---|---|
| `GET /health`, `GET /health/live` | public | 200 liveness | |
| `GET /health/ready` | | 200/503 `TypedHealthProjection`: `state_store` (required), `templates`, `tool_gateway`, `provider` | 401 |
| `GET /templates` | | 200 `WorkflowTemplateList` `{items: [{template, input_schema, tools[{name, available}], source}], count}` | 401 |
| `GET /templates/{id}` | | 200 `WorkflowTemplateDescriptor` | 404 `template_not_found` |
| `POST /runs` | `WorkflowRunRequest` `{template_id, input, requested_by?}` | **202** `WorkflowRun` (usually `planning`), `Location`, `X-Workflow-Run-ID` | 400 `invalid_request`, 422 `invalid_request_body` / `invalid_workflow_input`, 404 `template_not_found`, 503 `workflow_capacity_exceeded`, 413 `request_too_large` |
| `GET /runs` | `template_id`, `feature_id`, `state`, `limit` (1–100, default 20) | 200 `WorkflowRunPage` `{items: [WorkflowRunSummary], count}`, newest first | 400 `invalid_request` |
| `GET /runs/{run_id}` | | 200 `WorkflowRun` | 404 `run_not_found` |
| `POST /runs/{run_id}/decision` | `HumanDecisionRequest` `{decision, note, actor, accepted_step_ids?}` | 200 `WorkflowRun` (terminal, or `working` round 2 after a first `correct`) | 409 `invalid_state_transition`, 422 `invalid_decision` / `invalid_request_body` |
| `POST /runs/{run_id}/cancel` | optional `{actor}` | 200 `WorkflowRun` (`cancelled`) | 409 `invalid_state_transition` |
| `GET /runs/{run_id}/history` | | 200 `WorkflowRunHistory` `{run_id, state, history[], audit[]}` | 404 `run_not_found` |

A started run is processed in the background, so poll `GET /runs/{id}` until `state` is no longer
`planning`, `working` or `reviewing`. A `WorkflowRun` contains `plan` (steps with resolved
arguments), `worker_output` (step results, findings and `evidence[]`: tool, arguments, outcome,
`result_digest`, bounded `excerpt`, transport), `review` (`recommendation`, `findings[]` with
severity, outcome, recommendation and the evidence they cite), `superseded` (the corrected round),
`decisions`, `stages`, `error` and `available_actions`. Each agent output records `produced_by`:
the provider, model, prompt ID, version and hash, the number of invocations, and whether it fell
back.

```bash
TOKEN=$(cat .propertyscope-runtime/host/multi-agent.token)
curl -s -X POST http://127.0.0.1:5013/api/v1/multi-agent/runs \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"template_id": "example-readiness-review", "input": {"record_id": "8c0d7e0e-4a3b-4c55-9a62-0d7c5f0f9a11"}}'
curl -s -X POST http://127.0.0.1:5013/api/v1/multi-agent/runs/$RUN/decision \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"decision": "correct", "note": "Recheck the quality results", "actor": "analyst"}'
```

Feature backends must call the API over HTTP with `MULTI_AGENT_BASE_URL` and
`MULTI_AGENT_SERVICE_TOKEN`. They must never import `multi_agent_server`, including in tests; the
architecture gate enforces this.

## Workflow manifests

A feature owns `student-N/config/multi-agent/workflow.yaml`. The server registers it only when the
feature is enabled and `feature_id` is that feature's key. Check it with
`uv run multi-agent-server validate student-N/config/multi-agent/workflow.yaml`, which also checks
every tool against the enabled features' catalogues.

```yaml
schema_version: 1
id: example-readiness-review          # lowercase identifier, unique across features
version: v1                           # bump when steps or checks change; runs record it
feature_id: example-feature           # must be the owning feature's feature_key
title: Example readiness review
objective: >-                         # what the Planner is asked to achieve
  Recommend whether the requested record is ready to publish.
inputs:                               # closed JSON Schema built from these; validated on start
  - name: record_id
    type: string                      # string | integer | number | boolean
    title: Record ID
    format: uuid                      # uuid | date | date-time | uri (strings default to <=1000 chars)
  - name: reviewer_note
    title: Optional context
    required: false
    max_length: 500
planner_guidance: >-                  # extra instructions for the Planner prompt
  Read the record summary first, then its quality results. Never plan a write.
allowed_tools:                        # the only tools the Worker may call; each must be registered,
  - example.record.v1                 # read_only, approval-free and owned by this feature (or shared)
  - example.quality.v1
steps:                                # required steps; a model Planner may add, never drop or retool
  - id: record
    title: Read the record summary
    purpose: Confirm the record exists.
    tool: example.record.v1
    arguments:
      record_id: "{{input.record_id}}"  # whole placeholders keep their type; absent optional inputs are dropped
  - id: quality
    title: Read the quality results
    purpose: See which quality checks failed.
    tool: example.quality.v1
    arguments: {record_id: "{{input.record_id}}"}
reviewer_checks:                      # deterministic; a failed check becomes a finding
  - id: record-found
    description: The record summary was retrieved.
    severity: critical                # critical -> reject, high -> correct, medium -> partial
    recommendation: Confirm the record ID and run the workflow again.
    rule: {kind: step_succeeded, step: record}
  - id: record-matches
    description: The returned record is the one requested.
    severity: high
    recommendation: Investigate why a different record was returned.
    rule: {kind: field_compare, step: record, path: id, operator: eq, value: "{{input.record_id}}"}
  - id: quality-recorded
    description: At least one quality check result exists.
    severity: medium
    recommendation: Run the quality checks before publishing.
    rule: {kind: min_items, step: quality, path: checks, value: 1}
human_review_guidance: >-             # shown to the person deciding
  Approve only when every high or critical check passed.
```

Rule kinds are `all_steps_succeeded`; `step_succeeded` (`step`); `field_present` (`step`, `path`);
`field_compare` (`step`, `path`, `operator`: `eq ne gt ge lt le in not_in contains`, and `value`,
which may be a placeholder); and `min_items` (`step`, `path`, `value`). Paths use dots and list
indexes (`items.0.id`). The Reviewer's recommendation is the strictest failed check's mapping.
A model Reviewer can add findings, but it cannot recommend `approve` over a failed high or
critical check.

## CLI

```text
uv run multi-agent-server serve [--host 127.0.0.1] [--port 5013]
uv run multi-agent-server validate MANIFEST [--catalog CATALOG ...]
uv run multi-agent-server templates [--json]
uv run multi-agent-server run --template ID --input JSON|@file.json [--requested-by NAME] [--wait] [--json]
uv run multi-agent-server status RUN_ID
uv run multi-agent-server list [--template ID] [--feature KEY] [--limit N] [--json]
uv run multi-agent-server decide RUN_ID --decision approve|correct|partial|reject --note TEXT [--actor NAME] [--accept STEP ...] [--wait]
uv run multi-agent-server cancel RUN_ID [--actor NAME]
uv run multi-agent-server history RUN_ID [--json]
uv run multi-agent-server export RUN_ID [--out DIR]
```

Workflow commands run **in-process** by default. They open the state directory and run the agents
synchronously, so `run` returns at `awaiting_human`. Combine this with `--deterministic`,
`--tool-fixtures FILE` and `--template-path FILE` for a fully offline demonstration. Do not run
in-process commands against a state directory that a running server owns.

Add `--server [URL]` to call a running server instead. The URL defaults to
`$MULTI_AGENT_BASE_URL` or `http://127.0.0.1:$MULTI_AGENT_PORT`. The token comes from
`--token-file`, `MULTI_AGENT_SERVICE_TOKEN`, or the host runtime's token file. This is the
integrated path, where tools go through MCP. Put `--server` after positional arguments
(`status RUN_ID --server`) or give it a URL.

```text
uv run multi-agent-server run --deterministic \
  --template-path ai-services/multi-agent-server/tests/fixtures/workflow.yaml \
  --tool-fixtures ai-services/multi-agent-server/tests/fixtures/tools.json \
  --template example-readiness-review --input '{"record_id": "8c0d7e0e-4a3b-4c55-9a62-0d7c5f0f9a11"}'
```

## Evidence and export

Every state change is appended to `workflow_history.jsonl` (`sequence`, `run_id`, `request_id`,
`at`, `from_state`, `to_state`, `round`, `actor`, `role`, `reason`). Every coordination event is
appended to `coordination_audit.jsonl`: `run.created`, `agent.handoff`, `plan.created`,
`model.invocation` (provider, model, prompt hash, tokens, outcome), `model.fallback`, `tool.call`,
`tool.rejected`, `worker.completed`, `review.completed`, `decision.recorded` (actor, time, note),
`run.failed` and `run.cancelled`. SQLite is the source of truth, and the JSONL files are
append-only mirrors that span runs.

`multi-agent-server export RUN_ID [--out DIR]` writes `run.json`, that run's
`workflow_history.jsonl` and `coordination_audit.jsonl`, and a Markdown `summary.md` (stages,
plan, evidence, findings, decisions and the audit trail). The default directory is
`<state>/exports/<run_id>/`. Copy it into `docs/release-2/evidence/` for the report.

## Package layout

| Module | Responsibility |
|---|---|
| `state_machine.py` | Legal transitions, the correction rule, decision targets and available actions |
| `templates.py` | Manifest discovery, loading, ownership checks and input validation |
| `tools.py` | `ToolGateway` port (MCP/HTTP catalogue, fixture, unavailable) and the allowlist/read-only `TemplateToolbox` |
| `prompts.py`, `prompt_assets/` | Versioned, hashed Planner/Worker/Reviewer prompts |
| `providers.py` | Deterministic provider and model selection through AI-mode's registry |
| `agents.py` | Schema-validated, retried, policy-checked Planner, Worker and Reviewer |
| `checks.py` | Deterministic reviewer checks and recommendation mapping |
| `service.py`, `execution.py` | Run orchestration, decisions, cancellation, recovery and bounded background execution |
| `store.py`, `evidence.py` | SQLite state with optimistic versioning, JSONL mirrors and export |
| `app.py`, `client.py`, `cli.py`, `settings.py` | HTTP API, typed client, CLI and composition root |

Tests (`ai-services/multi-agent-server/tests`) need no Docker, network or model key. They use a
domain-neutral fixture template, fixture tools, `ScriptedLLMProvider` for model paths, and a
parity test that runs one scenario against both this API and `FakeMultiAgentServer`.
