# Release 1: Shared and Feature 1 implementation

Status: reviewed and approved for implementation after resolving the eight findings below.
Baseline: `fa08c61`.
Owner: Matthew Shelton. Branch: `Matt/Release_1_Shared_and_Feature_1`.

## Outcome and scope

Deliver working local MCP and RAG services used by Feature 1's existing assistant, with
inspectable, validated citations, reproducible ingestion and deployment, deterministic CI,
and live Docker/browser evidence. Retain all Release 0 behavior and provide the common
contracts, registration recipe and disabled-CI configuration other feature owners need for R1.
The parent [delivery plan](release-1-delivery-plan.md) and archived 41026 specification
remain background requirements. The newer rubric supplied by the user on 6 September takes
precedence: **AI-mode, MCP, RAG and the agentic loop run as non-containerised local processes;
none may be defined as Compose services. MCP/RAG remain disabled during CI/CD execution.**
It additionally requires confidence categories and separate MCP/RAG agent-loop validation
modes. This increment owns Shared and student-1, not Features 2–5.

Feature 1's bounded task is **explain published property coverage and diagnose import
failures using current owning-tool facts plus versioned operator guidance**. The initial
corpus is repository-authored, explicitly reusable project guidance about publication,
partial PSI scope, missing evidence, provenance and recovery. It is not official publisher
methodology or evidence of current property conditions. No private notes, raw warehouse,
new statewide datasets, or unagreed Feature 4 product enter this corpus.

## Architecture and decisions

1. Keep the deterministic four-phase runner and AI-mode's exclusive run store. A new
   `shared-tool-runtime` package extracts neutral catalogue parsing and bounded HTTP
   dispatch for reuse by AI-mode and MCP; it imports shared contracts, not agent-core or
   feature implementations. Existing AI-mode imports remain compatibility facades.
2. MCP uses a pinned supported official Python SDK, stateless Streamable HTTP and
   structured results. Project enabled catalogues as individual protocol tools with their
   original schemas/side-effect annotations. Supply correlation, feature/run scope and
   validated call metadata outside model arguments. Authenticate service calls; validate
   scope, argument schema and approval again before the same owning HTTP endpoint.
   Context resources expose only approved catalogue metadata. No arbitrary URL dispatch.
3. RAG is a separate host Flask service with its own SQLite metadata/vector index and model
   cache directories outside Git. Use local FastEmbed BGE-small English CPU embeddings (384 dimensions),
   pinned library and recorded model identity. Tests inject deterministic embeddings;
   a fixture embedding mode is explicitly labelled and never reported as semantic quality.
   No remote embedding transfer. Prepare model assets explicitly before the demonstration.
4. Explicit authenticated ingestion accepts a bounded, complete feature-owned document
   batch with source/license/status metadata. The first adapter reads approved local
   text/Markdown corpus manifests; HTTP ingest accepts their normalized text, never fetches
   arbitrary supplied URLs. Normalize, bounded chunk, hash, embed in small batches, validate
   dimensions/finiteness, then atomically activate a complete version. Identical content is
   idempotent; changed content creates a version; omitted documents are withdrawn on full
   replacement. Failed refresh retains prior active version. Bound retained versions and
   document/chunk/index sizes; historical run excerpts remain self-contained.
5. Neutral versioned `CorpusDocument`, `CorpusIngestRequest`, `CorpusVersion`,
   `RetrievalRequest`, `RetrievalResponse` and `EvidenceCitation` contracts carry feature,
   corpus/version, document/chunk ID, content hash, title, URI, location, source date,
   ingestion time, evidence kind, excerpt and score. Retrieval has explicit ready/no-match/
   empty/unavailable outcomes, top-k/context limits and scope/filter validation before search.
   Public project guidance is the only initial access class. Private owner/case corpora are
   rejected until their owner supplies an authenticated scope contract.
6. AI-mode registers an approved feature-scoped retrieval capability from startup corpus
   configuration. RAG is called over bounded authenticated HTTP inside the existing ACT
   path; domain tools dispatch through MCP in R1. Persist typed retrieved citations with
   tool results and expose them to adaptation as delimited untrusted evidence. A new
   immutable prompt version explains grounding; old prompts/runs remain readable.
7. Grounded final results contain typed claims with cited evidence IDs and explicit gaps.
   Before completion, validate IDs, feature/corpus scope and exact quote/support metadata
   against successful persisted retrieval results; reject forged or unrelated references.
   Include a confidence category (`high`, `moderate`, `low`, `insufficient`) with a concise
   rationale; deterministic policy forces `insufficient` when context is absent/unavailable
   and caps other categories when evidence is partial. Categories describe evidence support,
   not numeric model probability. Source citations never enter the trusted mutation identifier ledger. Do not equate ID
   validation with entailment: the evaluation separately checks claim support. No-match or
   outage produces an honest ungrounded/insufficient-evidence state, not invented citations.
8. Reuse shared chat source cards and operations projections. Show source title/excerpt,
   location, source date versus ingestion time, project/fixture/official kind and version.
   Only safe HTTP(S) or approved same-origin links; never model HTML. Show retrieval state
   and MCP/RAG runtime health separately from provider health and ordinary feature CRUD.
