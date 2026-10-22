# Student 5 Release 2 implementation

Owner: Derek Song. Commit IDs and Azure deployment evidence are pending.

## Buyer case action plan

The open buyer-case page mounts the shared Multi-Agent panel. Its proxy root is
`/api/buyer-workspaces/v1/buyer-cases/{case_id}/evidence-reviews`:

| Operation | Route |
|---|---|
| Deployment availability | `GET /capabilities` |
| Workflow descriptor | `GET /template` |
| Start / bounded recent list | `POST /`, `GET /` |
| Read a run | `GET /{run_id}` |
| Human decision | `POST /{run_id}/decision` |
| Cancel | `POST /{run_id}/cancel` |
| History and audit, including cursors | `GET /{run_id}/history` |

The backend pins template `f5-buyer-case-action-plan` and checks the server-selected
owner on every operation. A run must belong to this feature, template and case.
Responses use shared typed contracts, Problem Details and request IDs. Credentials
are sent only to the configured host Multi-Agent Server. Missing credentials or an
unreachable server return a safe unavailable state; database readiness and CRUD do
not depend on it. The existing cloud protection already covers `evidence-reviews`
at any path depth; no Azure edge policy change is needed.

The Planner prepares four evidence steps, the Worker reads case/shortlist, notes,
tasks and bounded research, and the Reviewer checks retrieval, case identity and
coverage. A human can approve, correct, partially accept or reject. Decisions never
create tasks or mutate case records. Existing Release 0 summary and Release 1 chat
routes retain their original tool policies and response contracts.

## Binding tool reads to the selected case

The shared Planner validates tool schemas but does not pin model-produced arguments
to template placeholders (`agents.Planner._validate`). Consequently, a prompt alone
would not prevent an allowed tool from receiving another case ID.

Student 5 therefore adds `buyer.action-plan.context.v1`. Its only argument selects
one of `case`, `notes`, `tasks` or `evidence`. It reads the gateway-supplied
`X-Agent-Run-ID`, loads that run from the Multi-Agent Server, checks its feature and
template, and derives the buyer case from the persisted input before reading records.
The model cannot submit a case identifier. The tool reuses the existing bounded
read functions and ownership checks. It uses the same HTTP path through MCP or direct
mode, without importing shared service implementations or accessing SQLite.

The browser destroys polling on a case change or return to the list. It can reopen
the last run for that case within the page session; case history is never moved to
another case. The shared panel retains recorded progress, human decisions, correction
rounds, activity, keyboard controls and reduced-motion behavior.

## Validation and remaining evidence

Deterministic tests use the real Student 5 routes and client with
`shared_testkit.FakeMultiAgentServer`, including all four decisions, correction,
partial acceptance, cancellation, stale decisions, cross-case refusals, ownership
rechecks, invalid inputs, poisoned dependency responses, outages, token isolation,
request correlation, cursor forwarding and unchanged case records.

Docker and all four host AI services were unavailable during the initial implementation
check. They subsequently became available; the live follow-up below supersedes that
initial limitation. Deterministic doubles remain distinct from live-provider evidence.

Checks on 22 October 2026:

- Student 5: **212 Python tests passed**, **83.69% coverage** (80% gate).
- Student 5 frontend: **27 JavaScript tests passed**.
- Strict Student 5 Mypy: **34 files passed**. Ruff formatting/lint, JavaScript
  syntax, workflow/catalogue validation, architecture, frontend styles and the
  existing Azure operator-protection regression passed.
- Full `uv run --all-packages python scripts/check.py` ran. All source checks and
  feature suites passed. The shared/scripts suite had **2077 passed, 12 skipped,
  1 failed**: `test_dry_run_source_cache_names_the_image_by_content_and_loads_it_on_the_vm`
  in `scripts/tests/test_azure_deployment.py`, because `deploy.sh` requires Docker
  on PATH. No Docker CLI was found in the normal Windows installation locations.
- A real Chromium page served the current Student 5 frontend and Flask API with
  `FakeMultiAgentServer`: list hidden → selected case → start → awaiting human →
  approve → approved → return to list cleared scope. Screenshots at 320, 390, 768
  and 1440 pixels had no horizontal overflow; there were no page errors. These are
  deterministic browser checks, not real provider/agent execution. Scratch captures
  are under ignored `tmp/student5-action-plan-browser/`.
- Git whitespace and lockfile checks passed. No commit or push was performed.

