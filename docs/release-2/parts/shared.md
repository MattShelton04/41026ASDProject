# Shared / Common: Release 2 plan

Owner: Matthew. Scope: the shared services, tooling, cloud and evidence that all five features
depend on. Feature-specific behaviour stays in the student slices. The decisions D1–D7 are in the
[implementation plan](../implementation-plan.md).

## A. Multi-Agent Server (R2-10 to R2-17)

Package `ai-services/multi-agent-server` (`propertyscope-multi-agent-server`): a Flask application
factory, a host process on `:5013`, no Dockerfile.

1. **Contract** in `shared/contracts`: `WorkflowTemplate`, `WorkflowRun`, `PlanStep`,
   `WorkerOutput`, `ReviewFinding`, `HumanDecision` (`approve | correct | partial | reject`).
   Regenerate with `scripts/generate_contracts.py`.
2. **State machine:** `planning → working → reviewing → awaiting_human → {approved, corrected,
   partially_accepted, rejected}`, plus `failed` and `cancelled`. A `correct` decision re-runs
   Worker and Reviewer once, with the human's note added.
3. **Agents:** three role prompts under `prompt_assets/` (planner, worker, reviewer), each with a
   version. They use the existing provider adapter and model registry. The Worker gathers evidence
   only through the template's allowlisted **read-only** MCP tools. The Reviewer sees the plan, the
   Worker output and the evidence, and returns findings with severity and recommendations. A
   deterministic provider is used for tests and offline runs.
4. **Persistence:** SQLite in `.propertyscope-runtime/host/multi-agent/`, plus append-only
   `workflow_history.jsonl` (state transitions) and `coordination_audit.jsonl` (agent handoffs,
   tool calls, decision actor and time), with an export command.
5. **HTTP API:** endpoints to start a run, read a run, submit a decision and list templates. Each
   is protected by a service token, uses the shared request/run correlation IDs, and returns
   structured errors.
6. **CLI:** `multi-agent-server run --template <id> --input <json>`, `status <run>`,
   `decide <run> --decision approve --note ...`, `export <run>`, and `validate <manifest>`.
7. **Runtime integration:** add `multi-agent` to `AI_SERVICE_PORTS` and the `ai start/stop/probe`
   commands; add `MULTI_AGENT_BASE_URL` (via `host.docker.internal`) to the feature backends in
   Compose; update `validate_architecture.py` and its tests (no student imports, no Compose
   service).
8. **Shared UI panel** `shared/frontend/multi-agent/`, reused by every feature in the same way as
   `ai-chat`: start, live stages, findings, decision buttons and a correction note.
9. **Test kit:** a fake Multi-Agent Server in `shared_testkit` so feature backends can be tested
   without the real host process.
10. **Docs:** ADR-047, a package README and an update to `ai-services/README.md`.

## B. Agentic-loop review modes (R2-20 to R2-23)

1. Add `dev.py ai review {multi-agent,testing,cloud}`. Keep `ai validate {mcp,rag}` unchanged.
2. **Collectors** read bounded evidence from `docs/release-2/evidence/`:
   - `multi-agent`: workflow histories and audits
   - `testing`: the security report and `ci/*.md`
   - `cloud`: the deployment report, workflow logs and smoke output
3. Each mode starts an AI-mode run with a review prompt set (`review-multi-agent.v1`,
   `review-testing.v1`, `review-cloud.v1`). The output schema has findings, risks,
   recommendations and a verdict.
4. Write `reviews/<mode>-review.md` and `<mode>-validation-log.jsonl` (run ID, prompt version,
   inputs hashed, checks passed/failed). Add a `--deterministic` flag for tests.
5. The cloud review ends with a human release decision, recorded in `cloud/release-decision.md`.

## C. Pre-commit security scans (R2-30, R2-31)

1. Add Ruff `S` (flake8-bandit) to `[tool.ruff.lint]`. Ignore `S101` in tests; fix or `# noqa`
   anything else, with a reason.
