# Agentic-loop review modes

Release 2 adds three review modes to the shared, non-containerised agentic loop (R2-20 to R2-23,
decision D5). They sit beside the Release 1 `ai validate mcp|rag` modes, which are unchanged.

| Mode | Command | Reviews | Prompt set |
|---|---|---|---|
| Multi-Agent Workflow Review | `uv run scripts/dev.py ai review multi-agent` | Workflow histories and coordination audits exported by the Multi-Agent Server | `review-multi-agent.v2` |
| Testing Report Review | `uv run scripts/dev.py ai review testing` | Pre-commit security scans and each student's post-commit CI endpoint evidence | `review-testing.v2` |
| Cloud Deployment Report Review | `uv run scripts/dev.py ai review cloud` | Cloud deployment report, workflow logs and public smoke output | `review-cloud.v2` |
| Human release decision | `uv run scripts/dev.py ai review decide ...` | Records a named person's decision on the latest cloud review | n/a |

Each mode writes `docs/release-2/evidence/reviews/<mode>-review.md` and appends one line per run to
`docs/release-2/evidence/reviews/<mode>-validation-log.jsonl`.

## How a review runs

```text
evidence files ──▶ collector ──▶ bundle (inputs + SHA-256, checklist, facts)
                                   │
                                   ▼
             AI-mode run: feature_key agentic-loop, prompt set review-<mode>.v2
             Plan ─▶ Act (review.evidence.v1) ─▶ Observe ─▶ Adapt (review output)
                                   │
                                   ▼
            schema + evidence validation ─▶ verdict = stricter(model, checklist)
                                   │
                                   ▼
           reviews/<mode>-review.md  +  reviews/<mode>-validation-log.jsonl
```

1. **Collect.** The mode's collector reads only allowlisted paths below `--evidence-dir`
   (default `docs/release-2/evidence`). It never follows symlinks or leaves the root, reads at
   most 1 MiB per file (512 KiB from the end of each log), 16 MiB and 150 files in total, and
   records every input with its status (`read`, `missing`, `oversize`, `invalid`), size and
   SHA-256. Oversize files are hashed but not parsed. Missing or unreadable evidence becomes a
   failed check with an "Evidence not submitted" or "Evidence gap" detail; it never crashes the
   review.
