# Release 0 recording runbook

Companion to the [timed script](presentation-script.md). These are preparation and
recording directions, not additional narration. Use the checklist in
[student-1](../../student-1/PRESENTATION_CHECKLIST.md) for the final rehearsal.

## Environment and branch isolation

- Presentation branch: `Matt/Release_0_Presentation_Spike`.
- Isolated worktree: `C:/git/41026ASDProject-release0-presentation`.
- Preparation baseline: `6fbe1b723ee127a27daeafbf35037f69c8939cdb`, from
  `Matt/F1_UI_Fix_1`; the other agent continues in `C:/git/41026ASDProject`.
- Rehearsal reads used the already-running `ps-dev` stack at `localhost:5100`.
  It is source-mounted from the primary checkout, which can change concurrently.
  These runtime observations are **not proof of the presentation branch runtime**.
- This spike adds documentation and a small whitelisted evidence record. It does not
  change product behaviour, seed production data, weaken CI or manufacture a failing run.
  The student-owned checklist is a useful Feature 1 change that also matches the
  existing Student 1 workflow path filter.

Do not run `stack up`, `restart`, `rebuild`, `down` or `reset` from this worktree while
the other agent uses the live stack. Both checkouts default to the same `ps-dev` project
and host ports. A separate Git worktree does not isolate Docker resources. No live
services were restarted or official datasets published during presentation preparation.
Three read-only AI questions were submitted and retained as durable runs.

## Before recording

1. Agree the final group commit and designated runtime checkout after the other fix is
   finished. Record `git rev-parse HEAD`, `git status --short`, Compose status and the
   selected Actions SHAs. Rehearsal baseline, CI merge commit and final submission SHA
   must not be silently treated as the same commit.
2. Confirm all five features are integrated. At rehearsal only 1/2/4/5 were enabled;
   Feature 3's card was Planned. Ask its owner to deliver the working integration.
3. Have the approved provider configured in the Git-ignored environment file. In the
   agreed live checkout, run the canonical commands below and record their real output.
   This does not require resetting volumes. Keep keys and environment-file contents out
   of the terminal capture. Builds/startup can be cut for time.
4. Use the shared origin `http://localhost:5100` throughout the product demonstration.
   Direct Feature 1 port 5200 is for focused development; the separate UI fixture server
   is not evidence of the integrated Docker/PostgreSQL/real-model application.
5. Search the chosen property again and wait for map and SEIFA panels to load. Confirm
   release IDs/counts still match. Do not publish or alter data merely to make screenshots
   look green; show the real accepted state and disclose any changed coverage.
6. Run both exact AI prompts in fresh chats. Capture submission, real Complete state,
   answer and evidence. The rehearsed durations were approximately 8 and 17 seconds;
   provider latency is variable. Prepare honest cuts of waiting time.
7. Rehearse disposable source CRUD once in the integrated app, keeping the full uncut
   screen capture. Fill the creation fields off-camera, then start the segment before
   pressing Create source. Confirm create/read/update/delete outcomes, not just clicks.
8. Pin the successful Actions run/job tabs. Open the log step before filming so no time
   is spent finding it. Verify the run's conclusion and SHA first.
9. Record the complete screen sequence, then edit it to the seven F1 time windows. Overlay
   `Typing shortened` or `Waiting time removed` when appropriate. Use one continuous
   narration track; never splice a failed action directly into an unrelated success.
10. Time the spoken script yourself. Target natural speech around 135–150 words/minute,
    using remaining time for clicks and pauses. Keep all five segments plus transitions
    under 10:00. The intended 1:00/1:45 windows are an edit budget, not measured human speech.

Run from the **agreed runtime checkout**, once it is free for deployment capture:

```powershell
uv sync --locked --all-packages --all-groups
uv run python scripts/check.py
uv run scripts/dev.py stack up
uv run scripts/dev.py stack status
uv run scripts/dev.py operator report
```

Use `stack rebuild` only after dependency/lockfile/Dockerfile changes. `stack up --offline`
and UI fixtures are suitable for deterministic rehearsal but cannot substantiate live AI.
No full G-NAF/PSI/BOCSAR collection needs to run inside a 105-second recording.

## Exact tab order and expected evidence