## Live follow-up and endpoint acceptance (22 October 2026)

The local Student 5 frontend was recreated with the required shared assets and
development mounts; the host services loaded the new template and catalogue.
The retained [live workflow evidence](../../docs/release-2/evidence/multi-agent/student-5/README.md)
records model agents, MCP reads, a human correction and final approval across two
rounds. **The Reviewer still recommended partial acceptance and recorded one high
and two medium failures**, including the missing three-to-five action deliverable.
This is a successful execution/human-review trace, not a claim of satisfactory
action generation, cleared findings, real-world source completeness or cloud AI.

Four endpoint tests cover two public functions: buyer-case creation/readback and
inverted-budget rejection, plus case-task creation/readback and unknown-case rejection.
They use the shared bounded HTTP client, validate Problem Details and request IDs,
and clean up only their own created cases. Default test runs skip them without a
configured endpoint origin; they do not require Docker or live AI.

The local execution against `http://127.0.0.1:5500` passed **4/4**:

```text
PROPERTYSCOPE_ENDPOINT_BASE_URL=http://127.0.0.1:5500 uv run --all-packages pytest student-5/tests/endpoints -m endpoint --no-cov -q -rA --junitxml=.propertyscope-runtime/student5-endpoint-tests/results.xml
uv run --all-packages python -m shared_testkit.junit_summary .propertyscope-runtime/student5-endpoint-tests/results.xml --title "Student 5 local endpoint tests (not CI)" --output .propertyscope-runtime/student5-endpoint-tests/summary.md --require-success --min-passed 4
```

The environment assignment above uses POSIX syntax; in PowerShell set
`$env:PROPERTYSCOPE_ENDPOINT_BASE_URL = 'http://127.0.0.1:5500'` before the first command.
These local reports are ignored runtime artifacts, **not GitHub CI evidence**.
The owning `student-5.yml` now runs the endpoint tests after Compose readiness,
publishes the JUnit summary and uploads `student-5-endpoint-tests`. It no longer
starts host AI-mode; empty service credentials and disabled MCP/RAG exercise safe
AI degradation while ordinary CRUD remains usable. Actual GitHub job results and
retained CI evidence await an approved commit/push and a green workflow run.

Security finding cleanup, action-plan output quality, and Azure verification remain
follow-up work. No commit or push has been performed.

### Checks after endpoint/CI integration

- Student 5 Python: **215 passed, 4 skipped** (the opt-in live endpoint tests),
  **83.69% coverage** against the 80% requirement. The separate live endpoint run
  passed **4 tests**, with no skips.
- Student 5 JavaScript: **27 passed**; syntax checks passed.
- Strict Student 5 Mypy: **37 files passed**. Repository-wide Ruff formatting/lint,
  architecture, catalogue/manifest, deployment drift, workspace packaging and
  frontend-style validation passed.
- Focused smoke/deployment/CI consistency regressions: **29 passed, 1 skipped**;
  the skip is Student 3's absent endpoint-test directory.
- The complete gate was run with Docker's installed directory on PATH, resolving
  the earlier Docker-discovery failure. All five feature suites passed. The
  shared/scripts suite had **2078 passed, 10 skipped, 2 failed**:
  `test_probed_status_reads_persisted_tokens_and_flags_foreign_port_holders` and
  `test_corrupt_pid_file_is_not_authority_to_signal` in
  `scripts/tests/test_host_runtime.py`. Both reproduced independently: their
  isolated fixtures do not stub `foreground_process`, so `status()` discovers
  the real foreground AI services and contradicts the tests' stopped/probe-count
  expectations. Shared code was not changed and the running services were not stopped.
- Git whitespace validation passed. Git reported that local pre-commit/pre-push
  hooks are not installed; no hook installation or security-cleanup work was
  included in this milestone.

The revised GitHub workflow and its complete AI-disabled Compose smoke have not
been executed on GitHub yet. Local endpoint results and mocked smoke regressions
must not be relabelled as a successful hosted CI job.

## Action-plan output correction (template v2, 22 October 2026)

Diagnosis: the shared Worker contract exposes only `summary` and per-step
`findings`; its system prompt asks for evidence findings. Student 5's v1 objective
requested proposed actions without specifying their location. The feature-owned
v2 objective explicitly places three to five numbered, imperative follow-ups in
the existing summary, with at most 30 words each. It keeps per-step findings
factual, distinguishes proposed follow-ups from workflow approval, and retains
untrusted-input, source-attribution, no-valuation/advice/purchase-recommendation
and no-record-change protections. Human-review guidance flags absent actions
instead of inventing them. Shared prompts, contracts and runtime were not modified.