2. **Check.** The collector builds a deterministic checklist. Each check is `required` or
   advisory, names its `owner` (`shared` or `student-N`) where the mode declares one, cites the
   evidence that decided it, and is listed in a stable order. A check whose prerequisite failed
   is `blocked`: it was not evaluated, and `blocked_by` names the failed root check (see
   [Owners and blocked checks](#owners-and-blocked-checks)). A failed or blocked required check
   means `fail`; a failed or blocked advisory check means at least `pass_with_risks`.
3. **Review through the loop.** The bundle becomes the objective of an AI-mode run with
   `feature_key` `agentic-loop`, the mode's prompt set and a one-tool allowlist. The planner
   (`review-planner/v1`) plans the read-only `review.evidence.v1` tool, which reads the bundle
   back from the durable run store, validates it and returns a compact checklist projection
   with `path#sha256:<digest>` evidence references, blocked checks grouped under their root and
   per-owner coverage. The mode's reviewer prompt (`review-<mode>/v2`, planner
   `review-planner/v2`) then returns the review: one finding per root cause, blocked checks
   summarised per owner, and "owner has not submitted X" rather than a code change when evidence
   is absent. The `v1` prompt sets stay registered so earlier runs remain reproducible.
4. **Validate.** AI-mode's completion validator checks the review against the output schema and
   the bundle inside the loop's bounded repair: every `evidence_refs` value must be a check ID or
   input path from the bundle (optionally with a `#` or `:` anchor), and the verdict must not be
   more lenient than the checklist. The CLI validates the returned review again.
5. **Write.** The report and a log line are written. The final verdict is the stricter of the
   model verdict and the checklist verdict.

The run is created through AI-mode's HTTP API (`POST /api/v1/agent-runs`) using the managed host
token, so it is persisted and visible in AI-mode **Activity history** like every other loop run.
AI-mode rejects review prompt sets for any other feature key, any other prompt set for
`agentic-loop`, a wider tool allowlist, and an objective that is not a valid bundle.

### Engines

| Engine | When | Model | In Activity history |
|---|---|---|---|
| `ai-mode` | Default | Configured AI-mode provider | Yes |
| `deterministic` | `--deterministic` | None: scripted checklist decisions | No (temporary store) |
| `deterministic-fallback` | `--fallback-deterministic` after AI-mode failed | None | The failed AI run is; the fallback is not |

`--deterministic` mirrors `ai validate`: it runs the production `AgentRunner`, prompt registry,
review tool and completion validator in-process with a temporary SQLite store and scripted
decisions (`deterministic-review` / `checklist-review.v1`). Its findings are the root causes,
required ones first: one per failed check, except that owners whose evidence was not submitted
share one "Evidence not submitted by ..." finding per check kind, with the checks it blocked
counted per owner. Beyond the schema's 30 findings, a final finding names the rest. Its
recommendations are the fixed remediation per check kind, attributed to the owner when evidence
is missing, and its verdict is exactly the checklist verdict. Use it in tests, CI and offline
work. CI refuses the live mode, because AI-mode stays disabled there.

Without `--deterministic`, an unreachable AI-mode, a failed or timed-out run, or a review that
fails validation stops the command with a clear message and appends a `review_unavailable` log
line. `--fallback-deterministic` instead writes a deterministic review, labelled with the reason
and the failed AI-mode run ID.

### Owners and blocked checks

The multi-agent and testing reviews are group-wide: they check evidence from Shared and from
each student. Every check names its owner (`shared`, `student-1` ... `student-5`), and each
student's checks depend on one gate check that only asks whether that student's evidence was
submitted and readable (`student-N.evidence`, `ci.student-N.evidence`). When the gate fails,
the student's other checks are recorded as `blocked` with `blocked_by` naming the gate, instead
of failing one by one with the same cause. A present but wrong file still passes the gate, so
every dependent check is evaluated against it.

| Status | Meaning |
|---|---|
| `passed` | The evidence shows the control works |
| `failed` | The evidence is missing or shows a defect; this is a root cause |
| `blocked` | Not evaluated because the `blocked_by` root check failed |

Verdict: a blocked check was never demonstrated, so it weighs like a failure. A blocked required
check means `fail`, a blocked advisory check at least `pass_with_risks`. The group-wide review
therefore cannot pass while a required owner has not submitted evidence. The report attributes
that to the owner instead of the behaviour under review:

- **Coverage by owner** lists each owner's passed, failed and blocked counts and a status:
  `complete`, `evidence not submitted` (every input the gate cites is missing), `evidence
  incomplete` (the gate failed on a partial or unreadable submission), `blocked by another
  owner's evidence`, `required checks failing` or `advisory gaps only`.
- A **Verdict basis** line under the summary names the owners behind the verdict and the
  complete owners, for example "fail — evidence not submitted for student-2 ... student-5.
  Complete: student-1."
- **Findings** are grouped by root cause, and the checklist collapses each root's blocked checks
  into one row.

`scripts/devtools/review/checklist.py` documents the collector API: `Checklist.add(...,
owner=..., prerequisite=...)`. A prerequisite may be one check ID or several; the blocked
check's `blocked_by` always names the root failure, and its owner defaults to the
prerequisite's. `shared_contracts.evidence_review.owner_coverage` derives the coverage table.

## Command reference

```text
uv run scripts/dev.py ai review multi-agent [--deterministic | --fallback-deterministic]
uv run scripts/dev.py ai review testing     [--evidence-dir DIR] [--out DIR] [--timeout SECONDS]
uv run scripts/dev.py ai review cloud       [--ai-mode-url URL] [--env-file PATH]
uv run scripts/dev.py ai review decide --decision {release,hold,rollback} \
    --decider NAME --rationale TEXT [--acknowledge-failed-review]
```

| Option | Default | Meaning |
|---|---|---|
| `--evidence-dir` | `docs/release-2/evidence` | Evidence root |
| `--out` | `<evidence-dir>/reviews` | Where the report and log are written |
| `--deterministic` | off | In-process loop, no model |
| `--fallback-deterministic` | off | Fall back to the deterministic review if AI-mode fails |
| `--ai-mode-url` | `http://127.0.0.1:$AI_MODE_PORT` | Host AI-mode URL; the token comes from `AI_MODE_SERVICE_TOKEN` or `.propertyscope-runtime/host/ai-mode.token` |
| `--timeout` | 300 | Seconds to wait for the run; also bounds the run's time budget |

A review command exits 0 for `pass` or `pass_with_risks` and 1 for `fail` or an error. A live
review needs `uv run scripts/dev.py ai start` with a provider key; the review does not need MCP,
RAG or the Compose stack.

## Evidence each collector expects

Producers should write these exact paths. Field names in brackets are accepted synonyms.

### `multi-agent`

For each `student-1` to `student-5`, files up to three levels below
`multi-agent/student-N/`:

| File | Format |
|---|---|
| `workflow_history.jsonl` (required) | One `WorkflowHistoryEntry` per line: `sequence`, `run_id`, `at` (timezone-aware ISO 8601), `from_state` (`null` first), `to_state`, `role`, `actor`, `reason` |
| `coordination_audit.jsonl` (required) | One `CoordinationAuditEntry` per line: `sequence`, `run_id`, `at`, `event`, `role`, `actor`, `detail` |
| `*.json` (optional) | A run or template export; `allowed_tools` (or `template.allowed_tools`) supplies the tool allowlist |

Every check is owned by `student-N`. `student-N.evidence` is the gate: when it fails, the other
six checks of that student are `blocked` by it. A student who exported nothing gets the detail
"Evidence not submitted"; a partial or unreadable export is an "Evidence gap" naming the file.

| Check | Required | Passes when |
|---|---|---|
| `student-N.evidence` | yes | Both files exist, parse, and contain at least one run (gate) |
| `student-N.stages` | yes | Every run that reached `awaiting_human` went `planning → working → reviewing → awaiting_human` and has planner, worker and reviewer audit events; at least one did |
| `student-N.human-decision` | yes | At least one run reached a human decision, each with a `decision.recorded` event whose `role` is `human` and which has an `actor` and `at` |
| `student-N.transitions` | yes | Sequences are contiguous, each `from_state` is the previous `to_state`, every transition is legal in the Multi-Agent Server state machine, and timestamps never go backwards |
| `student-N.tool-allowlist` | yes | Every `tool.call` names a tool in the run's recorded `allowed_tools` (from any audit `detail.allowed_tools`, such as `run.created`, or an exported template) and no recorded `side_effect` is a write |
| `student-N.correlation` | yes | History and audit contain the same run IDs |
| `student-N.handoffs` | advisory | `agent.handoff` events record `planner→worker`, `worker→reviewer` and `reviewer→human` (`detail.from`/`detail.to` [`from_role`, `to_role`]) |

### `testing`

| File | Format |
|---|---|
| `security/pre-commit-report.md` | Names Ruff, detect-secrets and pip-audit; records the scanned commit SHA; explains each accepted finding by Ruff code and file, or by vulnerability ID or alias |
| `security/ruff-security.json` | `ruff check --select S --output-format json` (a list) |
| `security/detect-secrets.json` | `detect-secrets` scan or audited baseline (`{"results": {path: [...]}}`) |
| `security/pip-audit.json` | `pip-audit --format json` (`{"dependencies": [{"name", "version", "vulns"}]}`) |
| `ci/student-N.md` | The Actions run URL (`https://github.com/<owner>/<repo>/actions/runs/<id>`), the 40-character commit SHA, a line or table row that starts with `Conclusion` (`Conclusion: success` or `\| Conclusion \| success \|`), and the `shared_testkit.junit_summary` totals line and per-test table. `scripts/collect_ci_evidence.py` writes exactly this |
| `ci/student-N/run.log` | The retained log of the endpoint-test steps, also written by `collect_ci_evidence.py`; the last 512 KiB are read |

The `security.*` checks are owned by `shared` and have no gate: each scan file is judged on its
own. Each `ci.student-N.*` check is owned by `student-N`; `ci.student-N.evidence` is the gate,
so a student who has not submitted `ci/student-N.md` has one failed check ("Evidence not
submitted", with the `collect_ci_evidence.py` command) and five blocked ones.

| Check | Required | Passes when |
|---|---|---|
| `security.report` | yes | The report exists and names all three scans |
| `security.traceability` | advisory | The report records a commit SHA |
| `security.ruff` | yes | Every Ruff finding is explained in the report (code and file) |
| `security.ruff-owners` | advisory | With security-report JSON, no finding is still temporarily allowed as `pending-owner` |
| `security.secrets` | yes | Every potential secret is audited as `"is_secret": false` |
| `security.dependencies` | yes | Dependencies were audited and every vulnerability ID or alias is explained in the report |
| `security.dependencies-clean` | advisory | No known vulnerability remains, even an accepted one |
| `ci.student-N.evidence` | yes | `ci/student-N.md` exists and was read (gate) |
| `ci.student-N.run` | yes | Run URL and commit SHA are present |
| `ci.student-N.green` | yes | The conclusion is `success` |
| `ci.student-N.endpoints` | yes | At least two endpoint tests passed and none failed or errored |
| `ci.student-N.junit` | advisory | The JUnit totals lines, summed over every report, show at least two tests and no failures or errors |
| `ci.student-N.log` | advisory | The run log exists and every pytest result line in it passed with no failures or errors |

### `cloud`

| File | Format |
|---|---|
| `cloud/cloud-deployment-report.md` | Names the public URL and the deployed 40-character commit SHA |
| `cloud/smoke*.json` | `{"base_url", "commit_sha", "ai_enabled": false, "images": {service: "registry/name:<commit sha>" or "...@sha256:<digest>"}, "checks": [{"name", "category": "frontend" \| "crud" \| "ai_disabled", "feature": "student-N", "passed": true}]}`. `passed` may be `status`/`outcome`/`result` set to `passed` or `success`; `feature` may be `feature_key` or `student` |
| `cloud/*.log`, `cloud/logs/**/*.{log,txt}`, `cloud/workflow-logs/**/*.{log,txt}` | Deployment workflow logs |

`cloud/release-decision.md` is output, not input: it is never reviewed, so recording a decision
does not invalidate the review it refers to.

| Check | Required | Passes when |
|---|---|---|
| `cloud.report` | yes | The report records a URL and a commit SHA |
| `cloud.smoke` | yes | Smoke output exists and every case passed |
| `cloud.frontend` | yes | A frontend case passed |
| `cloud.crud.student-N` | yes | That feature's CRUD case passed |
| `cloud.ai-disabled` | yes | `ai_enabled` is `false`, or every `ai_disabled` case passed |
| `cloud.images` | yes | Every image is tagged with the smoke commit SHA (at least 7 characters) or pinned by digest |
| `cloud.commit-consistency` | yes | Report and smoke output name the same commit |
| `cloud.workflow` | yes | At least one readable log and no `##[error]`, non-zero exit or `ERROR` line |
| `cloud.log-secrets` | yes | No private key, storage account key, provider or GitHub token, AWS key or client secret pattern in the logs |
| `cloud.https` | advisory | The smoke base URL uses HTTPS |

## Review output schema

`shared_contracts.evidence_review.EvidenceReviewOutput`, published as
`shared/contracts/schemas/evidence-review-output.v1.schema.json`. The bundle is
`evidence-review-bundle.v1.schema.json`.

```json
{
  "summary": "One to three plain sentences",
  "findings": [
    {"severity": "info|low|medium|high|critical", "area": "ci.student-2",
     "message": "Specific observation", "evidence_refs": ["ci.student-2.green", "ci/student-2.md"]}
  ],
  "risks": [{"severity": "medium", "description": "Remaining risk", "mitigation": "Action"}],
  "recommendations": ["Owner-actionable step"],
  "verdict": "pass|pass_with_risks|fail"
}
```

## Report and log

The report is written to paste into the technical report. It starts with the verdict, the
checklist and model verdicts, the passed/failed/blocked check counts, the engine, the review ID,
the loop run ID, request ID, prompt set and prompt versions, provider and model, phases, times,
evidence root and bundle SHA-256. It then gives the summary and a **Verdict basis** line,
**Coverage by owner** (when the mode declares owners), findings grouped by root cause, risks,
recommendations, the checklist (each root's blocked checks collapsed into one row), every input
with its status, size and SHA-256, validation notes and a compact table of the collected facts
(per-owner facts as one column per owner). The full facts are in the validation log. The cloud
report ends with a **Human release decision** section, pending until `decide` runs.

Each validation-log line is one compact JSON object. A completed review has `"event":
"review_completed"` and the keys `schema_version`, `review_id`, `mode`, `prompt_set`, `prompts`,
`engine`, `run_id`, `request_id`, `provider`, `model`, `started_at`, `finished_at`,
`duration_ms`, `evidence_root`, `bundle_sha256`, `objective_compacted`, `inputs` (path, status,
sha256, bytes), `checks` (id, status, required, plus `owner` and `blocked_by` when set),
`checks_passed`, `checks_failed`, `checks_blocked`, `owners` (the coverage table), `facts` (the
complete collected facts), `phases`,
`tool_evidence`, `model_output_valid`, `validation_detail`, `fallback_reason`, `findings`, `risks`,
`recommendations`, `model_verdict`, `checklist_verdict`, `verdict`, `report_path` and
`report_sha256`. A failed attempt adds a `review_unavailable` line with `error_code` and the
run ID, if one exists. `decide` adds a `human_release_decision` line to the cloud log. Log
schema `1.1` added `owner`, `blocked_by`, `checks_blocked`, `owners` and `facts`; `1.0` lines
written earlier remain valid and are read the same way.

## Human release decision

```text
uv run scripts/dev.py ai review cloud
uv run scripts/dev.py ai review decide --decision release --decider "Matthew Shelton" \
    --rationale "All five CRUD cases passed with the AI tier off."
```

`decide` reads the latest `review_completed` line in `cloud-validation-log.jsonl`, re-hashes the
cloud evidence and refuses if anything changed since that review. It refuses `release` over a
`fail` verdict unless `--acknowledge-failed-review` is given, and records that override. It writes
`cloud/release-decision.md` (decision, decider, time, review ID, run ID, verdict, prompt set,
bundle hash, rationale and the evidence hashes), appends a `human_release_decision` log line, and
replaces the pending section of `cloud-review.md`. The review supports the decision; the named
person makes it.

## Safety boundaries

- Evidence text, file names and facts are untrusted data. The prompts say so; the review tool
  takes no arguments and reads only the run's own objective; the model cannot add tools.
- The loop never deploys, merges, approves or publishes anything.
- Reports contain hashes, check results and short excerpts, never secrets: log lines that match a
  secret pattern are reported by line number only.
- A review is evidence about the files it hashed. Re-run it after the evidence changes.

## Tests

```text
uv run pytest scripts/tests/test_review_modes.py ai-services/ai-mode/tests/test_release_review.py shared/contracts/tests/test_evidence_review.py -q
```

They cover each mode on complete fixture evidence (`scripts/tests/review_fixtures.py`), missing,
invalid, oversize and out-of-root inputs, the deterministic loop, a live run through the real
AI-mode app with a scripted provider, schema-invalid and evidence-inventing model output, fallback,
timeouts, unreachable AI-mode, the CLI and the decision guards, plus owners and blocked checks:
the checklist prerequisite API, owner coverage, a partial submission (student-1 complete, the
others missing) reading as one root cause, the collapsed checklist and the facts table. They need
no network, Docker or provider credentials.
