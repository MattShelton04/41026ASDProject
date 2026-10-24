# Release 2

Release 2 keeps everything from Release 1 and adds:

- a shared, non-containerised Multi-Agent Server (Planner → Worker → Reviewer → Human Review)
- three new agentic-loop review modes
- pre-commit security scans
- CI tests for two endpoints per student
- deployment of the integrated application to **Azure**

In the baseline cloud deployment, AI-mode, MCP, RAG and Multi-Agent are disabled. Enabling them
is bonus work. The showcase is on 23 October 2026 and the report (`group-20.pdf`) is due on
25 October 2026.

- [Requirements](requirements.md): the brief and rubric restated as numbered requirements, report
  contents and showcase coverage.
- [Implementation plan](implementation-plan.md): key decisions, target architecture, workstreams,
  timeline, evidence layout and risks.
- [Agentic-loop review modes](review-modes.md): `dev.py ai review {multi-agent,testing,cloud}`,
  the evidence each mode reads, the review output schema, the validation logs and the human
  release decision.
- [Responsibilities by part](parts/README.md): what Shared and each feature must deliver, with a
  plan for each part:
  [Shared](parts/shared.md) · [F1](parts/feature-1.md) · [F2](parts/feature-2.md) ·
  [F3](parts/feature-3.md) · [F4](parts/feature-4.md) · [F5](parts/feature-5.md)
- [Showcase runbook](showcase-runbook.md): the rehearsable script for the 10-minute video and the
  live showcase, with segment owners and timings, exact commands, preparation and fallbacks.
- [Showcase checklist](showcase-checklist.md): one page listing what the overview and each
  feature slice must show, mapped to the rubric.

Evidence collected for the report goes in `evidence/`, as described in the implementation plan.

## Status (24 October 2026)