9. Keep only shared frontend and student feature services in Compose. Remove AI-mode's
   service and generated mounts; preserve its existing named-volume data through an explicit
   migration/export command, never automatic deletion. Host-local AI-mode, MCP and RAG get
   managed start/status/log/stop commands and persisted PID/command ownership records. Never
   kill an unrelated process reusing a PID. A foreground mode remains available for diagnosis.
   Bind AI-mode for Docker-host access with service authorization and bounded requests;
   MCP/RAG remain authenticated loopback services behind AI-mode. Configure feature backends
   and the shared edge with `host.docker.internal`, including Linux host-gateway mapping.
   Host tools use validated published feature frontend/API origins on loopback; startup
   projects catalogue service origins from enabled deployment metadata, never model URLs.
   `stack up` manages both host and container lifecycles, preserving data on ordinary down.
   R0 mode keeps host AI-mode/direct HTTP; R1 enables local MCP/RAG; CI explicitly disables
   MCP/RAG and does not launch them. Cloud excludes advanced services and multi-agent stays
   absent. This leaves the same run and approval model for R2 roles.

## Logical commits and execution sequence

| Group | Implementation and owned surfaces | Acceptance |
|---|---|---|
| 1. Reviewed design | This plan, ADR, contract decisions | Independent review resolved before production edits |
| 2. Retrieval foundation | Neutral contracts, RAG package/index/embeddings/API, lifecycle tests | Idempotency, replacement/withdrawal, rollback, bounds, scope and retrieval tests |
| 3. MCP transport | Neutral tool runtime extraction, MCP server/client, compatibility facades/tests | Real protocol negotiation/list/call/resources, equivalent HTTP results, denied scope/approval/invalid arguments, bounded failure |
| 4. Grounded harness | AI-mode composition/config, core validation, typed result persistence, new prompts | Old runs readable; retrieved evidence survives all phases; forged citations and injection fail safely |
| 5. Feature 1 and UI | Owned corpus/manifests/eval cases, feature configuration, shared source cards/status | Coverage/diagnosis cite guidance plus current facts; empty/outage states; approval invariant; browser behavior |
| 6. Runtime and CI | Host lifecycle and networking, student Compose/images/dev commands, architecture/package validators, five-workflow disable flags | Clean locked build, both release modes, storage ownership/cloud exclusion, no shared AI Compose services, deterministic full gate |
| 7. Live evidence and handoff | Local integration/evaluation scripts, docs/diagrams/onboarding/evidence, fixes | Live Docker/browser/provider run, restart and outage checks, final independent review, push and PR |

After reviewed interfaces are fixed, delegate RAG and MCP as disjoint workstreams while the
parent implements harness integration and deployment/UI. Only the parent edits workspace
membership, dependency lock, Compose, canonical checks and generated artefacts. Agents do
not commit each other's work. Commit each coherent validated group; repeat tests when its
behavior changes, then run the aggregate gate before handoff.

## Test and evidence plan

- Contract tests: strict bounds, URI safety, source versus ingestion dates, version identity,
  scoped filters, JSON Schema/OpenAPI drift, old snapshot defaults and round trips.
- RAG tests: normalization/chunk position/hash, duplicate/change/delete, failed embed/atomic
  rollback, invalid vectors, restart persistence, missing corpus, unrelated query, scoped
  search, deterministic ranking/context limits, corrupt input, retention and concurrency.
- MCP tests: deterministic in-memory SDK/transport tests in CI; actual SDK exchange over
  local HTTP only in explicit local integration validation; discovery/invoke/resource; enabled-only
  catalogues; wrong token/feature, unknown tool, malformed input/output, timeout/connection
  loss, correlation and idempotency, no automatic mutation replay, approval preservation.
- Harness tests: retrieval → observe → adapt → persisted grounded answer; forged IDs,
  wrong scope, malicious passage instructions, no evidence, service outage, cancelled or
  resumed run, preserved mutation trust policy and legacy run behavior.
- UI tests: safe source rendering/link rejection, empty/unavailable grounding labels,
  source inspection by keyboard, narrow viewport and route changes without stale polling.
- Run `uv run python scripts/check.py`, required Feature 1 form browser suite and relevant
  normal-origin UI audits. Add new packages to existing type/coverage/architecture gates
  without weakening thresholds. Explicitly disable MCP/RAG runtime in all five student
  workflows and assert Compose contains neither service. No MCP/RAG service is launched in CI.
- Add `ai validate mcp` and `ai validate rag` commands that run the shared agent loop in
  their named validation modes and retain safe structured outputs, including separate
  insufficient-context and citation/confidence assertions. Deterministic local validation
  is distinct from the actual provider-backed Feature 1 demonstration.
- Live local: start full enabled student Docker stack plus non-containerised AI-mode/MCP/RAG;
  explicit corpus ingest and identical replay;
  real retrieval; Feature 1 assistant run through UI/backend/AI-mode/MCP and RAG; inspect
  citations/four phases; restart new services and verify persistence; stop MCP/RAG separately
  and show safe AI failure with ordinary data reads/CRUD still usable. Restore stack.