Regression tests pin this output convention and preserve three-, four- and
five-action summaries through the real Student 5 proxy using the shared HTTP fake,
without changing case records. These are deterministic contract/transport tests,
not evidence that a model will always follow the instructions.

After Derek restarted only the foreground Multi-Agent Server, the public Student 5
API reported template v2. A new real model/MCP run,
`429fbe07-8dd8-48d0-b565-62d6536c4d9c`, produced **five actions** with word counts
**14, 16, 19, 15, 13** and no tool telemetry or raw UUIDs in the actions. All four
MCP reads succeeded. The Reviewer confirmed that the action deliverable was present
and grounded, with **only one medium partial-evidence-coverage failure** and a
**partial** recommendation. There was no model fallback. The run remains
**awaiting_human**; no decision was submitted on Derek's behalf.
The [reviewed export](../../docs/release-2/evidence/multi-agent/student-5/429fbe07-8dd8-48d0-b565-62d6536c4d9c/summary.md)
retains the actual output, references and limitation. No browser-rendering or Azure
verification was performed for this prompt-only correction.

Checks: **219 Student 5 Python tests passed, 4 opt-in endpoint tests skipped**;
**83.69% coverage**; **27 JavaScript tests passed**; strict Mypy passed **37 files**.
Workflow validation, formatting, lint, syntax, architecture, catalogue, deployment
drift, packaging and frontend-style checks passed. The full gate was run once:
the same two shared host-runtime tests failed because real foreground services
were detected (**2078 shared/scripts tests passed, 10 skipped**). It also initially
found one overlong test assertion; that assertion was wrapped and repository-wide
Ruff passed on rerun. The full gate is not claimed green, and shared tests were
not changed or bypassed. Git whitespace validation passed.

Security review was limited to the changed files, exported evidence and existing
report. That report still lists **59 pending-owner Student 5 findings** (assertions,
credential-string detection, URL-opening checks and formatted SQL); this correction
does not claim those are resolved. Security cleanup, human review, hosted CI evidence
and Azure verification remain separate follow-ups. No commit, push or merge occurred.

## Human decision and security cleanup (22 October 2026)

The actual v2 run is now **partially_accepted**. The user's terminal decision
accepted `case`, `notes`, and `tasks`, but not `evidence`, with the note that research
remains incomplete and needs verification. The recorded self-reported actor is
literally `Yes`; it has not been changed or presented as authenticated identity.
The reviewed [run export](../../docs/release-2/evidence/multi-agent/student-5/429fbe07-8dd8-48d0-b565-62d6536c4d9c/summary.md)
was refreshed from the server after checking the files for credentials and machine
paths. No decision was made by the coding agent.

Security changes:

- Replace database validation/repository and Compose-smoke assertions with explicit
  exceptions/checks that also operate under Python optimisation.
- Validate dependency URLs as HTTP(S), without embedded credentials, fragments or
  whitespace/control characters; reject redirects rather than forwarding internal
  credentials to an unexpected destination. Timeouts and bounded API reads remain.
- Enforce fixed table/column allowlists before constructing dynamic SQL; bind all
  record values. Add line-specific reasons for the remaining safe SQL identifiers
  and HTTP request construction, and for header-name credential false positives.
- Remove only Student 5's seven temporary root Ruff ignore entries, with explicit
  user approval. Other students' configuration, source and shared runtime semantics
  were not changed. No dependencies or lockfile were changed.
- Add regression tests for rejected URLs, all five redirect statuses, rejected SQL
  identifiers, hostile literal values, and non-optimisable smoke checks. A rejected
  fake credential URL is explicitly marked as a test-only secret-scan false positive;
  the shared secrets baseline was not edited.

The supported scan command was:

```text
uv run --all-packages python -m scripts.security report --check --output-dir student-5/docs/security-evidence
```

