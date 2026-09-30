# Student 5 Release 1 integration evidence

Contributor: Derek Song, Student 5. Date: 2026-10-01.
Work started on `main` at `a6b7b7f` with a clean working tree.
Contribution commit IDs: **pending**. Nothing has been committed, pushed or merged.

## Implemented scope

The request path is browser -> Student 5 backend -> host AI-mode -> shared MCP/RAG.
The shared host retains the Plan/Act/Observe/Adapt loop, retrieval enforcement,
identifier validation and grounding validation. No provider client, shared service
change, new database table, authentication system or Student 3 evidence integration
was added. Existing CRUD and Release 0 summary endpoints remain available.

The owning backend now exposes these routes under `/api/buyer-workspaces/v1`:

- `GET /assistant/capabilities`
- `POST /assistant/turns`
- `GET /assistant/turns/<run_id>`
- `GET /assistant/turns/<run_id>/events?after=<cursor>`
- `POST /assistant/turns/<run_id>/cancel`
- `POST /tools/buyer.capabilities.v1` with an empty object

Browser input chooses a guidance or selected-case scope, never an owner, corpus,
feature, tool list, prompt profile or arbitrary trusted identifier. The backend
checks the selected case against its configured owner before submission and every
read/events/cancel. It rejects foreign-purpose runs and all but its exact own
tool lists (with the shared retrieval-tool variant). `default.v9` is selected;
AI-mode injects grounding from the registered feature corpus when enabled.
Questions, history, notes and passages remain untrusted data. Tools are read-only.

The shared frontend offers Workspace guidance (RAG) and Case records (MCP) scopes.
These are scopes, not independent service toggles: combined host mode can retrieve
guidance for either. Changing the selected buyer case creates a separate
conversation, preventing history or active context from following another case.
The shared renderer presents citations, typed findings, confidence and reason,
evidence gaps, insufficient-context and service errors. Grounded answers preserve
their corpus version and raw citation metadata; legacy summaries still render.
Domain-name substitution only changes user-facing text, not raw evidence sources.

Five public guidance documents are registered through the feature manifest. They
contain no private buyer records. See `../config/rag/README.md` for the explicit
ingestion procedure. No startup ingestion or index access was added. Source links
become published references after merge; no commit link is fabricated.

Standalone configuration uses `127.0.0.1:5005`; existing Compose configuration
continues to use `host.docker.internal`. Only Student 5 frontend mounts/assets were
added. AI services remain outside Compose. Student 5 CI keeps MCP/RAG disabled,
offline provider configuration and deterministic fakes; it adds assistant coverage
and the shared source-renderer tests. No dependencies or lockfile were changed.

## Deterministic validation

- Initial complete Student 5 Python suite: **162 passed**, **83.49% coverage**, above 80%.
  After the selected-case task-scope regression fix: **164 passed** (without a
  coverage rerun in that focused check).
- Student 5 JavaScript: **29 passed**; shared ai-chat regression tests: **24 passed**
  (53 passed together). Shared renderer tests cover source disclosures, safe links,
  confidence reasons and insufficient context without invented source cards.
- Student 5 strict Mypy: **31 source files passed**.
- Student 5 Ruff format/lint, frontend style baseline, generated deployment drift,
  manifest/tool-catalogue validation, architecture, workspace packaging and
  `uv lock --check`: passed.
- Integration asset checks parse the development YAML and confirm the exact shared
  chat and Student 5 module mounts and build copies.
- Canonical gate: format, lint, contracts, deployment drift, architecture,
  packaging, model/catalogue validation, styles, Mypy (297 files) and all JavaScript
  syntax checks passed. Shared/core suite: **1027 passed, 2 failed, 18 skipped**,
  **90.94% coverage**. The fail-fast gate stopped there, before its feature suites;
  Student 5 and shared chat suites were run independently as reported above.
  Windows skips cover symlink privileges, POSIX-shell tests and absent Playwright
  Chromium. No unchanged Student 1 PyArrow typing failure occurred in this run.