| Tab/shot | URL or destination | Check before filming |
|---|---|---|
| Shared home | [Home](http://localhost:5100/#home) and [Research areas](http://localhost:5100/#features) | Shared style/navigation, actual availability badges. |
| Overview AI | [Global assistant](http://localhost:5100/#assistant) | All of PropertyScope scope, purpose-only prompt from script, real final answer. |
| Data platform | [Data overview](http://localhost:5100/features/data-platform/#overview) | Current accepted sources and honest update-status summary. |
| Published evidence | [SEIFA release](http://localhost:5100/features/data-platform/#releases/1672de46-b88e-400d-9e12-7e9fecad1b0a) | Published; 4,320 source and product rows; review note; three blocking checks Pass; preview contains Abbotsbury. |
| CRUD | [Sources](http://localhost:5100/features/data-platform/#sources) | Disposable Draft source; successful mutation notices; source details and edited name after reload; final absence. |
| Property search | [Search](http://localhost:5100/features/data-platform/#properties) | Query `20 Heysen Street` returns the single Abbotsbury address. |
| Property result | [20 Heysen Street](http://localhost:5100/features/data-platform/#properties/8060a0b4-96a2-6de3-be6b-00f6e844141f) | Verified identity, loaded map, G-NAF source, two datasets and ABS SEIFA attribution/year. |
| Feature AI | [Ask about Property data](http://localhost:5100/features/data-platform/#assistant) | Property data scope; **General Property data question** context; exact address prompt; real Complete state and sources. |
| Deployment | Terminal capture | Actual `stack up` execution/result followed by `stack status`; source checkout/SHA recorded separately. |
| Student CI | [Verified Student 1 run 33741678659](https://github.com/MattShelton04/41026ASDProject/actions/runs/33741678659) | Both jobs passed at `f787250`; refresh to new spike/final run for filming. |
| Student stack job | [Job 100604814510](https://github.com/MattShelton04/41026ASDProject/actions/runs/33741678659/job/100604814510) | `Build cached Shared and Feature 1 targets`, `Start bounded fixture stack`, `Run the code-driven fixture acquisition pipeline`, `Smoke the Shared and Feature 1 boundary`. |
| Shared gate | [Verified Integration run 33741678658](https://github.com/MattShelton04/41026ASDProject/actions/runs/33741678658) | Canonical quality gate and integrated Compose validation passed at `f787250`. |

### The selected property's facts

- Address: **20 HEYSEN STREET, ABBOTSBURY NSW 2176**.
- Property reference: `8060a0b4-96a2-6de3-be6b-00f6e844141f`.
- G-NAF PID: `GANSW711351856`; source-authoritative, current, verified identity.
- Point: latitude `-33.86735306`, longitude `150.86966825`.
- Accepted G-NAF release: `d6bf46ef-1e44-497d-9ab6-4338eb1447ab`, version
  `release-acc859eed2a8bc86-96ee7f24`, source count **5,190,134**.
- Accepted SEIFA release: `1672de46-b88e-400d-9e12-7e9fecad1b0a`, version
  `release-39d9c3b47565d7ee-c362a746`, **4,320 NSW SAL records**.
- SEIFA area: Abbotsbury, SAL `10002`, reference year **2021**, population **4,200**.
  Australian deciles: IRSAD **9**, IRSD **8**, IER **10**, IEO **8**. Show, don't recite all.
- Attribution: **Based on Australian Bureau of Statistics data**.
- Accepted sale-history API returned **zero matched rows**. Its compatible release
  `60000000-0000-0000-0000-000000000002` is the seeded `2026.08.2` baseline.
  Do not label it a completed, accepted full official PSI history. Zero matches do not
  imply the property never sold.

These are observations of the existing runtime on 3 September, not guaranteed future
results. The [JSON capture](evidence/presentation-rehearsal-2026-09-03.json) retains
public property/coverage responses and limited AI execution metadata. It omits internal
plans, reasoning, prompts and credentials. The basemap was visually verified in browser;
API coordinates alone would not prove map rendering.

## Disposable source CRUD: exact values and clicks

Use a unique name per take, e.g. `Release 0 demo - Matt - take 1`. The initial form may
be filled before the timed segment; show its fields and the actual Create click/result.

| Form field | Value |
|---|---|
| Source name | `Release 0 demo - Matt - take 1` |
| Publisher | `PropertyScope presentation fixture` |
| Attribution URL | `https://example.org/propertyscope-release-0-demo` |
| Connector | `fixture-snapshot` |
| Update cadence | `manual` |
| Licence | `cc0-1-0` |
| Licence URL | `https://creativecommons.org/publicdomain/zero/1.0/` |
| Redistribution policy | `metadata-only` |
| Research area keys | `["feature-1"]` |
| Operator notes | `Disposable source-definition metadata for Release 0 CRUD demonstration. No official data or acquisition job.` |
| Lifecycle status | **Draft** |

This is a declared demonstration record, not an official publisher or a claim that the
URL hosts data. The fixture metadata fields do not acquire or publish anything.

1. Data overview → **Manage sources** → **Create source**. Fill values, press
   **Create source**, retain the visible “was created” notice and generated UUID.
   Creation returns the list with **All statuses**; if reopening the page resets the
   Active filter, select **Draft** or **All statuses** and apply it.
2. Search the exact name, **Apply filters**, then **View details**. Show the saved name,
   publisher, Draft status and provenance fields. This supplies Read for the same entity.
3. Return to the list, **Edit** that exact row, append ` - reviewed` to its name, then
   **Save changes**. Show “was updated”, reload/reapply All statuses and read the new name.
4. On the same row, **Delete**, inspect the confirmation naming the correct record,
   then **Delete definition**. Search its unique original-name prefix with **All statuses** and show
   **No sources found**. If delete is rejected because it is referenced, stop and select
   a genuinely disposable record for a new take; never remove an official referenced source.

The schema accepts these values and the create/edit form labels were checked in the live
UI. Live CRUD mutations were not performed during preparation because another agent is
using this runtime. Existing tests and green CI cover the source path; **the integrated,
uncut four-operation recording is still a pre-filming check**, not claimed evidence here.

## Real CI evidence, without a manufactured failure

The baseline already has successful Student 1 and Integration runs. The spike's
student-owned checklist triggers Student 1 naturally on a PR, and Integration runs on
every PR. Use the newest successful matching SHA after review. If a run is red, inspect
its real failure and fix only within scope; don't weaken checks for a recording.

```powershell
gh run list --branch Matt/Release_0_Presentation_Spike --limit 10 --json databaseId,workflowName,status,conclusion,headSha,url
gh pr checks
```

The PR title must begin **[NO CHECKIN]** and remain a draft. Don't merge it as part of
presentation preparation. A docs-only spike is enough for a genuine CI demonstration;
it does not need a contrived product edit. Preserve run URLs and SHA in the final report.
The Student 1 container job validates Shared plus Feature 1, not all five student slices.

## Known recording risks and fallbacks

| Observed risk | Recording response / follow-up |
|---|---|
| Global capability guide incorrectly says Features 2/4/5 are Planned although shared cards enable them | Use the verified purpose-only prompt and describe five areas as scope. Fix the capability guide from authoritative manifest state as follow-up; do not present the broad stale answer as accurate. |
| Exact Property record context rejects this stored reference | Use General context plus exact address; verified search/inspect flow succeeds. Align `student-1/frontend/integration/assistant.js` UUID validation with stored/backend identifiers in a separate fix, with tests for this reference and malformed IDs. |
| Current source sidebar can need horizontal scrolling | Prefer the visible G-NAF identifier and ABS panel; recheck the other agent's layout fix before filming. Don't spend the property segment scrolling technical columns. |
| Map/provider network is slow | Preload the real page. Capture the successful real map/AI interaction ahead of narration and label removed waits. If unavailable, use an explicitly labelled earlier real recording with its date/SHA; do not substitute fixture output as live evidence. |
| PSI refresh failed; selected property has no matched accepted sales | Show honest current-data state and focus on G-NAF/SEIFA; AI should state the sales gap. A later successful ingestion still needs publication/activation before buyer-facing results can change. |
| No successful AI answer during the final take | Re-record after recovery or label previously captured real-provider evidence. Offline scripted fixtures alone leave the assessed live-AI evidence gap open. |
| Only 22 seconds for CRUD or 18 seconds for deployment/CI | Capture complete actions first; edit typing/waiting time. Keep all success outcomes. If over time, shorten narration/optional preview before dropping CRUD, AI, deployment or CI. |
| Team report contains obsolete topology/video instructions | Reconcile it with current manifests and the 30 August clarification. This presentation pack does not silently rewrite another owner's final report. |

## Report handoff checklist

Attach the repository/video URLs, team allocation, Agile/sprint/individual plans,
functional and non-functional requirements, risks, conceptual/ERD/logical/physical data
designs, repository/individual/integrated/Compose/DevOps/agent-loop diagrams,
implementation summary, all student workflow descriptions/results, endpoint/NFR/local
testing evidence, application screenshots, same-SHA deployment/provider evidence,
agentic development-review records and prompt/context artefacts, table-count evidence,
written approvals, known limitations, commit/contribution logs and attendance records.

The recorded application state and public AI metadata can support that report, but the
JSON rehearsal file is not a complete terminal loop log, development review record,
table-count report or final five-feature acceptance test. Finish and export the final
PDF as `group20.pdf`; include the published maximum-ten-minute group video URL.