The [actual security report](security-evidence/pre-commit-report.md) and accompanying
Ruff, detect-secrets and pip-audit JSON are retained. The tool scans the whole
repository; output was written under Student 5 rather than replacing Shared's
assessment report. Student 5 has **0 open, 0 pending-owner findings and 17 justified
line-level annotations**, superseding the earlier 59 pending-owner findings.
Credential scanning passed with **0 new secrets**. The dependency scan audited
**128 locked packages**, with **0 unaccepted vulnerabilities**; the existing
repository policy still accepts **42 risk entries across 2 packages**. No new
dependency risk exception was introduced, and this is not a claim of zero known
vulnerabilities or zero findings in other slices.

Validation: **238 Student 5 Python tests passed, 4 opt-in endpoint tests skipped**;
**83.58% coverage** (80% requirement); **27 JavaScript tests passed**; strict Student 5
Mypy passed **37 files**. All **4 live public CRUD endpoint tests passed** separately
against the running stack after the security changes, cleaning up only their own
temporary cases. The revised AI-disabled full Compose smoke was not run against
the user's stack because it intentionally mutates seeded CI data. Ruff formatting,
lint, architecture, packaging, generated contracts/deployment, catalogue, syntax and
frontend-style checks passed. The complete gate ran **153 commands in 190.5 seconds**;
all five feature suites and source checks passed. Its only failing command was the
shared/scripts suite: **2078 passed, 10 skipped, 2 failed**, again
`test_probed_status_reads_persisted_tokens_and_flags_foreign_port_holders` and
`test_corrupt_pid_file_is_not_authority_to_signal`. They detect the real foreground
AI services rather than isolating that dependency. No shared test was weakened,
skipped or changed, and the services were left running. The full gate therefore
remains red, despite the successful Student 5 and security checks.

Hosted CI evidence, Azure verification and an approved commit/push remain pending.
Local Git hooks remain uninstalled; passing scans here does not claim a hook ran
during a commit. No commit, push, volume removal or stack reset was performed.

## Final pre-commit validation (22 October 2026)

The clean-checkout CI smoke now creates the state file's parent directories before
writing. Two parameterised regressions cover missing/existing directories and
restart readback, using fake HTTP responses without modifying the user's stack.
An overlong fake-credential test annotation was shortened without changing its
secret-scan justification.

The user then authorised correcting the two shared test-isolation failures. Only
`scripts/tests/test_host_runtime.py` changed: each affected test explicitly simulates
no foreground process, instead of discovering real developer listeners. All original
assertions remain, and the separate foreground-service recognition tests still
exercise that behaviour. Shared runtime code, Student 1-4 source, services and data
were not changed or stopped. All **41 tests** in that module passed.

The complete `uv run --all-packages python scripts/check.py` gate then **passed all
153 commands in 169.9 seconds**, superseding the earlier red gate results:

- Shared/AI/scripts: **2080 passed, 10 skipped**, **93.49% coverage**.
- Student 5: **240 passed, 4 opt-in endpoint tests skipped**, **83.58% coverage**.
- All five feature suites, frontend JavaScript tests, syntax checks, Ruff formatting
  and lint, strict canonical Mypy, architecture, packaging, generated contract and
  deployment drift, model/catalogue and frontend-style checks passed.
- Git whitespace checking passed. The earlier separate **4 live Student 5 endpoint
  tests** and **27 Student 5 JavaScript tests** remain recorded above; the full gate
  does not substitute for a GitHub Actions execution or Azure verification.

The full gate completed before this documentation-only result was appended. The
final file review found no additional blockers. Commit IDs, hosted CI evidence and
Azure verification remain pending; hooks are still not installed. No staging,
commit, push or merge was performed.

## Approved commit preparation

After the green gate and final review, the user approved creating the Release 2
commit on `feature/student-5-release-2`, without pushing. Both `pre-commit` and
`pre-push` hooks were installed using the documented command; this supersedes the
earlier notes that hooks were not installed. The commit-time hooks are enabled,
not bypassed. The resulting commit ID and hook outcome are reported after the
commit command; hosted CI and Azure evidence remain pending.

The first commit attempt was correctly blocked by detect-secrets: a public Pillow
advisory (`CVE-2026-112896` / `GHSA-pchr-8j38-3x4p`) embedded an encoded TIFF proof
of concept in the saved pip-audit JSON. It was not a project credential. Only that
advisory description in the retained copy was summarised and linked to its public
source; the encoded payload was omitted. Package/advisory identifiers, fix versions,
audit results and accepted-risk policy are unchanged. The saved pip-audit JSON is
therefore an evidence copy with this one description sanitised, not byte-for-byte
raw scanner output. No secret baseline or hook was weakened to permit the commit.
