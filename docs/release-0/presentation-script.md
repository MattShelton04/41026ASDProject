# Release 0 presentation: project overview and Feature 1

Prepared for Matthew Shelton, Group 20, on 3 September 2026. Target speaking slots:
**project overview 1:00; Feature 1 1:45**. Read only the blockquotes aloud. Everything
else is a direction, evidence reference or background explanation.

Use this with the [recording runbook](presentation-runbook.md),
[Feature 1 assessment](feature-1-rubric-assessment.md) and
[rehearsal evidence](evidence/presentation-rehearsal-2026-09-03.json).
This is a recording plan, not a claim that the final video/report is complete.

## What the university actually requires

The source is the supplied local Canvas capture, not an inferred generic software-demo rubric.

| Source | What determines this plan |
|---|---|
| [Release 0 assignment, full brief and rubric](https://canvas.uts.edu.au/courses/39716/assignments/267942), local file `C:/git/Uni/courses/41026-advanced-software-development/assignments/267942--assessment-1-release-0-agentic-ai-foundations-microservices-devops.md`, fully captured 3 September | Integrated feature; visible CRUD; frontend-callable AI; deployment steps; successful student CI; maximum ten-minute published group video; five-minute Q&A; report evidence. |
| [30 August showcase clarification](https://canvas.uts.edu.au/courses/39716/discussion_topics/806634), local `announcements/806634--week-6-release-0-showcase.md` under the same course folder | **Do not show agentic-loop execution in the video.** Put its technical workflow, execution evidence and logs in the report. AI functionality through each student's frontend still belongs in the video. |
| [3 September reminder](https://canvas.uts.edu.au/courses/39716/discussion_topics/809344), local `announcements/809344--release-0-showcase-tomorrow.md` | Final video ready for Friday 4 September; every member attends and answers Q&A; non-integrated features and non-attendance carry zero-mark consequences. |
| `files/week-0/ASD_2026_Project_Specifications.txt` in the course folder | Frontend/backend/database ownership, CRUD, ten records per table, required diagrams/planning/logs, and later MCP/RAG/multi-agent/cloud requirements. The newer assignment controls the extended deadline and revised video instructions. |
| [Registered feature scope](../architecture/registered-feature-scope.md), [Feature 1 README](../../student-1/README.md), current root README and deployment manifests | Matthew owns Data Platform and Property Discovery. The repository records approval for OpenAI and Feature 1 PostgreSQL/PostGIS; retain the actual written approvals with the submission. |

Submit **group20.pdf** by **6 September, 11:59 pm Sydney time**, with repository and
published video URLs. The literal spec's Ollama/SQLite wording must be reconciled with
the recorded tutor-approved exceptions. Do not call PostgreSQL SQLite or claim a local
Ollama container is running. No future-release rubric was published in the supplied
folder; the separate assessment compares future requirements without inventing marks.

## Coverage map: screen evidence versus report evidence

| Deliverable / criterion | What is actually shown | Other evidence still required |
|---|---|---|
| Project purpose, ownership, unified HTMX entry and shared CSS | Overview: shared home, research-area cards, global Ask AI; Feature 1 remains under `localhost:5100/features/data-platform/` | Team allocation and repository structure in report. Names: Matthew/F1, Burhan/F2, James/F3, Michael/F4, Derek/F5. |
| Frontend → backend → database, implemented feature | F1: source CRUD, accepted release, real property page and map | Architecture/Compose diagrams, health and endpoint evidence. Source ownership and HTTP boundaries explained below. |
| Create, Read, Update, Delete | F1 0:24–0:46: one disposable draft source, shown being created, opened, edited and deleted | Complete uncut CRUD capture and component/browser tests. A map/search is only Read. |
| Populated database, ten records per assessed table | F1 0:12–0:24: published SEIFA's 4,320 rows; property evidence from accepted G-NAF | This is scale evidence, **not proof of ten rows in every table**. Attach an owner-produced table-count audit and resolve exceptions with tutor. |
| Feature AI via its own frontend | F1 1:12–1:27: submit an address question in **Ask about Property data**, show Complete and answer with source references | Current provider/prompt/run metadata and written approval. The global overview chat alone does not satisfy this individual demonstration. |
| Governed acquisition, validation and publication | Data overview → published SEIFA release with review note/hash/counts; short cut to its passing Data checks | Successful ingestion timeline, canonical/export checksums, review decision, receipt and activation evidence. Long acquisition is pre-recorded/report material. |
| Assigned GitHub Actions and build/validation | F1 1:35–1:45: actual successful **Student 1 CI** jobs/steps and **Integration CI** | Workflow files, run URL, SHA, jobs and logs. Student 1's fixture CI does not prove live OpenAI. |
| Docker deployment steps and running integration | F1 1:27–1:35: actual `stack up` command/result and `stack status` capture | Capture full deployment output and health at final recording SHA; all five owners must be integrated. |
| Agentic Plan → Act → Observe → Adapt | **No phase replay, execution terminal or loop walkthrough in this video** | Report: diagram, execution log, own prompts, human review and development-review records for DB, implementation, architecture and DevOps. A successful property chat does not prove all development reviews. |
| Prompt/context engineering, Agile planning, FR/NFR, individual plan and risks, conceptual/ERD/logical/physical data designs | Explained if asked in Q&A, not squeezed into a product walkthrough | Complete report sections, versioned prompt/context examples tied to actual changes/tests, NFR/endpoint tests, sprint backlog and overall project plan. |
| Contributions, attendance, limitations, final demonstration | Matthew narrates these two segments; finish with a handoff | Each member's commits/contribution log, all members at showcase/Q&A, final video URL and PDF. |

“Cover all deliverables” means an explicit evidence destination for every requirement.
The 105-second clip cannot truthfully demonstrate every recovery branch, every table and
every diagram. The assessed UI/AI/deployment/CI essentials stay in the clip; supporting
evidence is assigned to the report rather than silently omitted.

## Group running order

| Group clock | Segment |
|---|---|
| 0:00–1:00 | Matthew: project overview |
| 1:00–2:45 | Matthew: Feature 1 |
| 2:45–4:30 | Burhan: Feature 2 |
| 4:30–6:15 | James: Feature 3 |
| 6:15–8:00 | Michael: Feature 4 |
| 8:00–9:45 | Derek: Feature 5 |
| 9:45–10:00 | Shared closing/credits and transition allowance |

This is a proposed allocation for the other owners, not a claim their recordings exist.
Titles and transitions count toward ten minutes. Each owner needs their own working UI
and AI interaction, and identifiable student-workflow evidence. The shared deployment
clip can be shown once here. **Feature 3 is currently Planned/disabled in the observed
integrated application**: its owner must resolve integration before the final recording.
Do not change the label or narrate all five as working to hide that gap.

## Project overview — target 60 seconds

Keep browser chrome visible enough to establish the common `localhost:5100` application.
The spoken script is 123 words, about 53 seconds at 140 words/minute, leaving seven
seconds for clicks and a natural pause. Rehearse to the time windows rather than rushing.
Do not read the AI answer aloud in addition to the script.

### 0:00–0:15 — the problem and shared home

**Show:** [shared home](http://localhost:5100/#home). Start with the hero and common
navigation. Move the pointer to the address search, then to Research areas.

> PropertyScope NSW brings property research into one shared workspace. Instead of jumping between disconnected sources, a buyer can start with an address and see the evidence, its origin, and its limitations.

**Background, not spoken:** The central idea is a stable property identity with attributed
evidence attached to it. It supports research; it does not promise a valuation, complete
due diligence or a buy/no-buy recommendation.

### 0:15–0:28 — how the team divides the project

**Show:** [Research areas](http://localhost:5100/#features), moving across the cards.
Leave actual Available/Planned badges visible. This sentence describes the project scope.

> Our five areas cover property data, sales and markets, suburb context, site and planning, and the buyer journey. Each student owns a feature within the same application.

**Background, not spoken:** At rehearsal, Features 1, 2, 4 and 5 were enabled, Feature 3
was planned. The cards establish common navigation, not proof of each service's full
functionality. Avoid the stale report statement that Features 2–5 are all unimplemented.

### 0:28–0:45 — ask the project to explain its purpose

**Show:** [Ask AI](http://localhost:5100/#assistant), **All of PropertyScope** scope.
Paste and submit the prepared overview prompt below. Show its actual completed answer.
Record submission and completion; remove waiting time if needed and label the cut.

> The shared assistant can explain the project in plain language. I'll ask about its purpose. Its answer captures our approach: traceable information, visible uncertainty, and evidence you can inspect before relying on it.

**Exact prompt:**

```text
Explain PropertyScope NSW's purpose for a first-time visitor in one short paragraph of at most 45 words. Focus on its big idea: researching NSW properties using traceable data and visible uncertainty. Do not list research areas or make claims about which features are implemented.
```

**Background, not spoken:** Tested successfully in run
`0b4bd24c-8b14-43bc-9e0d-867df603381d` in about 8 seconds with OpenAI/v7.
The answer was 38 words. Only the summary paragraph is length-bounded; the UI also
renders findings and evidence. A fresh conversation is preferable for filming.
The broad “which features work?” question currently reads stale capability metadata;
this prompt has a narrower, verified purpose and is not a fix for that defect.

### 0:45–1:00 — the big idea and handoff

**Show:** Briefly return home, then enter **Property data overview** through the shared
UI. End on the data overview ready for Feature 1, without a new title-card pause.

> The big idea is that every research view starts from evidence we can trace. I'll show the data foundation, then follow one published address through to its map and attributed area data.

**Background, not spoken:** The overview chat demonstrates the shared experience. Matthew
still demonstrates the separate Feature 1 chat below, as the announcement explicitly
requires AI functionality through each student's frontend.

## Feature 1 — target 105 seconds

The spoken script is 205 words, about 88 seconds at 140 words/minute, leaving roughly
17 seconds across the slot for clicks and pauses. The seven windows below reserve
the final 18 seconds for deployment and CI. Capture
actions first and edit to these windows; the prose timing alone cannot guarantee that
live navigation, form submission or an AI provider will finish on cue.

### 0:00–0:12 — start with the data platform

**Show:** [Data overview](http://localhost:5100/features/data-platform/#overview).
Point to Published sources/current data and the update-status summary. Leave any genuine
failure indicators visible; don't launch a lengthy acquisition during this segment.

> My feature manages data sources and property discovery. Updates are validated and reviewed before publication; failed updates leave the previous accepted data available.

**Background, not spoken:** Rehearsal showed six published sources and two update problems,
including an interrupted example and a failed PSI update. Those counts can change; they
are intentionally not hard-coded into the speech. A failed refresh is different from
losing the accepted data. Imported candidates require human review before activation.

### 0:12–0:24 — establish the real published data

**Show:** Open **Published data**, then the
[published ABS SEIFA release](http://localhost:5100/features/data-platform/#releases/1672de46-b88e-400d-9e12-7e9fecad1b0a).
Show **Published**, 4,320 source/product records and review note for six seconds. Cut
to **Data checks** with its three blocking Pass results for five seconds; allow one
second for the next transition. The preview rows including Abbotsbury are optional
report/backup footage, not another mandatory screen within this twelve-second window.

> This published ABS dataset contains all four thousand, three hundred and twenty NSW locality records. Its version, checks, approval and source attribution remain attached to the data.

**Background, not spoken:** This is the complete NSW subset of the official 2021 SAL
workbook, not all Australian areas. The preview shows 25 rows per page; it does not cap
the export. All three observed checks passed: candidate count, NSW scope and schema.
G-NAF's separately accepted generation has 5,190,134 NSW address records. Neither count
proves the university's ten-per-table rule. A local publication receipt is not evidence
that another student's consumer imported this release.

### 0:24–0:46 — prove all four CRUD operations

**Show:** Return to **Data overview → Manage sources**. Use the disposable draft record
from the runbook. Show its filled creation form and press **Create source**; open
**View details**; change the name to append `- reviewed` and press **Save changes**;
then **Delete → Delete definition**, and show its absence. Use cuts for typing, not for outcomes.

> Source definitions support full CRUD. I create this demonstration source, open the saved record, update its name, then delete it. These changes go through my frontend and backend to the owning database service, with the result visible after each action.

**Background, not spoken:** A source definition is governed metadata, not permission
to execute an arbitrary URL. Its attribution URL is metadata; acquisition uses registered
allowlists. Keep the demo record Draft and unreferenced by any job/release, so deletion
is possible and official source records are untouched. Existing-source deletion may be
correctly rejected for referential integrity. Capture the full sequence before editing
the clip; reload after the update to substantiate persistence.

### 0:46–1:12 — follow an actual property to its map and evidence

**Show:** **Property search** → type `20 Heysen Street` → **Search** → open
**20 HEYSEN STREET, ABBOTSBURY NSW 2176**. Show the verified address and loaded map.
Open **Sources and identifiers** briefly to expose G-NAF, then scroll to
**Socio-economic area context**, the decile table, **2021** and the ABS attribution.

> Now I search twenty Heysen Street, Abbotsbury. The accepted address has a stable reference and verified G-NAF identifier, with its point shown on the map. Here, ABS SEIFA adds attributed area context. These are twenty twenty-one locality statistics, not scores for this house or its residents.

**Background, not spoken:** Exact record and expected panels are listed in the runbook.
The point is an address geocode, not a cadastral boundary, legal lot or proof of ownership.
The map basemap's OpenFreeMap/OpenMapTiles/OpenStreetMap attribution differs from the
G-NAF identity source and ABS statistical source. SEIFA uses exact normalised locality
and state, not a spatial join. Keep that interpretation limit visible. There are no
matched accepted PSI sales for this property in the observed stack; don't promise a
sales table in this shot. Four SEIFA deciles are visible, but reading them all wastes time.

### 1:12–1:27 — show Feature 1 AI through its integrated frontend

**Show:** **Ask about Property data**, scope **Property data**, page context
**General Property data question**. Submit the exact address prompt below and cut to
the real completed response. Keep its **Sources used** and run link visible; leave the
phase/activity disclosure collapsed. Do not replay the agentic loop.

> From my feature's AI page, I ask about this address. It checks accepted records and reports missing sale evidence explicitly, instead of inventing a transaction or valuation.

**Exact prompt:**

```text
Find 20 Heysen Street, Abbotsbury NSW 2176 in accepted property records. Summarise its verified address evidence and accepted sale-history availability in at most 45 words. State missing evidence; do not infer value or suitability.
```

**Background, not spoken:** Tested through this UI in run
`5a436835-e8e3-41f1-a00a-4c9a29b2454e`: about 17 seconds, two successful calls
(`property.search.v1`, `property.inspect.v1`), OpenAI/v7. Its answer correctly reports
verified identity and zero returned sale records. Availability of a compatible accepted
PSI dataset is not evidence that this address has a matched sale. These sale-availability
results use the seeded `2026.08.2` sales baseline
(`60000000-0000-0000-0000-000000000002`), not a completed official PSI publication.
The address itself and SEIFA evidence come from accepted official-source generations.
The request flow is
browser → F1 backend → shared AI-mode → approved provider and allowlisted F1 HTTP tools.
The AI service has no Feature 1 database credentials. Use General context because the
current Property record input rejects this valid stored reference; record that defect
in limitations rather than typing a fabricated replacement ID.

### 1:27–1:35 — show deployment, not just a healthy screenshot

**Show:** A short, genuine terminal recording of `uv run scripts/dev.py stack up`
being run, its successful result, then `uv run scripts/dev.py stack status`.
Cut elapsed startup time; show the shared frontend/AI and Feature 1 services.

> Docker Compose starts the integrated services through our stack command. The status output confirms the deployment is running.

**Background, not spoken:** Record this after coordination with the other agent, from
the designated live checkout. The helper composes the base file, enabled-feature
projection and development overlay. The observed runtime had four enabled slices;
final group evidence must include Feature 3 once integrated. Runner/loader are workers
and may show Up without a health badge. Do not claim every container has a healthcheck.

### 1:35–1:45 — close on actual student CI and integration evidence

**Show:** Successful **Student 1 CI** run, its **Feature 1 browser forms** and
**Feature 1 integrated stack** jobs. Show build/start/fixture/smoke steps in the stack job,
then switch to successful **Integration CI / Canonical quality gate**. Use pinned run
tabs prepared from the evidence list; keep the branch/SHA recognisable.

> Student One CI validates browser forms, builds containers and smoke-tests integration. The shared quality gate also passes. These linked runs make the result reproducible.

**Background, not spoken:** This is Release 0 build/validation and local Compose deployment.
There is no evidence here of Azure deployment or automatic production delivery; those
belong to Release 2. Student 1 uses deterministic fixtures without a live provider key.
Fresh presentation-spike runs prove that spike commit, not the final group submission.

## Background explanations for the five-minute Q&A

| Likely question | Answer in your own words |
|---|---|
| Why a data platform as a feature? | One place owns acquisition, validation, provenance and accepted versions. Consumers get versioned HTTP/artifact contracts and import into their own stores. Property Discovery makes that foundation directly useful to a person researching an address. |
| Where is the microservice boundary? | F1 frontend, backend, DB API, loader, runner and PostgreSQL/PostGIS are separate containers. Backend and runner use HTTP to the DB service; only DB API/loader get database credentials. AI-mode uses allowlisted HTTP tools and its own run store. |
| What makes publication safe? | Verified artifacts enter an isolated candidate generation. Quality checks and human review precede publication. Background preparation finishes before a short accepted-version switch, so existing readers keep the previous accepted version during a failed update. |
| What does Verified mean? | Address identity resolved against accepted source records. It is not verification of title, ownership, building safety or market value. |
| What does SEIFA describe? | Relative socio-economic characteristics of the 2021 Suburb and Locality area. It is attached by exact normalised locality/state; it does not describe this household or its residents. |
| What is the AI contribution? | Plain-language explanation based on explicitly allowed tools. The application validates tool inputs/outputs, limits iterations/time/calls and records the final answer/evidence. Free-form chat is read-only; publication remains separate and human-reviewed. |
| Why not Ollama/SQLite? | The project records tutor approval for the OpenAI provider and a narrow Feature 1 PostgreSQL/PostGIS exception. Show the written approval attachment. The service ownership/API boundaries remain intact. |
| What is missing? | Give the current known issue, not an old screenshot: Feature 3 integration, missing sales for the chosen property, stale capability guide, UUID context validation, or outstanding submission evidence as applicable. |
| What comes later? | Release 1 adds local MCP/RAG and evaluated grounded responses. Release 2 adds local multi-agent roles/human review, required testing stages and Azure deployment, with MCP/RAG/multi-agent disabled in cloud. Existing HTTP tools and a shared state machine are foundations, not proof those later servers exist. |
