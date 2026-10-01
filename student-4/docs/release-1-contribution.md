# Student 4 Release 1 integration evidence

Contributor: Michael White, Student 4 (Site, Planning & Building Due Diligence).
Date: 2026-10-01. Feature key `student-4-due-diligence`, API prefix
`/api/due-diligence/v1`, route `/features/due-diligence/#site-reviews`.

Release 1 was adopted, not re-invented. The shared MCP server, RAG server, agent loop,
grounding validation and assistant renderer are shared platform work. This feature
followed `docs/release-1/adopt-mcp-and-rag.md` and contributed the feature-owned parts:
an allowlist and capabilities tool, a guidance corpus, the browser surface, CI cover and
this evidence.

## Contribution commits

| PR | Commit | Scope |
|---|---|---|
| #125 | `bbd112d` | Approve grounded allowlists and add the `duediligence.capabilities.v1` MCP tool |
| #126 | `a6b7b7f` | Add and register the due-diligence RAG guidance corpus |
| #128 | `e0720f4` | Adopt the shared grounded assistant in site reviews |
| #130 | `b4cf74a` | Cover Release 1 assistant behaviour in Feature 4 CI |
| PR 5 | pending | This evidence: validation artifacts, browser screenshots and this document |

## Implemented scope

The request path is browser -> Feature 4 backend -> host AI-mode -> shared MCP/RAG.
Feature 4 added no provider client, no shared service change, no new database table and
no direct database access from AI-mode. The shared host keeps the Plan/Act/Observe/Adapt
loop, retrieval enforcement, identifier validation and grounding validation.

The owning backend exposes these Release 1 routes alongside its Release 0 CRUD:

- `GET /assistant/capabilities`
- `POST /assistant/turns`
- `GET /assistant/turns/<run_id>`
- `GET /assistant/turns/<run_id>/events`
- `POST /assistant/turns/<run_id>/cancel`
- `POST /tools/duediligence.capabilities.v1`
- `POST /tools/duediligence.review.inspect.v1`
- `POST /tools/duediligence.evidence.summary.v1`

All three tools are read-only. `TOOL_ALLOWLIST_V1` is the pair
`duediligence.review.inspect.v1` and `duediligence.evidence.summary.v1`;
`duediligence.capabilities.v1` is additionally allowed so the assistant can state the
feature's own limits. The browser chooses a scope and a selected site review, never a
feature key, corpus, tool list, prompt profile or arbitrary trusted identifier. The
backend rejects foreign-purpose runs and tool lists other than its own.

The frontend reuses the shared `shared/frontend/ai-chat` module rather than a private
chat implementation. `student-4/frontend/app.js` imports `createFeatureAssistant`, and
the hash router tears down `activeAssistant` on route change and `pagehide` so a
conversation never follows the user to another review. The Dockerfile `frontend` stage
copies `shared/frontend/ai-chat` to `/usr/share/nginx/html/ai-chat`.

Three public guidance documents are registered through `student-4/config/rag/corpus.json`
under corpus `operator-guidance`. They are repository-authored operator guidance
(CC0-1.0) and contain no property records:

- `what-this-feature-does` - what the feature does and does not claim
- `evidence-limits` - what its evidence cannot establish
- `evidence-states` - how evidence states and confidence are read

No startup ingestion was added. Ingestion stays an explicit operator step.

## Deterministic validation

`uv run scripts/dev.py ai validate` was run against the live local MCP and RAG servers.
The decision provider is `deterministic-validation` (`extractive-validation.v1`), so
these artifacts prove protocol, allowlisting, retrieval and loop orchestration. They do
not prove a model answer is good. That distinction is recorded in
`docs/release-1/host-runtime.md`.

Artifacts are in `student-4/docs/release-1/evidence/`:

| Artifact | Mode | Passed | Status | Grounding / confidence | Citations |
|---|---|---|---|---|---|
| `validation-mcp.json` | mcp | true | succeeded | n/a (tool `duediligence.capabilities.v1`) | 0 |
| `validation-rag.json` | rag | true | succeeded | `ready` / `moderate` | 1 |
| `validation-rag-insufficient.json` | rag | true | succeeded | `no_match` / `insufficient` | 0 |

All three record `transport: live-local-services` and the full phase list
`plan, act, observe, adapt`. The MCP artifact shows evidence references
`service:propertyscope-due-diligence-backend` and `status:200`. Both RAG artifacts carry
corpus version `64835d6f386e093066fa8b7f683195e8c95fa63750cbf071f56b59c0f19577c4`.

The insufficient case is the important one: an unrelated question
("median apartment rental yield in Bondi") returns `no_match` with zero citations,
`confidence: insufficient` and a recorded evidence gap, rather than an ungrounded answer.

The artifacts were scanned for the RAG, MCP, AI-mode and provider credentials before
staging; none appear in the committed files.

## Runtime observations

These came from the running stack on 2026-10-01, not from fixtures.

### Host AI preparation

`stack up --offline` is not a path to this evidence: `--offline` forces direct mode and
leaves MCP and RAG stopped. The stack and the host AI services were therefore started
with an explicit provider environment file (gitignored, Gemini provider, profile
`gemini-development.v1`).

`ai probe` initially failed with `rag embedding model ready - HTTP 503;
unprepared-local-model`, because startup never downloads model weights. The documented
sequence resolved it:

1. `uv run rag-server prepare-model` - fetched `BAAI/bge-small-en-v1.5`
2. restart the host AI services
3. `uv run --no-sync rag-server ingest student-4/config/rag/corpus.json`

Ingestion produced 3 documents and 8 chunks at 384 dimensions. `ai probe` was then green
for this feature's corpus.

### Live browser evidence

Captured through the running Feature 4 container at `http://localhost:5400` with a real
provider answering, so these show model output, not deterministic validation.
Images are in `docs/reports/assets/release-1/screenshots/`:

| Screenshot | Run | What it shows |
|---|---|---|
| `feature-4-mcp.png` | `239e816a` | Answer plus the 8 recorded steps: Plan, `Context.retrieve.v1` (`service:rag`), `Duediligence.review.inspect.v1` (status 200), Observe, Decision **Continue**, `Duediligence.evidence.summary.v1` (status 200), Observe, Decision **Complete** |
| `feature-4-rag.png` | `f4138c7e` | Grounded answer, **Confidence: High**, "1 guidance source - 1 record check", three findings each citing a source, two of them the `evidence-limits` guidance document |
| `feature-4-insufficient.png` | `680d9db2` | "Insufficient context to provide a grounded explanation.", **Confidence: Insufficient**, evidence gaps listed, no citations invented |

The MCP capture is the clearest agentic-loop evidence: the final decision records a real
adaptation, where the loop corrected a tool argument schema (`evidence_gaps` formatted as
an empty array rather than an empty string) before completing.

The provider returned transient `HTTP 503` on three turns. The assistant surfaced this as
"The assistant could not complete this turn - Model provider returned HTTP 503" with a
"Prepare question again" control, and each question succeeded on retry. That is provider
throttling, not a defect in this feature, and the failure path itself is correct
behaviour: no answer was fabricated when the provider was unavailable.

### Not observed

`f1-db-api`, `f3-database` and `shared-frontend` were unhealthy or restarting for reasons
that predate this branch and belong to other students' slices. They were not modified.
Because `shared-frontend` was down, the shared edge at `http://localhost:5100` was not
used to cross-check run history; every observation above was taken from the Feature 4
container and the host AI services directly.

## Continuous integration

`.github/workflows/student-4.yml` keeps MCP and RAG **disabled** in CI and uses
deterministic doubles, so no job depends on a provider key, a model download or network
access. The Release 1 additions in #130 were:

- `Check browser JavaScript` now runs `shared/frontend/ai-chat/*.test.mjs` as well as
  Feature 4's own frontend tests, because #128 made this feature depend on that shared
  module. Locally: 46 tests pass (22 Feature 4, 24 shared assistant).
- A new step, `Accept Release 1 grounding and assistant behaviour without live AI`,
  running the assistant, grounding, capabilities and corpus tests. Locally: 14 selected.
- `Smoke CRUD, seed and frontend boundaries` now asserts that `/ai-chat/index.js` and
  `/ai-chat/styles.css` are actually served. Both the content type and a body marker are
  checked, because `nginx.conf` uses `try_files $uri $uri/ /index.html`: a missing asset
  would otherwise return `index.html` with HTTP 200 and a naive check would pass against
  a broken image. Verified against the running container, both assets return the correct
  content type and marker.

The existing `Validate R1 contracts and disabled runtime with deterministic doubles` step
was already present before this work and was not changed.

## Boundaries respected

- No other student's slice was edited.
- No shared package gained feature-specific domain logic.
- AI-mode, MCP and RAG remain host processes; nothing was added to a Compose file and
  `ai-services/` still has no Dockerfile (ADR-046).
- AI-mode reaches this feature only through the allowlisted HTTP tool endpoints and never
  opens the Feature 4 database.
- No third-party dependency was added. The only dependency change was #125 adding the
  internal workspace package `shared-testkit` to this feature's `dev` group, with
  `uv.lock` regenerated by `uv` rather than hand-edited.
- Shared files were touched only where registration requires it: `student-4` entries in
  `deployment/enabled-features.v1.json` (generated), the `student-4` service in
  `docker-compose.dev.yml`, and the shared host-runtime/validation tests that enumerate
  registered corpora.

## Changed-file map

| Path | Change |
|---|---|
| `student-4/backend/src/propertyscope_due_diligence/api.py` | Assistant routes, tool allowlist, capabilities tool (#125, #128) |
| `student-4/tool-catalog.yaml` | Declared the three read-only tools (#125) |
| `student-4/pyproject.toml`, `uv.lock` | `shared-testkit` added to the `dev` group (#125) |
| `student-4/config/rag/corpus.json` and `documents/` | Registered guidance corpus (#126) |
| `student-4/feature.yaml`, `deployment/enabled-features.v1.json` | Corpus registration and regenerated manifest (#126) |
| `student-4/frontend/app.js`, `index.html`, `ai-chat/`, `Dockerfile`, `docker-compose.dev.yml` | Shared assistant mount and teardown (#128) |
| `student-4/tests/test_backend_api.py`, `test_rag_corpus.py`, `tests/frontend/core.test.mjs` | Assistant, corpus and frontend cover (#125, #126, #128) |
| `.github/workflows/student-4.yml` | Release 1 CI cover (#130) |
| `student-4/docs/release-1/evidence/*.json` | Deterministic validation artifacts (PR 5) |
| `docs/reports/assets/release-1/screenshots/feature-4-*.png` | Live browser evidence (PR 5) |
| `student-4/docs/release-1-contribution.md` | This document (PR 5) |