2. Add a `detect-secrets` hook with a reviewed `.secrets.baseline`.
3. Add a `pip-audit` hook that audits the exported `uv.lock`. Add the dev dependencies with
   `uv add --dev`.
4. Add `dev.py security report`, which runs all three scans and writes
   `evidence/security/pre-commit-report.md` plus the raw JSON.
5. Run the same scans in `integration-ci.yml` so they are enforced on pushes as well.
6. Update `CONTRIBUTING.md` (`uv run pre-commit install`) and tell each owner their slice's
   findings.

## D. CI endpoint testing support (R2-32, R2-33)

1. Add an `endpoint` pytest marker. Tests skip unless `PROPERTYSCOPE_ENDPOINT_BASE_URL` is set, so
   default runs stay Docker-free.
2. Add a small helper in `shared_testkit` (HTTP client with retries/timeouts and a JUnit writer),
   and a step-summary snippet that each `student-N.yml` can copy.
3. Add `scripts/collect_ci_evidence.py`, which uses `gh` to record run URL, SHA and results into
   `evidence/ci/student-N.md`.

## E. Azure deployment (R2-42 to R2-45)

1. **IaC** in `deployment/azure/main.bicep`: resource group resources, ACR, VNet/NSG (443/80 only),
   Ubuntu VM with system-assigned identity, Key Vault, and a budget alert. Parameters live in
   `deployment/azure/*.bicepparam`.
2. **Compose production override** `docker-compose.azure.yml`: images from ACR by SHA, no host
   ports except the edge, secrets read from files rendered from Key Vault, AI URLs unset by
   default.
3. **Scripts** `deployment/azure/deploy.sh` (and a `dev.py cloud` wrapper): `provision`, `push`,
   `deploy`, `smoke`, `ai on|off`. They are idempotent and reusable from a laptop or from Actions.
4. **`cloud-deployment.yml`:** gate on Integration CI success, then OIDC login, build and push
   images, Bicep deploy, VM deploy through `az vm run-command`, then the public smoke test (the
   home page plus each feature's CRUD case). Upload the logs and the report. Use the `production`
   environment.
5. Produce the cloud deployment report automatically from the workflow outputs into
   `evidence/cloud/`.
6. Write ADR-048 and the Azure reference architecture diagram for the report.

## F. Bonus (R2-B1 to R2-B6), in rubric order

1. **B5 Endpoint security:** Caddy TLS (Let's Encrypt on the Azure DNS label) and an
   HTTP→HTTPS redirect; NSG with no SSH or DB ports; nginx rate limits and security headers;
   token or basic auth on operations and AI routes. Validation script: closed ports, redirect,
   401 and 429 responses.
2. **B6 Data security:** every secret in Key Vault, read by the managed identity; encryption at
   host on the disks; databases only on the private Compose network; GitHub OIDC instead of keys;
   detect-secrets in CI. Validation: `az` queries plus a check that no secret appears in images or
   environment dumps.
3. **B1–B4 Cloud AI:** `systemd` units for AI-mode, MCP, RAG and Multi-Agent, toggled by
   `PROPERTYSCOPE_CLOUD_AI`. Prepare the RAG model and ingest all five corpora on the VM. Prove
   each tier from a feature UI and save the outputs to `evidence/bonus/`.

## G. Evidence and report

1. Local deployment report: `stack up`, `ai start --mode combined`, multi-agent, plus a script
   that records multi-terminal logs into `evidence/local/`.
2. Report source `docs/reports/release-2-technical-report.md`, with a builder modelled on
   `build_release1_report.py`.
3. Collect contribution logs, the commit URL, design flows from each owner and the video link.
   Submit by 25 Oct.

## Acceptance

- `uv run python scripts/check.py` passes, including the updated architecture rules and tests for
  the new packages.
- A terminal workflow and a UI workflow (Feature 1) both reach a human decision locally.
- A push to `main` deploys to Azure automatically, and the public smoke test passes with the AI
  tier off.
- All three review modes produce a report and a validation log from real evidence.