| Area | State | Where |
|---|---|---|
| Multi-Agent Server (Shared A1–A7) | Done: contracts, state machine, model and deterministic agents, SQLite and JSONL audit, HTTP API, CLI, `FakeMultiAgentServer` | [README](../../ai-services/multi-agent-server/README.md), [ADR-047](../architecture/decisions/ADR-047-multi-agent-server.md) |
| Shared multi-agent panel (A8) | Done: feature-agnostic "mission relay" panel (live lanes, now line, one-question decision, drawers, replay of recorded runs) with the proxy contract every feature implements, including incremental history cursors | [`shared/frontend/multi-agent/`](../../shared/frontend/multi-agent/README.md) |
| Review modes (B) | Done, with `v2` prompts. Every group-wide check names its owner, a student's checks are `blocked` behind one evidence gate, and each report shows **Coverage by owner** and a **Verdict basis**. The committed reviews were regenerated on 24 October with `v2` prompts through live AI-mode: testing `pass_with_risks` (36 of 37; the one failure is Shared's advisory `security.dependencies-clean` check on the accepted pip-audit risks), multi-agent `pass` (35 of 35, Students 1–5 complete) and cloud `pass` (18 of 18) | [review-modes.md](review-modes.md), [`evidence/reviews/`](evidence/reviews/README.md) |
| Pre-commit security (C), endpoint testing (D) | Done. The committed report was regenerated on `main` at `7b3fb437` (23 October, 23:56 UTC) and passes: Ruff 0 open and 0 pending owner, detect-secrets 0 new, pip-audit 0 open with 55 accepted risks in 2 packages. (The earlier 16 October report scanned a branch commit with uncommitted changes and listed 85 pending-owner Ruff findings) | `.pre-commit-config.yaml`, [`evidence/security/`](evidence/security/pre-commit-report.md), [`shared/testkit`](../../shared/testkit/README.md) |
| Local deployment report (G1) | Done: `scripts/capture_local_deployment.py`, 111 of 111 live checks on `main` at `7b3fb437` (captured 23 October, 23:56–23:57 UTC), six terminal logs with every host service in its own foreground terminal (`dev.py ai serve SERVICE`), and a real-provider terminal Multi-Agent run. The RAG and MCP logs carry this capture's request IDs | [`evidence/local/`](evidence/local/README.md) |
| CI release gate (E4) | Done: `cloud-deployment.yml` runs `verify-ci` (Integration CI and Student 1–5 CI green for the deployed commit, `scripts/verify_release_gate.py`) and `build-validate` (every image built and the Azure Compose model validated, `scripts/validate_release_images.py`) before its `deploy` job. In run 40041985429 the gate passed with Integration CI #480 and Student 1–5 CI all `success` on `7b3fb437` (`identical`), and 18 images were built and validated | [`cloud-deployment.yml`](../../.github/workflows/cloud-deployment.yml), [`evidence/cloud/`](evidence/cloud/README.md) |
| Technical report (G2) | Builder and source done; every owner's sections are written, including the cloud figures, deployment scripts and job timings, the 24 October release decision and the B1–B6 bonus claim. Students 2 and 4 filled their sections in #163 and #166; Students 3 and 5 have filled theirs. Still open: the showcase video URL and the participation statements (a later commit), then the final `--final --baseline` report build | [`docs/reports/`](../reports/README.md), `scripts/build_release2_report.py --status` |
| Azure (E/F) | **Provisioned and deployed** on 17 October: *Azure for Students*, `newzealandnorth`, `Standard_D4as_v4`. **Current AI-off evidence (24 October)** from [run 40041985429](https://github.com/MattShelton04/41026ASDProject/actions/runs/40041985429) on `main` at `7b3fb437` (dispatched 23 October 23:51 UTC, finished 24 October 00:09 UTC; `production` approved by MattShelton04; provision skipped): gate passed, 21/21 containers, smoke 37/37 with 0 skipped (create, read and delete for all five features against real Feature 1 releases), AI `503 ai_disabled`, B5 58 PASS and 0 FAIL, B6 43 PASS and 0 FAIL from a laptop (00:13 UTC), `ai review cloud` pass 18/18 through live AI-mode (review `be5514a8`), human release decision **RELEASE** (00:14 UTC). Feature 1 held six accepted releases at deploy time and no demonstration data (#153, #154). Earlier evidence, kept: run [39112162750](https://github.com/MattShelton04/41026ASDProject/actions/runs/39112162750) (`3c25c083`, 18 October) and the 15 portal and 5 app screenshots taken after it, which were not retaken. The Cloud AI Tier workflow (`cloud-ai.yml`, #156) turned the AI tier on for B1–B4 (18 and 22 October) and it was turned off again afterwards. Automatic deployments are paused (`AZURE_AUTO_DEPLOY=false`); the VM is currently deallocated (it is also deallocated nightly). Bicep compiles and lints cleanly (`deployment/azure/validate-iac.sh`, Integration CI job `iac-lint`) | [deployment/azure](../../deployment/azure/README.md), [`evidence/cloud/`](evidence/cloud/README.md) |
| Showcase (G) | Runbook written: segments, timings, commands and fallbacks. Students 2–5 write their own segments | [showcase-runbook.md](showcase-runbook.md) |
| Feature 1 (F-1..F-9, F-11) | Done: workflow manifest (template v2), `/release-reviews` proxy routes with input validation, "Readiness review" UI (disabled with a visible reason where the deployment has no AI tier), demonstration-data notice, endpoint tests, terminal and UI evidence, CI evidence (run #415 on `7b3fb437`, 23 endpoint tests passed and 2 skipped on each origin; earlier run #387 on `817ef779`), report sections. F-9 done on Azure: Feature 1 CRUD passes the cloud smoke test against real releases, and the suburb-map spatial API serves Feature 3 (#151). F-10: the Feature 1 release review ran on Azure as B4 (run `2058658b`, [`evidence/bonus/`](evidence/bonus/README.md)); UI captures with the AI tier on, and the human decision on that run, are in [`evidence/bonus/ui/`](evidence/bonus/README.md#ui-captures-19-october) (19 October) | [student-1 README](../../student-1/README.md), [`evidence/ci/student-1.md`](evidence/ci/student-1.md) |

### Remaining work

| Item | Owner | Notes |
|---|---|---|
| Evidence refresh at the freeze | Matthew | **Evidence done** on `main` at `7b3fb437` (23–24 October): security report, Student 1–5 CI, local deployment report, the three reviews and the cloud evidence (the [ordered checklist](#evidence-refresh-at-the-freeze-on-clean-main) below). Still open: the final `--final --baseline` report build, after the showcase video URL and participation statements land in a later commit |
| Azure evidence and release decision (R2-45) | Matthew | **Done.** AI-off evidence and the cloud review are in [`evidence/cloud/`](evidence/cloud/README.md) (run 40041985429). The review ran through live AI-mode (review `be5514a8`, loop run `ce7e9072`, pass 18/18). Human decision recorded on it: **RELEASE** by Matthew Shelton at 2026-10-24T00:14:49Z ([`release-decision.md`](evidence/cloud/release-decision.md)). The earlier decision (RELEASE, 19 October, deterministic review `44929d5d` on run 39112162750) is superseded. The portal and app screenshots are the earlier 18 October set. Optional: add the Key Vault secret names to `portal/12` (needs a temporary firewall rule) |
| Cloud gate | Matthew | **Addressed** by the `verify-ci` and `build-validate` jobs (see the status table) |
| Bicep compile | Matthew | **Done**: `deployment/azure/validate-iac.sh` builds and lints every template; Integration CI runs it with `--strict` in the `iac-lint` job |
| Bonus B1–B6 | Matthew | **Claimed in report Section 13**, pending demonstration in the showcase. B5: passes in run 40041985429 (58 PASS, 0 FAIL, [`evidence/cloud/endpoint-security.txt`](evidence/cloud/endpoint-security.txt)). B6: passes from a laptop at 00:13 UTC on 24 October (43 PASS, 0 FAIL, [`evidence/cloud/data-security.txt`](evidence/cloud/data-security.txt)). B1–B4: all pass in Cloud AI Tier run 39119158736 on commit `817ef779` (18 October), and ran again on 22 October in run 39720293518 (`dedda460`); the AI tier was then turned off again. The B1–B4 outputs, and the earlier 18 October B5 (52 PASS) and B6 copies, are in [`evidence/bonus/`](evidence/bonus/README.md). B1–B4 UI captures (19 October, run 39215189074) are in [`evidence/bonus/ui/`](evidence/bonus/README.md#ui-captures-19-october). Still to do: show B1–B4 and the B5/B6 checks in the video |
| Report and video (G) | All | `build_release2_report.py --status` lists each owner's TODOs; the remaining ones are the showcase video URL and the participation statements. The [showcase runbook](showcase-runbook.md) holds each student's video segment |
| Features 2–5 workflows (F-2..F-11) | Students 2–5 | **Done.** Each of Students 1–5 has a decided multi-agent run exported (see the list below), CI evidence on `7b3fb437` (Student 2 #198, Student 3 #192, Student 4 #186, Student 5 #195) and complete coverage in the 24 October multi-agent and testing reviews. The recipe, for reference: copy Feature 1: a `config/multi-agent/workflow.yaml`, proxy routes tested with `FakeMultiAgentServer`, and a panel mount (Dockerfile `COPY`, `docker-compose.dev.yml` bind mount, empty `frontend/multi-agent/README.md`). Endpoint test recipe: `shared/testkit/README.md`; then `collect_ci_evidence.py --student N`, and `multi-agent-server export <run> --out docs/release-2/evidence/multi-agent/student-N/<run> --server` |

### Decided multi-agent runs exported

From each run's `summary.md` under [`evidence/multi-agent/`](evidence/multi-agent/). Every run below
reached a human decision.

| Owner | Run (folder) | Template | Created | Final state |
|---|---|---|---|---|
| Student 1 | `18740ca5` (`-ui`) | `f1-release-readiness-review` v1 | 10 October | partially_accepted |
| Student 1 | `c17c66cc` (`-terminal`) | `f1-release-readiness-review` v1 | 9 October | partially_accepted |
| Student 2 | `68c410ca`, `f7c08ae0`, `f1c290a2` (`-ui`) | `f2-market-case-brief` v1 | 20 October | approved |
| Student 2 | `58936cad` (`-api`) | `f2-market-case-brief` v1 | 20 October | approved |
| Student 3 | `5338d71c` (`-ui`) | `f3-suburb-comparison-review` v1 | 23 October | rejected |
| Student 4 | `2956e465`, `ec73c476` (`-ui`) | `f4-evidence-readiness-review` v1 | 21 October | approved |
| Student 4 | `f58a46f5` (`-api`) | `f4-evidence-readiness-review` v1 | 21 October | approved |
| Student 5 | `e9600341` | `f5-buyer-case-action-plan` v1 | 22 October | approved |
| Student 5 | `429fbe07` | `f5-buyer-case-action-plan` v2 | 22 October | partially_accepted |

### Evidence refresh at the freeze (on clean main)

One command runs every capture in order and logs each step:
`scripts/refresh_release2_evidence.py` (see its docstring). It copies nothing into the repository
in a dry run, and under `--final` it refuses to start unless the checkout is `main` at
`origin/main` with a clean source tree. The capture tools ignore `docs/release-2/evidence` when
they check for uncommitted changes, so one step's output never marks the next capture as dirty.

1. Start the stack and the four host services, each in its own foreground terminal
   ([layout](evidence/local/README.md#several-real-terminals)): `uv run scripts/dev.py stack up`,
   `uv run scripts/dev.py ai stop` (stack up starts them in the background), then
   `uv run scripts/dev.py ai serve <service>` for `ai-mode`, `mcp`, `rag` and `multi-agent`.
2. Rehearse first, into a scratch folder under `.propertyscope-runtime/evidence-refresh/`:

   ```text
   uv run python scripts/refresh_release2_evidence.py
   ```

3. At the freeze, once every `student-N.yml` is green on `main` and Students 2–5 have merged
   their evidence:

   ```text
   uv run python scripts/refresh_release2_evidence.py --final --ci-students all
   ```

   The steps are `preflight`, `security`, `ci`, `local`, `ui`, `reviews` and `report`. At `ui` the
   command waits for a person to decide a Feature 1 Readiness review in the UI (current panel,
   template v2) and exports that run to `multi-agent/student-1/<run>-ui/`. `--ui-run-id` exports
   an already-decided run instead; `--only` and `--skip` rerun single steps. The cloud review
   reports `fail` until cloud evidence exists; after the first Azure deployment rerun
   `--final --only reviews`, then `uv run scripts/dev.py ai review decide`.
4. Check `summary.md` in the run folder, review `git diff --stat docs/release-2/evidence`, and
   commit the refreshed evidence.
5. Contribution tables (report Section 12): every student's commits, including the merged Wave 1/2
   PR. Then rebuild the report: `uv run python scripts/build_release2_report.py`.

### Known issues

Rechecked against the 23–24 October evidence on `7b3fb437`.

- Shared packaging touched other slices in two ways only: one
  `COPY ai-services/multi-agent-server/pyproject.toml` line in each `student-{1..5}/Dockerfile`
  (needed for `uv sync --locked`; not rechecked on 24 October), and per-file Ruff `S` ignores in
  the root `pyproject.toml`. **Resolved** for the Ruff ignores:
  [`evidence/security/pre-commit-report.md`](evidence/security/pre-commit-report.md) lists only
  the test-code per-file ignores and 0 pending-owner findings.
- **Resolved:** Ruff `S` findings no longer await their owners. The 23 October
  [`pre-commit-report.md`](evidence/security/pre-commit-report.md) shows 0 open and 0 pending owner
  for every slice (Student 3: 10 and Student 5: 17 justified with `# noqa`; Students 2 and 4
  cleared theirs in #162 and #164).
- pip-audit passes with two reviewed exceptions in `scripts/security/accepted-risks.toml`: Pillow
  11.3.0 (held by `fastembed==0.7.4` in RAG; never decodes untrusted images) and pytest 8.4 (fix
  only in pytest 9). The 23 October report counts 55 accepted risks in these 2 packages, and the
  24 October testing review's one failed check (Shared's advisory `security.dependencies-clean`)
  is this item ([`testing-review.md`](evidence/reviews/testing-review.md)). Removing them needs a
  RAG upgrade with re-ingest and evaluation, and a pytest 9 change across every suite; neither was
  attempted before the showcase.
- **Resolved:** `f3-backend` now has its `MULTI_AGENT_*` environment (08a9331): the Azure AI overlay
  (`docker-compose.azure-ai.yml`) gives it the Multi-Agent URL and token, and
  `student-3/tests/test_deployment.py` asserts them.
- **Resolved:** `ai review multi-agent` and `ai review testing` no longer report `fail`. On
  24 October the multi-agent review passed 35 of 35 and the testing review returned
  `pass_with_risks` (36 of 37), both with Students 1–5 complete
  ([`multi-agent-review.md`](evidence/reviews/multi-agent-review.md),
  [`testing-review.md`](evidence/reviews/testing-review.md)).
- `f2-backend`'s background sales-import reconciliation still logs `DependencyUnavailableError`
  ("Market database API is unavailable"): 3 tracebacks in the 23 October local capture, while all
  111 checks, including Feature 2's health and CRUD, passed
  ([`local-deployment-report.md`](evidence/local/local-deployment-report.md), "Log observations";
  Student 2). The 16 October capture showed the same.
- On Azure (18 October, earlier evidence): Feature 3's `/published/suburbs` answered 503; Feature 2
  still showed fixture cases; and Data status listed the deliberately disabled AI tier as needing
  attention (fixed in #160, which is in the deployed `7b3fb437`). The 24 October smoke test does not
  call `/published/suburbs` or open these pages, and the screenshots were not retaken, so none of
  the three was rechecked on 24 October. Details:
  [`evidence/cloud/README.md`](evidence/cloud/README.md#observations-made-while-capturing).
- Under heavy load, `test_ui_audit_browser.py::test_configured_named_flows_reach_their_response_state`
  and a Student 3 MCP socket test have each failed once and passed on rerun (not rechecked on
  24 October).

Fixed since 16 October: RAG and MCP log correlated request IDs (the 23 October capture's RAG and
MCP terminal logs carry 17 and 4 lines with its IDs; the earlier 16 October capture showed none),
and the Azure AI overlay now hands the Multi-Agent token to the Feature 1 backend.