- Inspect existing Feature 1 accepted publications, immutable artifact download/schema/hash,
  consumer receipts, discovery and current migration/table counts. Use deterministic fixture
  acquisition for new smoke state; preserve existing source-scale data and human publication
  review. Record unavailable upstream evidence rather than manufacturing approval or facts.
- Version a small evaluation set before tuning: coverage, partial scope, failure recovery,
  ambiguous/absent evidence, stale/conflicting guidance and injection. Target expected-source
  recall@5 >= 0.9 for answerable guidance cases; zero accepted forged/out-of-scope citations;
  no forbidden claims on negative cases. Compare tool-only versus retrieved context on the
  same cases. Retain actual model/prompt/corpus identity, latency/token counts and failures.
  These are engineering targets, not claimed course rubric thresholds.

## Handoff and remaining external evidence

Update living READMEs/architecture, operational commands and a concise feature-onboarding
guide; retain an evidence index, architecture flows and Shared/F1 report-ready implementation,
feature/risk plan and showcase steps. Final independent subagent review covers the complete
diff; validate and repair its actionable findings, rerun affected checks, then push and open PR.

The course archive's detailed R1 brief was unpublished on 3 September; the user supplied
the marking rubric directly and authorized proceeding. Its non-containerised shared runtime,
disabled-CI, confidence and validation-mode requirements supersede the old delivery plan.
Durable tutor OpenAI/PostgreSQL approval,
the operational-table ten-record interpretation, unagreed F4 products, other owners' feature
acceptance, attendance and a new group video remain explicit external assessment items.
Do not fabricate these or claim full five-feature submission sign-off from this increment.

## Independent plan review resolution (6 September)

All eight findings were checked against the named source seams and accepted:

1. Host migration includes the Compose generator, development overlay, nginx, five backend
   URLs, workflow service lists, configurable host ports and catalogue origin projection.
   Existing volume history is detected and exported with SQLite consistency checks before
   first host startup; an existing host store is never overwritten.
2. Add an explicit backward-compatible grounding request/configuration on each R1 run and
   a typed completion validator, independent of model-selected output. Old runs default off.
3. Grounded claims distinguish `tool_fact` from `guidance`: facts reference successful
   owning tool call IDs, guidance references retrieved chunk IDs. Server projection supplies
   citations; the model cannot manufacture citation metadata. Confidence is capped at
   moderate for partial evidence, low for conflicting/stale evidence, insufficient without
   usable retrieval, and never derived solely from similarity.
4. Require retrieval in the active plan for grounded completion. Replans retrieve again;
   each retrieval response pins a complete corpus version. Historical outputs retain
   excerpts/version labels; resumed completion rechecks active corpus identity and reports
   superseded/withdrawn context instead of claiming current guidance.
5. MCP authentication binds feature/run/call identity and approval metadata outside model
   arguments. Signed short-lived invocation context uses a service secret, includes the
   exact argument hash and requested tool, and rejects conflict/expiry. Only the existing
   orchestrator policy can create approved invocation context. No mutation retries.
6. Project complete bounded citations separately before ordinary tool-content truncation;
   test maximum-size envelopes retain IDs, excerpts and support references intact.
7. Corpus fingerprint includes citation metadata, normalized text, model identity/artifact
   hashes, dimensions and preprocessing/chunk strategy. Normal startup uses prepared local
   model files; it neither downloads them nor silently falls back to fixture embeddings.
8. Separate local real-service validation modes from CI; canonical tests use in-process
   doubles and static disabled-runtime assertions. Capture both named modes plus combined
   Feature 1 live-provider/UI evidence locally.

## Implementation review resolution (7 September)

The interrupted implementation was preserved in `035b8ff`; latest `main` (Fieldbook UI,
`a102bff`) was merged by `d10d103`. Continuation commits retain that merged design.
Two final reviewers independently inspected the runtime and implementation. Their confirmed
findings were reproduced and fixed:

- Host AI-mode's Docker-reachable listener requires a dedicated service token on every route
  except liveness. Backend adapters and the loopback shared edge supply it; browser content
  never receives the credential. Direct unauthenticated access returns 401.
- Corpus-version verification consumes the remaining run budget and a cumulative bounded
  stream deadline. Slow metadata cannot hold the serial runner indefinitely.
- Reactivating a retained A→B→A corpus restores its original metadata/citations without
  reembedding or replacing its ingestion timestamp.
- The validation command now honours its advertised explicit environment-file option.

Live integration additionally found and fixed Feature 1's exact ownership allowlist rejecting
RAG-extended runs, catalogue output drift after the UI merge, and generic prompt bounding
truncating citation evidence. Grounded context receives a separate reserved message budget.
The semantic evaluation exposed unrelated high-similarity passages; actual answer validation
now permits explicit insufficient context even for ready retrieval, and the provider-backed
negative/adversarial set records both successful refusals and bounded repair attempts.

The [handoff and evidence](shared-feature-1-handoff.md) records final checks, actual local
provider/browser runs, remaining external submission evidence and the PR.
