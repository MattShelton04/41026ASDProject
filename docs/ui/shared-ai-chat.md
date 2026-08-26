# PropertyScope AI chat

Status: implemented shared capability, with Property data as the first feature adapter
Updated: 26 August 2026

## Open the assistant

Start the complete stack, then use either entry point:

```text
Application-global chat  http://localhost:5100/#assistant
Property data chat       http://localhost:5200/#assistant
Integrated Feature 1     http://localhost:5100/features/data-platform/#assistant
```

The global interface has an explicit scope chooser. **All of PropertyScope** answers questions
about the website and current application capabilities; **Property data** focuses the same turn on
the implemented Feature 1 tools. Research areas that are not implemented are reported as planned,
not silently routed to Property data.

Feature 1 also keeps its fixed-objective **Data review** workflow. Data review starts from an exact
candidate release and uses preset comparison/quality objectives. AI chat is a separate route for
free-form, read-only questions; it does not replace publication review or recovery controls.

## What one turn means

Each submitted message creates exactly one durable AI-mode `AgentRun` through the Feature 1 public
backend. The browser does not call AI-mode or a feature database directly:

```text
Shared or Feature 1 browser
  -> POST /api/data-platform/v1/assistant/turns
  -> Feature 1 validates scope, message and page context
  -> POST AI-mode /api/v1/agent-runs
  -> AI-mode calls only allowlisted Feature 1 HTTP tools
  <- run snapshot + resumable cursor events
```

The visible transcript groups independent runs for convenience. It is intentionally local to the
open page and is not hidden server-side conversation memory. Follow-up questions must repeat or
attach the required entity context. Every assistant message shows its state, durable run ID, full
activity link and a collapsed source/tool record. The UI shows recorded phases and evidence—not
private chain-of-thought.

Supported visible states are queued, planning, plan ready, checking a source, recording evidence,
preparing an answer, complete, needs human review, failed and cancelled. A temporary polling error
keeps the last recorded answer visible and retries with bounded backoff.

## Page-linked context

Feature routes can open chat with allowlisted context query fields:

```text
#assistant?route=releases/detail&release_id=<uuid>
#assistant?route=runs/detail&ingestion_run_id=<uuid>
#assistant?route=properties/detail&property_ref=<uuid>
```

Only `route`, `release_id`, `ingestion_run_id` and `property_ref` are accepted. The feature wrapper
filters them before submission and the backend validates them again. Exact identifiers are copied
into the run objective; unknown fields and malformed UUIDs are rejected rather than passed to the
model.

## Current capabilities and limits

The read-only `platform.capabilities.v1` tool grounds questions about PropertyScope, available
routes, the assistant and current limitations. Feature 1 additionally supplies bounded tools for
sources, ingestion runs, releases, coverage and accepted property search/inspection.

Do not interpret a registered or active source as loaded data. `data.sources.v1` describes source
definitions only. `data.releases.v1` supplies bounded release IDs, states and record counts;
`data.runs.v1` defaults to the latest ten succeeded runs and retains only the explicit requested
scope and row-count evidence needed to assess full-data loads. A "fully loaded" answer requires a
succeeded run whose `requested_scope_json` explicitly names `full-data` or `all_records`. Candidate,
awaiting-review and accepted release states are reported separately.

Conversational turns persist an exact per-run `tool_allowlist` containing only read-only tools.
AI-mode filters the planner catalogue and checks the same allowlist again at execution, so the
prompt is guidance rather than the security boundary. Protected retry and publish tools remain part
of the separately reviewed AI-mode platform but are neither visible to nor executable by chat runs.
The Feature 1 adapter also verifies the run's feature key and exact chat allowlist before returning
detail/events or forwarding cancellation; another feature's run and a fixed Data review run are
returned as not found.
The assistant:

- is research support, not valuation, legal, lending, planning or buy/no-buy advice;
- cannot access arbitrary repository files, environment files, a shell or a feature database;
- distinguishes accepted data from candidate data and missing checks from passing checks;
- may only use the Feature 1 tools currently registered under its feature key; and
- has no cross-feature routing until another implemented feature supplies its own manifest,
  backend turn adapter and allowlisted HTTP tools.

## Gemini development setup

Keep the Git-ignored `.env.gemini` file configured as described in the root README. Start or
reconcile the stack without printing that file:

```text
uv run scripts/dev.py stack up --env-file .env.gemini
```

Then confirm readiness and use either assistant route above. A normal turn should progress through
planning, one or more bounded source checks and adaptation before reaching a terminal answer. Use
the exact **Open full activity** link on a message to audit its model profile, persisted steps,
tool evidence and correlation references.

The deterministic UI fixture server can render the component without a provider:

```text
uv run scripts/dev.py ui serve
```

Fixture mode is for layout and interaction checks; it is not evidence of a Gemini answer.

## Reusable frontend package

Feature frontends import only `shared/frontend/ai-chat/index.js` (copied into the frontend image as
`ai-chat/index.js`). The public barrel provides:

- a same-origin assistant client;
- cursor merge and adaptive polling helpers;
- semantic run-state definitions;
- generic structured-result and evidence formatting;
- accessible message, status, disclosure and run-link components; and
- the transcript/controller lifecycle.

Wrappers inject their scope labels, suggested questions, page context, activity URL and API root.
This prevents the shared package from owning feature vocabulary or business rules. Component styles
use only the shared `--ps-*` design tokens and are loaded from `ai-chat/styles.css`.

## Validation

Use these focused checks while developing:

```text
node --test shared/frontend/ai-chat/ai-chat.test.mjs
node --test shared/frontend/dashboard.test.mjs student-1/tests/frontend/core.test.mjs
uv run pytest student-1/tests/unit/test_assistant.py student-1/tests/component/test_http_apps.py --no-cov -q
uv run pytest ai-services/ai-mode/tests/test_prompts.py ai-services/agent-core/tests/test_runner.py --no-cov -q
uv run python scripts/check.py
```

The prompt regressions prove that cumulative results above the model-message limit are projected,
tool-discovered identifiers reach replanning, guessed UUID-shaped identifiers are rejected before a
tool call and prompt-construction validation failures become terminal rather than reconciling
indefinitely. Replanning also rejects any exact tool call that already succeeded, so the model must
choose a genuinely different evidence path. Feature tests prove that release/run inventories omit
large manifests, source snapshots and lease internals, and that accepted property search and exact
inspection return the same stable identity.