Tests use injected deterministic doubles, including foreign-owner/run rejection,
case deletion, trusted-scope injection attempts, legacy and grounded completions,
citations, confidence, no-match/empty/unavailable/insufficient-context responses,
AI outages, host-token/correlation forwarding, event/cancel boundaries and CRUD.
These are not successful live model interactions or a security proof against every
possible adversarial prompt.

### Shared acceptance-test correction

Reproduce with:

```text
uv run pytest scripts/tests/test_host_runtime.py::test_corpus_scopes_come_from_enabled_declarations scripts/tests/test_release1_validation.py::test_feature_without_a_corpus_is_told_what_to_declare --no-cov -q
```

Reproduced before correction: **2 failed**. The first copies the real enabled projection into an isolated
fixture but does not copy Student 5's newly declared corpus, and expects only the
older corpus tuple. Production correctly refuses that incomplete fixture. The
second explicitly expects `resolve_corpus("student-5-buyer-journey")` to raise,
which is no longer true once Student 5 adopts RAG. This is a stale shared-test
assumption, not evidence that the live service can retrieve the new corpus.

With explicit authorisation, corrected only `scripts/tests/test_host_runtime.py`
and `scripts/tests/test_release1_validation.py`. The isolated fixture copies existing
declared corpus manifests while deliberately missing manifests remain absent.
Expected scopes derive from declarations, with explicit Student 5 and overridden
Student 2 assertions. Corpus resolution is checked against the owning manifests
for Students 1, 2, 4 and 5. Student 3 still exercises the genuinely unregistered
corpus error. No runtime behaviour, assertions about missing manifests or CI
checks were disabled. Both affected test modules: **38 passed**.

Canonical rerun on 1 October 2026: `uv run python scripts/check.py` **passed
(exit 0)**. Formatting, lint, contracts, deployment drift, architecture, packaging,
model/tool catalogues, frontend styles, strict typing and JavaScript syntax passed.
Python results: shared/core **1032 passed, 18 skipped** (90.94% coverage);
Student 1 **882 passed, 72 skipped**; Student 2 **34 passed** (81.17%);
Student 3 **105 passed, 1 skipped** (91.29%); Student 4 **86 passed** (90.19%);
Student 5 **164 passed** (83.49%). All enforced coverage thresholds passed.
Combined shared/student JavaScript suite: **238 passed, zero failed or skipped**.
`git diff --check` and all six local evidence-directory/artifact links passed.
The skips reflect optional test prerequisites/platform limitations, not new skips
introduced by this correction. No remaining canonical failure was observed.

## Actual runtime observations

### Initial failed attempt (historical)

The initial inspection could not find Docker on PATH or at its standard installation
path and found the host AI services stopped. The initial named validations failed:
MCP run `009928a5-68dd-4cfa-b0d2-ed017bb4f4de` reported `mcp_unavailable`;
RAG run `2a4c8d9f-db32-4d9a-9a53-55b717f88f88` returned unavailable retrieval,
insufficient confidence and no citations (`passed: false`). These are historical
failures, not the final readiness state.

Subsequent inspection found the per-user Docker Desktop installation. Targeted
rebuilds resolved stale dependency images and the shared Nginx startup failure,
preserving the existing database volumes. Host AI-mode and MCP probes passed.
RAG was running but initially returned HTTP 503, `unprepared-local-model`.

### Successful preparation, ingestion and validation

On 1 October 2026 (Australia/Sydney), the supported preparation command downloaded
and hashed the real FastEmbed `BAAI/bge-small-en-v1.5` model. Its identity is
`BAAI/bge-small-en-v1.5@82a556141f0473c60c5b9302c9d597373f79070324d8d4f7750af4ad6211b659`.
No fixture embeddings or grounding bypass were used.

Commands actually executed from the repository root:

```text
uv run --no-sync rag-server prepare-model
uv run --no-sync scripts/dev.py ai stop rag
uv run --no-sync scripts/dev.py ai start --mode combined
uv run --no-sync scripts/dev.py ai probe
uv run --no-sync rag-server ingest student-5/config/rag/corpus.json
uv run --no-sync scripts/dev.py ai validate mcp --feature student-5-buyer-journey
uv run --no-sync scripts/dev.py ai validate rag --feature student-5-buyer-journey
uv run --no-sync scripts/dev.py ai validate rag --feature student-5-buyer-journey --query "How do I bake sourdough?"
```

The managed RAG token was loaded by the documented process without printing it.
Authenticated `GET /health/ready` returned HTTP 200, `status: ok`,
`embedding_mode: semantic`. Explicit ingestion returned **5 documents / 5 chunks**,
**384 dimensions**, at `2026-09-30T19:29:47.330375Z`.
Corpus version:
`b8c5424bc339808fbf27a49a765f89124b57f1c6f72ad8c2146eede592c2fb9d`.

Authenticated corpus metadata and six focused `POST /api/v1/retrieve` checks
confirmed the same version. With the unchanged 0.55 score floor, top-k 5 and
5,000-character budget, the five supported questions each returned the expected
source first: `buyer-cases`, `shortlist-and-stages`, `notes-and-tasks`,
`evidence-limits` and `responsible-ai`. The unrelated sourdough question returned
`no_match` with no sources. This is bounded source-retrieval evidence, not proof
of general answer quality.

| Validation | Actual result | Recorded run |
| --- | --- | --- |
| MCP | Passed; `buyer.capabilities.v1` returned public read-only capabilities | `f5b011d7-8c95-49b9-8d36-cf408167a40a` |
| RAG | Passed; ready, cited guidance, moderate confidence | `0b379f3c-32dd-4341-8c73-b4645003c86a` |
| Off-topic RAG | Passed; no match, insufficient confidence, zero citations | `61f95c85-81df-44ab-8341-46012fcebcda` |

All three named validations completed Plan, Act, Observe and Adapt. They used
**deterministic validator decisions with live services and real semantic embeddings**,
not provider-generated browser answers. Their run IDs belong to temporary validator
stores, not demonstrated durable AI-mode provider history.

The reviewed portable outputs are preserved in the repository's documented
[Release 1 evidence location](../../docs/release-1/evidence/),
not only under ignored temporary storage. Five JSON artifacts retain actual results,
correlation IDs, citation/source metadata, model/corpus hashes and limitations.
Review found no credentials, secret tokens, private case content or machine-specific
paths; no redaction or result changes were necessary.

Retained artifacts (relative links checked against the working tree):

- [Ingestion](../../docs/release-1/evidence/student5-ingestion.json)
- [Readiness and source retrieval](../../docs/release-1/evidence/student5-readiness-and-retrieval.json)
- [Named MCP validator](../../docs/release-1/evidence/student5-mcp-validation.json)
- [Named RAG validator](../../docs/release-1/evidence/student5-rag-validation.json)
- [Named off-topic RAG validator](../../docs/release-1/evidence/student5-rag-no-match-validation.json)

The final whole-workspace probe passed Student 5 corpus, grounded retrieval and
insufficient-context checks. It still failed for un-ingested Student 1/2/4 corpora
and an unregistered Student 3 corpus. Those scopes were not changed.

### Live API/provider and manual browser verification

The task question initially returned truthful insufficient context because the
Student 5 frontend defaulted a selected case to guidance scope. Run
`beec4625-ed3c-40a9-8eeb-127b687e2e2d` did not permit or call the task tool.
The frontend now defaults a selected case to case scope; explicit guidance mode
remains restricted. Ownership and shared grounding checks were not changed.

