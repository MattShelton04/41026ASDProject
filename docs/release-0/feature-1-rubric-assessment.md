# Feature 1 assessment and future-release gaps

Assessed 3 September 2026 against repository commit
`6fbe1b723ee127a27daeafbf35037f69c8939cdb`. This is an independent preparation
review, not a tutor mark. The strongest opportunity is to package the existing
implementation into current, reproducible assessment evidence. Adding another
data feature is lower priority than proving CRUD, approved AI, integration and
the required report/video.

## Assessment basis and limits

The authoritative local sources reviewed were:

- The [Release 0 Canvas assignment and full 0/1/2 rubric](https://canvas.uts.edu.au/courses/39716/assignments/267942),
  captured on 3 September in
  `C:/git/Uni/courses/41026-advanced-software-development/assignments/267942--assessment-1-release-0-agentic-ai-foundations-microservices-devops.md`.
- `C:/git/Uni/courses/41026-advanced-software-development/files/week-0/ASD_2026_Project_Specifications.txt`,
  especially sections 6.2, 7.2 and the release submission requirements.
- `C:/git/Uni/planning/41026-project-release-checklists.md`, a secondary summary.

Release 1/2 requirements are published in the project specification, but no
complete future marking rubric was available in these supplied materials.
Therefore **no Release 1/2 marks or percentage are invented** below.

This review inspected code, manifests, test definitions and retained evidence. It
also read GitHub Actions status through `gh` and incorporated the presentation
preparer's separately verified, read-only live observations below. It did not start/restart containers,
change live data, invoke a live model, or independently rerun the quality gate.
Recorded historical tests/runs are identified as such. Browser acceptance at the
final recording commit remains necessary.

## Provisional Release 0 score

**Evidence-limited preparation estimate: 14/20.** This is a conservative snapshot
of what a reviewer can substantiate now, including the incomplete submission
package. It is not a prediction of Matthew's final grade or an allocation of
independently awarded Feature 1 marks: several criteria assess the group.
The implementation is stronger than this evidence-completion score suggests.

| Published criterion | Provisional /2 | Evidence and reason | What supports full marks |
|---|---:|---|---|
| 1. Project Setup | 1 | Shared HTMX shell, theme, workspace, workflows, Compose and populated Feature 1 are present. Current [feature selection](../../deployment/features.yaml) enables 1, 2, 4 and 5. Feature 3 is absent from selection; ten records in **every** assessed table is unproven. | Complete five-feature integration and retain a reproducible table-count report or written clarification of the literal table rule. |
| 2. Service Implementation | 2 | Feature 1 frontend → backend → private database API/loader boundaries exist. The verified Student 1 CI run builds and starts its integrated stack and passes the Shared/Feature 1 smoke. | Retain equivalent evidence at the submitted SHA, and show the feature through the shared entry point. This score concerns Feature 1; it does not certify every other feature. |
| 3. AI-Mode Integration | 2 | The integrated Property data assistant successfully used real OpenAI/default.v7 and Feature 1 `property.search.v1` then `property.inspect.v1` in run `5a436835…`; [redacted execution evidence](evidence/presentation-rehearsal-2026-09-03.json) is retained. [Registered scope](../architecture/registered-feature-scope.md) records approval. | Retain this evidence at the submitted runtime and attach durable written approval for the departure from Ollama/open-source wording. This score assumes the recorded approval is accepted. |
| 4. Agentic AI Workflow | 1 | The [agent core](../../ai-services/agent-core/README.md) implements four persisted phases; the fresh Feature 1 run records two complete iterations/eight phases. The report still lacks the final terminal execution/log bundle and each student's development-review record. | Put an identifiable Plan → Act → Observe → Adapt execution in the report, with own prompt assets and reviews of database, implementation, architecture and DevOps. A product evidence/diagnosis run alone does not prove all these software-development reviews. |
| 5. Prompt Engineering and Context Management | 2 | Versioned planner/adapter assets through v7, bounded schemas/context, [agent instructions](../../AGENTS.md), and reusable implementation prompts such as the [PSI adoption plan](psi-parquet-adoption.md) make the context and instructions inspectable. | In the final report, connect one development prompt/context revision to a concrete change, human review and test result. Runtime prompt assets alone would be weaker evidence of AI-assisted development. |
| 6. DevOps and GitHub Actions | 2 | The independently checked Student 1 run passed both browser forms and integrated stack jobs. The canonical Integration CI run also passed at the same SHA; see evidence below. | Show the real workflow/run/logs in the video and refresh success at the final submission SHA. This proves build/validation, not Azure continuous deployment. |
| 7. Docker Compose Integration | 1 | Feature 1 plus Shared builds/runs successfully in CI, and current projections enable four student slices. Feature 3 remains disabled. | One-machine five-feature deployment/health evidence with the approved AI configuration and all required services. |
| 8. Working Software | 2 | [Source fragment routes](../../student-1/backend/src/propertyscope_data_platform/source_fragments.py) implement GET/POST/PUT/DELETE through the private store client; [component tests](../../student-1/tests/component/test_source_fragments.py) cover create, update/version conflict and delete. The CI browser form job passed. | Show visible create → read → update → delete of a disposable source definition in the integrated app. Property search/map alone is Read, not CRUD. |
| 9. Technical Report | 1 | The [report scaffold](../reports/release-0-technical-report.md) contains architecture, diagrams, evidence links and planning, but retains numerous TODOs and stale implementation/contribution statements. The final PDF and complete evidence bundle were not reviewed. | Reconcile current topology, tables, contributors and workflow results; complete individual requirements/data designs/risks, NFR and endpoint tests, approvals, logs, video URL and final PDF. |
| 10. Project Demonstration | 0 | A published, completed group demonstration was not available to this reviewer. A script is preparation, not demonstration evidence. | Publish a ≤10-minute video showing every student's integrated feature, AI mode, deployment steps and CI/CD, and include its URL in the PDF. |

The table sums to 14. Some ratings depend on accepting historical execution
evidence and the team's recorded approvals. If the final report remains
substantially incomplete, criterion 9 could be 0 under the literal rubric. A
different marker may require fresher runtime evidence for other rows. Conversely,
closing the named evidence gaps can improve the score without expanding Feature 1.

The assignment explicitly makes a non-integrated individual feature, and
non-attendance at the showcase, zero-mark risks. Feature 3's disabled status is
a group integration problem and a direct risk to its owner's assessment; the
materials do **not** establish that it automatically gives every other student
zero. Every member still needs to attend and demonstrate their own contribution.

### Independently checked CI evidence

Both runs below completed successfully on 3 September at
`f787250098abccfc279b9d814ee5f9e7a0e013dc`:

- [Student 1 CI, run 33741678659](https://github.com/MattShelton04/41026ASDProject/actions/runs/33741678659):
  **Feature 1 browser forms** and **Feature 1 integrated stack** passed.
  The stack job passed image builds, Compose startup, the deterministic fixture
  acquisition pipeline and Shared/Feature 1 boundary smoke.
- [Integration CI, run 33741678658](https://github.com/MattShelton04/41026ASDProject/actions/runs/33741678658):
  completed with conclusion `success`.

These are verified historical GitHub results, not an assertion that
`6fbe1b7` or any later presentation-spike commit has passed. The Student 1 workflow
uses an offline fixture and does not validate a real OpenAI request. Its browser
forms and container smoke provide complementary evidence; they should not be
described as one full browser-to-PostgreSQL CRUD capture.

### Current live observations supplied by the presentation preparer

The main preparation agent independently checked the running stack on 3 September
and supplied these observations to this reviewer. The whitelisted
[rehearsal evidence](evidence/presentation-rehearsal-2026-09-03.json) retains public
final responses and execution metadata. Its live stack is source-mounted from
the concurrently edited primary checkout, so it is not proof of the presentation
branch or final submission SHA:

- Shared home on port 5100 shows Features 1, 2, 4 and 5 as Available and Feature 3
  as Planned. Enabled HTTP/database containers report healthy; the acquisition
  runner and database loader are running and have no healthchecks.
- Shared overview chat run `0b4bd24c-8b14-43bc-9e0d-867df603381d` succeeded from
  `2026-09-03T10:04:05.653Z` to `2026-09-03T10:04:13.954Z`, using `default.v7`,
  `remote-standard.v1`, OpenAI planner/adapter metadata and `platform.capabilities`.
  This provides current shared overview evidence.
- Feature 1 run `5a436835-e8e3-41f1-a00a-4c9a29b2454e` succeeded from the integrated
  `#assistant` page in **Property data** scope, using **General context** and an
  exact-address question. The retained metadata spans
  `2026-09-03T10:06:21.40739Z`–`2026-09-03T10:06:37.971502Z`. It records
  `default.v7`/`remote-standard.v1`, OpenAI planner/adapter execution, two complete
  four-phase iterations, and `property.search.v1` followed by `property.inspect.v1`.
  The answer correctly reports a current authoritative G-NAF identifier and zero
  returned matched sales. This closes the earlier gap in current Feature 1 AI
  integration evidence and raises criterion 3 from 1 to 2, subject to approval.
- The real property **20 Heysen Street, Abbotsbury** is property reference
  `8060a0b4-96a2-6de3-be6b-00f6e844141f`, G-NAF PID `GANSW711351856`. Its map and
  SEIFA panel were verified against accepted releases; the G-NAF release contains
  5,190,134 address records and SEIFA contains 4,320 area records. Its sales panel
  has **zero matched sales**. Show that limitation honestly or select another
  verified property if sale-history evidence is required.
- An earlier shared overview run `1ec67f1a…` repeated stale capability-guide
  claims that Features 2, 4 and 5 were planned. A focused purpose question gave a
  suitable overview, but that does not repair the underlying stale context.
- The **Property record** assistant context rejects this existing property's
  reference before submission. [The browser adapter](../../student-1/frontend/integration/assistant.js)
  restricts UUID strings to versions 1–5, while this stored reference has a `6`
  version nibble and the backend accepts it. **General context** with the exact
  address is the verified working demonstration route. The presentation
  documentation does not repair the input-validation mismatch.

These observations establish current running examples, not a complete full-stack
acceptance test. The preparation package should retain redacted metadata and
screenshots, identify the runtime checkout, and avoid exporting private reasoning.

## What Feature 1 already does well

- **Meaningful vertical slice:** governed acquisition, immutable candidate
  releases, human publication review and property discovery have clear ownership.
  Show data overview → accepted release evidence → property detail to connect
  backend work to user value.
- **Traceable data:** accepted generations, source attribution, explicit unknowns,
  schema/checksum validation and versioned HTTP consumer contracts are strong
  foundations for future grounding. Existing large-source records demonstrate
  scale, but their dates, selected scope and candidate/accepted state must remain
  visible. Historical counts do not certify the currently running database.
- **Real integration:** shared navigation, a common design system, HTTP service
  boundaries and independently owned PostgreSQL/PostGIS persistence are testable.
- **Reviewable AI:** durable runs, bounded tools, versioned prompts, evidence and
  protected-action review provide more useful context than a generic chat reply.

## Prioritised improvements before Release 0

1. **Finish evidence that can otherwise cost several rubric points.** Retain
   current approved-provider AI output and an agent-loop terminal/log record;
   attach the signed OpenAI and PostgreSQL/PostGIS approval evidence. Existing
   repository statements record approval, but cannot substitute for its source.
   Capture representative CRUD through the shared UI and show real successful CI.
2. **Coordinate the group gap.** Feature 3 is not enabled and its workflow is
   still an always-skipped scaffold. Its owner must integrate and demonstrate it.
   Check the other enabled slices at runtime; an enabled manifest alone is not
   proof of complete working features. Preserve each student's ownership.
3. **Replace stale report and AI-context claims.** At this assessment's base commit the report,
   Release 0 index and parts of scope/AI documentation still claim Features 2–5
   are unimplemented. Some also show old model, counts, contributor snapshots,
   or a video segment for agentic-loop execution. Use the current manifests,
   final commit and actual evidence; do not copy these passages into narration.
   The live overview also exposed stale capability-tool guidance. Correct that
   guidance in an isolated change and verify the enabled/planned distinctions;
   a carefully worded presentation prompt is only a recording workaround.
4. **Resolve table-count evidence.** Ten deterministic fixture properties and
   millions of imported addresses do not prove ten rows in every operational,
   mapping or serving table. Generate a schema-qualified count inventory, explain
   legitimate empty/control tables and obtain any needed tutor clarification.
   Do not fabricate operational history merely to pad counts.
5. **Record and rehearse the required package.** A 1:45 Feature 1 slot needs
   deliberate time for CRUD, a short AI result and CI evidence. Maps/provenance
   enrich the demonstration, but cannot replace these. The overview can introduce
   the shared shell and project idea; a generic “what is this project?” answer
   alone is weaker proof of Feature 1's own AI path.
6. **Fix the Property record context validation in a focused follow-up.** Align
   the browser's accepted reference format with the API contract and real stored
   identifiers, with a regression case for the demonstrated reference. Keep the
   proven General context/address route for recording until that fix is verified.
   This is a bounded assistant-context defect; source CRUD and the successful
   feature-scoped address question remain working.

The updated assignment/30 August announcement moves agentic-loop **execution**
out of the video and into the technical report. The video must demonstrate
deployment and CI/CD instead. Keep ordinary user-facing AI in the feature
demonstration; avoid spending its 1:45 budget reading technical loop traces.

## Future releases: requirement gap analysis, without invented marks

| Published requirement | Current evidence | Remaining work / useful acceptance evidence |
|---|---|---|
| Release 1: retain Release 0 | Strong Feature 1 implementation; evidence and group gaps above | Close the Release 0 package before treating it as a complete baseline. |
| Release 1: local MCP server | `ai-services/mcp-server/` contains only `.gitkeep`; HTTP tool catalogues already exist | Implement a real MCP service/adapter using the approved contracts. Record a request/response through the integrated feature, including invalid input and unavailable-service handling. A JSON tool catalogue is not an MCP server. |
| Release 1: local RAG server and grounded answers | `ai-services/rag-server/` contains only `.gitkeep`; accepted releases and provenance are useful inputs | Define a bounded permitted corpus, ingestion/indexing/version lifecycle, retrieval interface and evidence-bearing answers. Evaluate relevant/irrelevant retrieval, stale releases, unsupported questions and citation correctness. Existing SQL/tool lookups must not be relabelled as a completed RAG server. |
| Release 1: integrated Compose, workflows, tests, report and video | Release 0 integration framework exists | Add actual local MCP/RAG services and Student 1 checks; retain architecture/request/retrieval flows, grounded-response evidence and the new video. |
| Release 2: local planner, worker, reviewer and human-review multi-agent service | `ai-services/multi-agent-server/` contains only `.gitkeep`; current core has phases and review gates | Implement observable role delegation, bounded messages/state, reviewer feedback and human control. Current planner/adapter phases or parallel HTTP calls alone do not establish the required multi-agent server. |
| Release 2: pre-commit pytest and post-commit AI-assisted unit tests | `.pre-commit-config.yaml` runs lint/format/type checks; its full pytest gate is at **pre-push**. Current CI is deterministic. | Add the specifically required pre-commit pytest path and post-commit AI-assisted testing workflow, with retained before/after evidence and human validation. Do not claim pre-push testing already satisfies the named pre-commit requirement. |
| Release 2: Azure deployment and gated cloud workflow | Azure is approved; `.github/workflows/cloud-deployment.yml` is disabled scaffold | Implement deployable configuration and a workflow that follows successful individual workflows; collect cloud health, deployment and failure evidence. Keep MCP/RAG/multi-agent disabled in cloud, and the approved AI mode enabled, per the specification and approved exceptions. |
| Release 2: testing, security and deployment readiness | Deterministic suites, strict service boundaries and source-scale benchmark evidence exist | Define NFR targets and measure them; add cloud authentication/authorisation or disable operator mutations before public exposure, as already required by the Feature 1 plan. Preserve licensing, secrets, data ownership and migration/recovery controls. |

The highest-value future Feature 1 work is to reuse its accepted-release and
provenance boundary for demonstrable MCP/RAG integration, then add the specified
multi-agent/testing/cloud capabilities. Source volume, a polished map and more
charts cannot stand in for those named deliverables.

## Review handoff

This assessment made no production changes and ran no new test suite. Read-only
checks covered repository status, current feature selection, relevant workflow
and route/test definitions, placeholder future services, historical evidence and
the GitHub runs listed above. Reassess the scores after the final report, video,
approval attachments, runtime evidence and submitted-SHA CI results are present.
