# Release 2 showcase runbook

This is the script for the group video (at most 10 minutes, recorded 21–22 October 2026) and for
the live showcase on 23 October. It covers every item the brief requires
([requirements.md, "Showcase video must show"](requirements.md#showcase-video-must-show-criterion-10)).
Rehearse it end to end at least once on the freeze commit.

Shared and Feature 1 segments are written out in full. Students 2–5 fill in their own segments:
the `<Student N: ...>` placeholders list what the brief needs from each of them. Nobody else
writes another student's segment.

All commands run from the repository root in PowerShell 7. Every command here exists. Check any
of them with `--help` (for example `uv run scripts/dev.py ai review decide --help`).

## Coverage

| Brief requirement | Segment |
|---|---|
| Multi-Agent workflow through the frontend UI, including human review | 3 (Feature 1), 9–12 (each student) |
| Frontend running locally and on Azure | 2–3 and 9–12 (local), 8 (Azure) |
| Pre-commit security scans running during a commit | 5 |
| Post-commit CI endpoint tests in GitHub Actions | 6, 9–12 |
| All three agentic-loop review modes, plus the human release decision | 7 |
| Local multi-terminal operation (AI-mode, MCP, RAG and Multi-Agent each in its own terminal) | 2 |
| A terminal Multi-Agent run | 4 |
| Every student explains and defends their own Release 2 contribution | 1–8 (Matthew), 9–12 |
| Bonus services or controls we claim | 13 (only if claimed) |

## Segments

| # | Segment | Owner | Budget | Ends at |
|---:|---|---|---:|---:|
| 1 | Introduction: team, what Release 2 adds, architecture figure | Matthew | 0:20 | 0:20 |
| 2 | Local deployment: six terminals, Compose plus four host services | Matthew | 0:45 | 1:05 |
| 3 | Feature 1 Readiness review in the UI: Planner → Worker → Reviewer → Human Review | Matthew | 1:20 | 2:25 |
| 4 | Terminal Multi-Agent run with a human decision | Matthew | 0:25 | 2:50 |
| 5 | Pre-commit security scans during `git commit` | Matthew | 0:35 | 3:25 |
| 6 | Post-commit CI: `student-1.yml` endpoint tests, JUnit summary, Cloud Deployment gate | Matthew | 0:35 | 4:00 |
| 7 | Review modes: `ai review multi-agent`, `testing`, `cloud`, then `ai review decide` | Matthew | 0:45 | 4:45 |
| 8 | Azure: the public URL, CRUD, AI tier off | Matthew | 0:35 | 5:20 |
| 9 | Feature 2 | Burhan Naeem | 1:00 | 6:20 |
| 10 | Feature 3 | James Huang | 1:00 | 7:20 |
| 11 | Feature 4 | Michael White | 1:00 | 8:20 |
| 12 | Feature 5 | Derek Song | 1:00 | 9:20 |
| 13 | Bonus (optional, only for a claimed bonus) | Matthew | 0:00–0:20 | 9:40 |
| 14 | Close: repository, report, decision | Matthew | 0:10 | 9:50 |

"Ends at" assumes the full 20-second bonus segment. The total is 9:30 without it and 9:50 with it. The remaining 10 seconds are a
buffer for transitions. If a segment overruns in rehearsal, cut it back to its budget. Do not take
time from another student's segment. Segments 9–12 can be recorded separately and spliced in.

## Prepare

### The day before (22 October, or before the recording session)

1. **Check out the freeze commit** on `main` in a clean checkout, then sync it:

   ```powershell
   git switch main; git pull --ff-only
   git status --short                      # must be empty
   uv sync --locked --all-packages --all-groups
   uv run pre-commit install --hook-type pre-commit --hook-type pre-push
   ```

2. **Set the provider key** in `.env` (`OPENAI_API_KEY`). Do not show `.env` on screen.
3. **Start the stack once** and confirm that everything is healthy:

   ```powershell
   uv run scripts/dev.py stack doctor
   uv run scripts/dev.py stack up
   uv run scripts/dev.py stack status      # every container healthy, four host services ready
   uv run scripts/dev.py ai probe          # MCP and RAG auth, tools, corpora, retrieval
   ```

4. **Check the data and label it correctly.** A fresh database holds the seeded demonstration
   baseline (about 10 synthetic records per dataset). Say "seeded demonstration data" on camera
   unless this command shows a published official release:

   ```powershell
   uv run python .github/skills/feature-1-data/data_status.py
   ```

5. **Create a candidate release for segment 3.** The Readiness review is offered only for
   `candidate` and `awaiting_review` releases. `abs-cpi` is small, real and takes about a minute
   (needs internet). `fixture-property` works offline in seconds. Either way the command waits and
   prints the candidate release ID. Write that ID down. **Do not publish it.**

   ```powershell
   uv run scripts/dev.py data collect abs-cpi
   # offline alternative: uv run scripts/dev.py data collect fixture-property
   ```

   Make a second candidate (or use the other job) for segment 4, so the terminal run does not
   reopen the UI run.

6. **Write the terminal input file** for segment 4 in the ignored `tmp/` folder:

   ```powershell
   New-Item -ItemType Directory -Force tmp/showcase | Out-Null
   '{"release_id": "<second candidate release ID>", "reviewer_note": "Showcase terminal run"}' |
     Set-Content -Encoding utf8 tmp/showcase/review-input.json
   ```

7. **Prepare the demo commit branch for segment 5** (see segment 5). Make the edits but do not
   commit them yet.
8. **Prepare a scratch evidence copy for segment 7** so that a rehearsal never overwrites the
   committed reviews or the release decision:

   ```powershell
   Copy-Item -Recurse -Force docs/release-2/evidence tmp/showcase/evidence
   ```

9. **Check GitHub Actions.** Make sure the latest `student-1.yml` run on `main` is green, and
   that there is a Cloud Deployment run whose `verify-ci` and `build-validate` jobs passed. If
   there is none for the freeze commit, start one now (each takes a few minutes):

   ```powershell
   gh run list --workflow student-1.yml --branch main --limit 3
   gh workflow run student-1.yml --ref main
   gh run list --workflow cloud-deployment.yml --limit 3
   ```

10. **Azure.** If it is provisioned, open
    `https://propertyscope-nsw-g20.australiaeast.cloudapp.azure.com/` (the default DNS label in
    `deployment/azure/main.bicepparam`; `uv run scripts/dev.py cloud outputs` prints the real FQDN)
    and confirm that the home page and all five features load. Start the VM first if it was
    deallocated (see [deployment/azure/README.md](../../deployment/azure/README.md)). **Azure is
    pending provisioning at the time of writing (17 October).** If it is still not provisioned at
    recording time, segment 8 uses its fallback, and the video must say so plainly.
11. **Record fallback clips** of segments 3, 4 and 8 during the rehearsal. Keep them ready to
    splice in.

### One hour before

1. Start Docker Desktop, then bring the stack up and hand the host services to their own terminals
   (the [local deployment README](evidence/local/README.md#several-real-terminals) explains this
   layout). Use Windows Terminal with six panes, each labelled with its number:

   | Terminal | Command | Shows |
   |---|---|---|
   | 1 Compose | `uv run scripts/dev.py stack up`, then `uv run scripts/dev.py ai stop`, then `uv run scripts/dev.py stack logs` | Every container's log |
   | 3 MCP | `uv run scripts/dev.py ai serve mcp` | MCP in the foreground (start before AI-mode) |
   | 4 RAG | `uv run scripts/dev.py ai serve rag` | RAG in the foreground (start before AI-mode) |
   | 2 AI-mode | `uv run scripts/dev.py ai serve ai-mode` | AI-mode and its agentic loop |
   | 5 Multi-Agent | `uv run scripts/dev.py ai serve multi-agent` | The Multi-Agent Server on :5013 |
   | 6 Operator | `uv run scripts/dev.py ai status`, then the segment 4–7 commands | The demo commands |

2. In terminal 6, run `uv run scripts/dev.py stack status` and `uv run scripts/dev.py ai status`.
   The four host services must show as ready and `foreground`.
3. **Browser tabs**, in this order, at 100 % zoom and 1440 px wide or more:
   1. Shared home: <http://localhost:5100>
   2. Feature 1 Published data, open on the candidate release: `http://localhost:5200/#releases/<candidate ID>`
   3. AI-mode Activity history: <http://localhost:5100/operations/ai-mode/>
   4. GitHub Actions, `student-1.yml`: <https://github.com/MattShelton04/41026ASDProject/actions/workflows/student-1.yml>
   5. GitHub Actions, `cloud-deployment.yml`: <https://github.com/MattShelton04/41026ASDProject/actions/workflows/cloud-deployment.yml>
   6. Azure home: `https://propertyscope-nsw-g20.australiaeast.cloudapp.azure.com/`
   7. Azure Feature 1: `https://propertyscope-nsw-g20.australiaeast.cloudapp.azure.com/features/data-platform/`
   8. Each student's local and Azure feature pages, for segments 9–12
4. Close every window that could show a secret: `.env`, `.propertyscope-runtime/`, the Azure
   portal's Key Vault blade and shell history containing tokens.
5. Turn off notifications. Hide the bookmarks bar if it shows anything private.

### Fallbacks

| Problem | Fallback | Say on camera |
|---|---|---|
| The model provider is down or rate-limited | Restart terminal 5 with `$env:MULTI_AGENT_PROVIDER = "deterministic"` before `uv run scripts/dev.py ai serve multi-agent`. Restart terminal 2 with `uv run scripts/dev.py ai serve ai-mode --offline` (direct mode, no model). Run the reviews with `--deterministic`, or `--fallback-deterministic` to try AI-mode first | "The agents are running on the deterministic provider" (the run records this) |
| AI-mode review fails or times out | `uv run scripts/dev.py ai review <mode> --fallback-deterministic --evidence-dir tmp/showcase/evidence` writes a labelled deterministic review with the failed run ID | "AI-mode failed, so this is the labelled deterministic review" |
| No Docker stack | Splice in the rehearsal clip. For layout only, `uv run scripts/dev.py ui serve` serves deterministic fixture pages at <http://127.0.0.1:5990> | Fixture pages are not live integration. Say so if you show them |
| The Multi-Agent Server is unavailable for segment 4 | Offline in-process run with fixture tools and its own scratch state (never the running server's state directory): `uv run multi-agent-server run --deterministic --state-dir tmp/showcase/ma-state --template-path ai-services/multi-agent-server/tests/fixtures/workflow.yaml --tool-fixtures ai-services/multi-agent-server/tests/fixtures/tools.json --template example-readiness-review --input '{"record_id": "8c0d7e0e-4a3b-4c55-9a62-0d7c5f0f9a11"}' --review` ([Multi-Agent README](../../ai-services/multi-agent-server/README.md#cli)) | "This uses the example template and fixture tool results, not Feature 1" |
| GitHub Actions is slow | Show the completed green run (`#353` or the freeze run) instead of a live one | — |
| The pre-commit hooks are slow (mypy) | Cut the wait in the edit. Supplementary shot: `uv run pre-commit run --all-files` | — |
| Azure is not provisioned, or the VM is down | Splice in the rehearsal clip if one exists. Otherwise show the `verify-ci` and `build-validate` jobs and the `deploy` job skipped, and say that the cloud deployment is pending | Never present a local page as Azure |

## Script

Each segment gives the commands in order, what to click and what the viewer should see. The
speaker notes are a guide; say them in your own words.

### 1 Introduction (Matthew, 0:20)

Show the shared home at <http://localhost:5100>, then Figure 1 of the report
(`docs/reports/assets/release-2/release-2-architecture.png`).

> "We are Group 20. PropertyScope NSW is five feature slices behind one shared home page. Release 2
> adds a shared Multi-Agent Server, three agentic-loop review modes, pre-commit security scans,
> endpoint tests in CI and an Azure deployment. I'm Matthew. I own the shared platform and
> Feature 1."

### 2 Local deployment: several terminals (Matthew, 0:45)

1. Show all six panes at once.
2. Terminal 6: `uv run scripts/dev.py stack status`, then `uv run scripts/dev.py ai status`.
3. Point at terminals 2–5: each host service is running in its own terminal, outside Docker.

**Viewer sees:** every container healthy in terminal 1. AI-mode (:5005), MCP (:5011), RAG (:5012)
and the Multi-Agent Server (:5013) as separate `foreground` host processes.

> "The feature frontends, APIs and databases run in Docker Compose. AI-mode, MCP, RAG and the
> Multi-Agent Server never run in a container. Each one is a host process with its own terminal,
> and the backends reach them through `host.docker.internal`."

### 3 Feature 1 Readiness review through the UI (Matthew, 1:20)

The reference workflow for every feature: Frontend → Feature 1 backend → Multi-Agent Server →
Planner → Worker → Reviewer → Human Review → response.

1. Browser tab 2: the candidate release page. Point at the record count, quality results,
   **Publish** and **Readiness review**.
2. Click **Readiness review**. The shared panel opens inline.
3. Watch the lanes fill: **Planner** (the read-only steps and the evidence it needs),
   **Worker** (`data.release_inspect.v1` and `data.releases.v1` through MCP), **Reviewer** (the
   passed and failed checks and its recommendation). Keep terminals 3 and 5 visible in a corner if
   the layout allows: the Worker's tool calls appear in MCP's log and the run ID in the Multi-Agent
   log.
4. At **awaiting human**, read the Reviewer's recommendation and the guidance out loud.
5. Make a real decision. To show the correction loop, choose **Correct** with a note (for example
   "Confirm completeness against the publisher's totals"). The Worker and Reviewer re-run once
   with the note. Then choose **Approve**, **Partially accept** (pick the steps) or **Reject**.
   Type your own name as the actor.
6. Open the decision and history drawers: the recorded decision with actor, time, round and note,
   and the state transitions.
7. Point at the release status: still `candidate` or `awaiting_review`. **Publish** is still a
   separate button.

**Viewer sees:** four stages in order, a human decision with a name and time, and nothing
published.

> "The Planner plans read-only checks, the Worker gathers evidence with Feature 1's tools through
> MCP, and the Reviewer compares it with the publication criteria. Only a person ends the run.
> The workflow's tool allowlist leaves out the publish tool, so a review can never publish.
> Every stage is in the workflow history and the coordination audit log."

### 4 Terminal Multi-Agent run (Matthew, 0:25)

Terminal 6:

```powershell
uv run multi-agent-server templates --server
uv run multi-agent-server run --template f1-release-readiness-review --input "@tmp/showcase/review-input.json" --review --actor "Matthew Shelton" --server
```

The run follows the agents live (`==` state changes and `.` audit events). At the prompt, press
Enter to take the Reviewer's suggestion, or type a decision and a note. Then:

```powershell
uv run multi-agent-server history <run ID> --server
```

**Viewer sees:** the same Planner → Worker → Reviewer → human trail, from the terminal, against
the same server (terminal 5 logs the run).

For the report after the recording (not on camera), export the run:
`uv run multi-agent-server export <run ID> --out docs/release-2/evidence/multi-agent/student-1/<run ID>-terminal --server`.

### 5 Pre-commit security scans during a commit (Matthew, 0:35)

**Gotcha:** the pip-audit hook runs only when `uv.lock`, a `pyproject.toml` or
`scripts/security/accepted-risks.toml` is staged (`files:` in `.pre-commit-config.yaml`). The
Ruff `S` hook runs only on staged Python files. A commit of one Markdown file shows both as
`Skipped`. The demo commit therefore stages one comment in a `pyproject.toml` and one comment in
a Python file, on a throwaway branch that is never pushed.

Prepare (the day before, off camera):

```powershell
git switch -c demo/showcase-precommit
Add-Content student-1/pyproject.toml "# Release 2 showcase: pre-commit demonstration"
Add-Content student-1/backend/src/propertyscope_data_platform/__init__.py "# Release 2 showcase: pre-commit demonstration"
```

On camera (terminal 6):

```powershell
git add student-1/pyproject.toml student-1/backend/src/propertyscope_data_platform/__init__.py
git commit -m "chore: showcase pre-commit demonstration"
```

**Viewer sees:** `Ruff lint`, `Ruff format`, `mypy`, then
`security: Ruff flake8-bandit rules (S)`, `security: detect-secrets against .secrets.baseline`
and `security: pip-audit of locked dependencies (uv.lock)`, each `Passed`. Cut the mypy wait in
the edit.

Clean up straight after the take (off camera). The branch was never pushed:

```powershell
git switch main
git branch -D demo/showcase-precommit
```

Supplementary shot, if time allows: `uv run pre-commit run --all-files`. Mention that
`integration-ci.yml` repeats the three scans on every push and that
`uv run scripts/dev.py security report` writes the report in
[`evidence/security/`](evidence/security/pre-commit-report.md).

### 6 Post-commit CI endpoint tests (Matthew, 0:35)

1. Browser tab 4: the latest green **Student 1 CI** run on `main`. Open the
   **Feature 1 integrated stack** job and expand the two endpoint steps ("on the feature origin",
   "through the Shared edge").
2. Scroll to the run's **Summary**: the JUnit tables from `shared_testkit.junit_summary`, with at
   least two passing endpoint tests for property search and for source-definition CRUD. Point at
   the `student-1-endpoint-tests` artifact.
3. Browser tab 5: a **Cloud Deployment** run. Show the job graph: **Verify CI gate (Integration CI
   + Student 1-5 CI)** → **Docker build and validation** → **Deploy to Azure** (skipped until Azure
   is configured).

> "Every push to `main` runs each student's workflow. Ours starts Feature 1's Compose stack in
> GitHub Actions with the AI tier off and tests two endpoint functions. The cloud deployment only
> starts after Integration CI and all five student workflows pass for that commit, and every image
> builds and validates."

Optional terminal shot: `gh run list --workflow student-1.yml --branch main --limit 3`.

### 7 Review modes and the human release decision (Matthew, 0:45)

Terminal 6. Use the scratch evidence copy, so that a retake never overwrites the committed
evidence. Drop `--evidence-dir` only for the real freeze run, which is then committed.

```powershell
uv run scripts/dev.py ai review multi-agent --evidence-dir tmp/showcase/evidence
uv run scripts/dev.py ai review testing --evidence-dir tmp/showcase/evidence
uv run scripts/dev.py ai review cloud --evidence-dir tmp/showcase/evidence
uv run scripts/dev.py ai review decide --evidence-dir tmp/showcase/evidence --decision hold --decider "Matthew Shelton" --rationale "<the reason, in your own words>"
```

1. After each review, open its report (`tmp/showcase/evidence/reviews/<mode>-review.md`) and show
   the verdict, **Verdict basis**, **Coverage by owner** and the findings.
2. Browser tab 3: the review runs in AI-mode **Activity history**, with their four phases.
3. The decision: `release` only after a passing cloud review of a real deployment; `hold`
   while Azure is pending or a check fails. `decide` refuses `release` over a failed review
   unless `--acknowledge-failed-review` is given, and refuses if the evidence changed since the
   review.

**Viewer sees:** three reviews written by the agentic loop (Plan → Act → Observe → Adapt), each
with a report and a validation-log line, and a named human decision. Shared and Student 1 show as
`complete` in Coverage by owner even while the group verdict is `fail` for missing evidence.
Say which owners are missing; do not hide it.

> "The loop reads the evidence, builds a checklist and reviews it. The verdict is never more
> lenient than the checklist. A person makes the release decision, and the record pins the
> evidence hashes it was made on."

### 8 Azure (Matthew, 0:35)

**Pending provisioning.** Record this segment only against the real Azure URL. Until then use
the fallback in the table above.

1. Browser tab 6: the Azure home page over HTTPS. Point at the padlock and the
   `cloudapp.azure.com` address.
2. Open each of the five features from the home page.
3. Browser tab 7: Feature 1 on Azure. Run a property search, then create, read and delete a
   source definition (or show the smoke output's CRUD cases).
4. Open the deployed candidate release (the deployment runs the `fixture-property` collection
   once). **Readiness review** and **Review with AI** are visible but disabled, with the note
   "Multi-agent review is not enabled in this deployment."
5. Show the Cloud Deployment run's smoke step: every CRUD case passed and the AI check reports
   `ai_disabled`.

**Viewer sees:** the same frontend, APIs and databases working on Azure, with the AI tier off by
default (R2-44). The cloud data is the seeded demonstration baseline. Say so.

> "This is one Ubuntu VM in Australia East. It runs the same Compose model, with images from Azure
> Container Registry pinned to the commit SHA, Caddy for TLS and secrets in Key Vault. AI-mode,
> MCP, RAG and the Multi-Agent Server are off in the cloud baseline."

### 9 Feature 2 (Burhan Naeem, 1:00)

`<Student 2: segment script, written by Burhan>`. It must show, in Burhan's own words:

- `<Student 2: Feature 2 frontend running locally (http://localhost:5300), with one CRUD action>`
- `<Student 2: Feature 2's Multi-Agent workflow started from the Feature 2 UI, through Planner, Worker and Reviewer, to a human decision made on camera>`
- `<Student 2: the green student-2.yml run in GitHub Actions and its two endpoint tests (JUnit summary)>`
- `<Student 2: how Feature 2's pending Ruff S findings were fixed or justified>`
- `<Student 2: Feature 2 on Azure, or the agreed fallback>`
- `<Student 2: what Burhan built for Release 2 and why (contribution explanation)>`

### 10 Feature 3 (James Huang, 1:00)

`<Student 3: segment script, written by James>`. It must show, in James's own words:

- `<Student 3: Feature 3 frontend running locally (http://localhost:5600), with one CRUD action>`
- `<Student 3: Feature 3's Multi-Agent workflow started from the Feature 3 UI, through Planner, Worker and Reviewer, to a human decision made on camera>`
- `<Student 3: the green student-3.yml run in GitHub Actions and its two endpoint tests (JUnit summary)>`
- `<Student 3: how Feature 3's pending Ruff S findings were fixed or justified>`
- `<Student 3: Feature 3 on Azure, or the agreed fallback>`
- `<Student 3: what James built for Release 2 and why (contribution explanation)>`

### 11 Feature 4 (Michael White, 1:00)

`<Student 4: segment script, written by Michael>`. It must show, in Michael's own words:

- `<Student 4: Feature 4 frontend running locally (http://localhost:5400), with one CRUD action>`
- `<Student 4: Feature 4's Multi-Agent workflow started from the Feature 4 UI, through Planner, Worker and Reviewer, to a human decision made on camera>`
- `<Student 4: the green student-4.yml run in GitHub Actions and its two endpoint tests (JUnit summary)>`
- `<Student 4: how Feature 4's pending Ruff S findings were fixed or justified>`
- `<Student 4: Feature 4 on Azure, or the agreed fallback>`
- `<Student 4: what Michael built for Release 2 and why (contribution explanation)>`

### 12 Feature 5 (Derek Song, 1:00)

`<Student 5: segment script, written by Derek>`. It must show, in Derek's own words:

- `<Student 5: Feature 5 frontend running locally (http://localhost:5500), with one CRUD action>`
- `<Student 5: Feature 5's Multi-Agent workflow started from the Feature 5 UI, through Planner, Worker and Reviewer, to a human decision made on camera>`
- `<Student 5: the green student-5.yml run in GitHub Actions and its two endpoint tests (JUnit summary)>`
- `<Student 5: how Feature 5's pending Ruff S findings were fixed or justified>`
- `<Student 5: Feature 5 on Azure, or the agreed fallback>`
- `<Student 5: what Derek built for Release 2 and why (contribution explanation)>`

Each student's workflow uses the shared panel and proxy contract that Feature 1 uses (segment 3).
After recording, each student exports their decided run with
`uv run multi-agent-server export <run ID> --out docs/release-2/evidence/multi-agent/student-N/<run ID> --server`.

### 13 Bonus (optional, Matthew, up to 0:20)

Include this only for a bonus the report claims. The rubric scores the AI tiers cumulatively
(AI-mode → MCP → RAG → Multi-Agent) and security as endpoint, then endpoint plus data.

- **B5 and B6 (no AI needed):** show `uv run scripts/dev.py cloud validate endpoint` (closed ports,
  HTTP → HTTPS redirect, 401 on protected routes, 429 from the rate limit), then
  `uv run scripts/dev.py cloud validate data`.
- **B1–B4 (AI tier enabled in Azure):** `uv run scripts/dev.py cloud ai on`, then
  `uv run scripts/dev.py cloud smoke --expect-ai`. Show an assistant answer (B1), a tool call (B2),
  a cited answer (B3) and a Feature 1 Readiness review reaching a human decision on Azure (B4).
  The protected routes ask for the operator credentials. Type them off camera. Turn the tier off
  again afterwards with `uv run scripts/dev.py cloud ai off`.

If the video runs long with this segment, shorten segment 7 or 8, never a student segment.

### 14 Close (Matthew, 0:10)

> "The repository, the commit history and the report are linked in `group-20.pdf`. Thank you."

## After the recording

1. Stop terminals 2–5 with Ctrl+C, then return to the managed services:
   `uv run scripts/dev.py ai start --mode combined`.
2. Delete `tmp/showcase/` once the takes are final. Never copy its reviews or decision into
   `docs/release-2/evidence/`. The committed evidence comes from the freeze run
   ([evidence refresh](README.md#evidence-refresh-at-the-freeze-on-clean-main)).
3. Upload the video, check that it is at most 10 minutes and that the link works signed out, then
   put the same URL on the report cover, in `RELEASE2_METADATA` and in Section 14.
4. Record who took part in the showcase in Section 14 of the report.

## Live showcase (23 October)

Play the video, then take questions. Keep the stack, the six terminals and the browser tabs from
"One hour before" open, so that any step can be repeated live. Likely questions and where the
answers are:

| Question | Answer from |
|---|---|
| Why a VM and not Container Apps? | [ADR-048](../architecture/decisions/ADR-048-azure-vm-hosting.md): the AI tier must stay a host process |
| Why a separate Multi-Agent Server instead of AI-mode? | [ADR-047](../architecture/decisions/ADR-047-multi-agent-server.md) |
| Can the Worker change data? | No: allowlisted read-only tools only; the publish tool is not allowlisted |
| What blocks a deployment? | `verify-ci` (Integration CI and Student 1–5 CI) and `build-validate`, then the protected `production` environment |
| Why does a review say `fail`? | Coverage by owner names the missing evidence and its owner ([review-modes.md](review-modes.md#owners-and-blocked-checks)) |