Live API/provider verification run `b15a0ccd-6b24-4f45-89f4-66dcd677b5ea`
successfully called `buyer.tasks.list.v1` with the selected buyer-case identifier,
returned its outstanding task and preserved a call-linked `tool_fact`, with ready
grounding and moderate confidence. This was a real provider run through the public
Student 5 API, not a named deterministic validator or automated browser test.
Private task content and full run payloads are not copied into the public corpus
or portable evidence files.

**Derek manually verified the browser task lookup successfully**, as confirmed
by Derek. This is human-reported browser evidence, separate from the agent's
observed API/provider run; no screenshot or browser recording is claimed here.

## Unified Buyer workspace assistant

The duplicate Release 0 summary chat panel was removed from the frontend; its
create/read API remains unchanged for compatibility. The visible summary shortcut
now submits `Summarise this case` through the same case-scoped assistant form and
turn endpoint as typing it. The selected case is visibly labelled; MCP case-record
and RAG workspace-guidance scopes, cancellation and activity inspection remain.
Case-summary instructions retain all four read-only case tools, a concise summary,
practical actions, source attribution and explicit gaps without overriding shared
confidence or insufficient-context decisions.

Before editing, actual runs `c37ec297-ebc9-410b-b8b4-4a6a0562730a` (old summary
button) and `5cc9398b-70e1-4a96-ae8f-48bc35649fa3` (typed summary) were compared.
Both used the same case, corpus, `default.v9`, four case tools and ready retrieval.
The old objective explicitly requested a bounded summary/actions; the assistant
objective was general question answering and additionally allowed capabilities.
Their retrieval queries and cited passages differed. The shared policy retained
the former's Low assessment for unresolved/conflicting evidence and derived
Moderate for the latter from citations, record checks and explicit gaps. Neither
confidence was rewritten by Student 5; the shared policy was not changed.

Live browser verification at `http://localhost:5500` produced successful run
`42438ca3-e59f-4c15-b97c-3ca3e5aaec16` through the shortcut. It invoked retrieval
and all four case tools and displayed the selected case, cited findings, Moderate
confidence/reason, three evidence gaps and five practical actions in one conversation.
Sources & activity opened with the recorded case scope and tool/source references;
both scope options were present, and cancellation controls appeared while running.
No browser warnings/errors were recorded. This is live browser/provider evidence,
not a deterministic named validator. No private run payload was added to the corpus.

A typed follow-up with the same summary request produced run
`90f14aec-b931-4e0c-9bee-929049074810`. Its trusted case, tool allowlist and corpus
matched the shortcut, and retrieval plus all four case tools succeeded. The shared
loop then stopped it with `run_stalled` (planner repeated the previous plan after
successful tool evidence). The browser displayed the failure and retained activity
inspection. This is a recorded live-provider limitation, not a second successful
answer; no shared loop safeguard was bypassed or changed.

Post-consolidation checks: canonical `uv run python scripts/check.py` passed
(exit 0), including **168 Student 5 Python tests**, **83.49% coverage**, and
**233 combined JavaScript tests**. Student 5's focused JavaScript suite passed
**24 tests**; six tests of the removed summary panel were replaced by unified-path
coverage rather than retained against dead rendering code. Strict Student 5 Mypy
passed **31 files**. Ruff, syntax, architecture, packaging, deployment drift,
frontend style validation and `git diff --check` passed. Existing platform and
optional PostgreSQL/Chromium test skips remain as documented above.

## Public evidence audit and case-only shortcut (1 October 2026)

Student 5 now reads Suburb analytics' documented published context endpoint,
using exact uppercase/whitespace-normalised NSW locality names. Buyer target
suburbs and verified Property discovery locations are separately labelled;
neither postcode inference nor stored address labels substitute for verified
locations. Requests, retained records and response sizes are bounded. Source
provenance, reporting periods and limitations remain in the evidence response.
This supersedes the earlier hard-coded unavailable integration.

The Sales research and Due diligence list adapters now send the documented
`limit=25`. Property discovery fixture/partial coverage, excluded sales and
partial/unavailable Due diligence observations are not promoted to complete.

Read-only live checks against all four public APIs found:

- Property discovery's verified Sydney identity came from the seeded demonstration
  baseline; the documented data-status check confirmed fixture/GNAF/sales/crime/
  schools releases are demonstration data, not a full official import.
- Sales research returned 10 saved cases. The inspected evidence had 12 sales,
  2 eligible and 10 excluded, with synthetic-data and insufficient-sales limits.
- Suburb analytics had no active published sources (two failed inactive imports).
  Wollongong and Sydney context responses contained no published records. Student
  5 correctly displayed Unavailable, not zero incidents or retrieved evidence.
- Due diligence returned 7 constraint and 5 building observations including
  partial/unavailable states; Student 5 displayed Partial.

The browser showed separate Wollongong target context and verified Sydney
property-location context. The summary shortcut was hidden on the list, visible
inside the case, and hidden again after returning; the selected case was cleared
and Workspace guidance remained available. No buyer records were changed.

Explicit ingestion used `uv run rag-server ingest student-5/config/rag/corpus.json`
with the existing local service credential (not recorded here). It ingested
5 documents / 5 chunks using the configured 384-dimensional local embedding model.
Corpus version: `4e7dfcd5c8ee07839d9c2140fe63a9999611cd5736bc2b2702528f8d577a5cc4`.
The named RAG validator, queried about target versus verified property locations,
passed in run `59418a3c-e31a-4b5d-8aab-d41aa458b660` and cited `evidence-limits`
edition v2 from that version. This is deterministic validation over live local
services, not live provider-generated answer evidence. Non-empty published suburb
records were tested with injected fixtures; none were available for live verification.
Commit IDs remain pending.

Focused validation: 184 Student 5 Python tests passed with 83.57% coverage;
26 Student 5 JavaScript tests passed. Strict Student 5 Mypy passed 31 files.
The initial canonical run caught the corpus document's 1,200-character bound;
the guidance was shortened, re-ingested and retrieval-verified before retesting.
The final canonical `uv run python scripts/check.py` passed (exit 0), including
235 combined JavaScript tests, Ruff/formatting, syntax, typing, architecture,
packaging, catalogues, frontend styles and generated-deployment drift checks.
`git diff --check` passed. The gate retained 91 existing optional/platform skips
across the shared and other-feature suites; Student 5 had no test skips.

## Remaining assessment tasks

1. Extend the verified task lookup with retained browser evidence for grounded
   guidance answers, citations/confidence, insufficient context, dependency outages
   and unaffected CRUD. Capture screenshots and actual provider run/request IDs;
   the task lookup alone does not establish this broader matrix.
2. If required for assessment, separately verify corpus replay/restart persistence
   and broader answer quality; the present captures do not establish either.
3. Add real commit IDs and verify published source links after approved commits
   exist. All commit IDs remain pending.

## Changed-file map

- Backend: `assistant.py`, `grounded.py`, `api.py`, `app.py`, `configuration.py`,
  `integrations.py` under `backend/src/propertyscope_buyer_workspaces/`.
- Frontend: `frontend/assistant.js`, `frontend/app.js`, `frontend/index.html`.
- Registration/build: `feature.yaml`, `tool-catalog.yaml`, `Dockerfile`.
- Guidance: `config/rag/corpus.json`, `config/rag/README.md`, and five documents
  under `config/rag/documents/`.
- Tests: `tests/test_backend_api.py`, `tests/test_integrations.py`,
  `tests/test_tool_catalog.py`, `tests/test_frontend.py`,
  `tests/test_integration_assets.py`, `tests/frontend/assistant.test.mjs`.
- Owning CI: `.github/workflows/student-5.yml`; frontend mounts only:
  `docker-compose.dev.yml`; generated manifest projection:
  `deployment/enabled-features.v1.json`.
- This contribution/evidence document.

No Student 1-4 implementation or shared AI service semantics were changed.
