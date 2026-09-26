# ADR-043: Run local grounded research through the existing agent boundary

- Status: Accepted for the Shared/Feature 1 Release 1 increment
- Date: 7 September 2026
- Owner: Shared platform and Feature 1 (Matthew Shelton)
- Extends: ADR-012 release gates, ADR-017 model boundary, ADR-034 feature enablement
- Supersedes: earlier local Compose designs placing AI-mode, MCP or RAG in containers
- Review: [implementation plan and independent review resolution](../../release-1/shared-feature-1-implementation-plan.md)

## Context

The Release 1 rubric supplied on 6 September requires one shared non-containerised local MCP
server, RAG server and agentic loop. AI-mode also remains outside Compose. Student frontend,
backend/API and database services must retain their integrated containerised behavior. MCP/RAG
must remain disabled in CI/CD, while local validation captures both named agent-loop modes,
citations, confidence and insufficient-context behavior. The initial archived delivery plan's
Compose topology conflicts with that more specific requirement.

Feature 1 needs bounded explanations of published coverage and import failures. It already owns
current release/run facts and publication approval. Reimplementing those facts in Shared or
letting retrieved instructions authorize tools would weaken the existing boundaries.

## Decision

Keep the production Plan / Act / Observe / Adapt runner and AI-mode's exclusive run store.
The local launcher manages AI-mode, MCP and RAG as independently owned host processes; the loop
is an AI-mode library/worker, not a fourth network server. Compose defines only the shared edge
and enabled student services. Docker backends use `host.docker.internal`; MCP/RAG bind loopback.
Provider credentials stay with host AI-mode. The Docker-reachable managed AI-mode listener requires
`X-PropertyScope-AI-Token` on every route except `/health/live`; only backend clients and the
shared proxy receive it. The launcher generates or validates `AI_MODE_SERVICE_TOKEN` and injects
it consistently into container and host configuration, never browser assets. This is service
authentication within the trusted local demonstration profile;
production end-user authentication and cloud deployment remain separate Release 2 work.

Extract neutral catalogue parsing, bounded HTTP dispatch and signed invocation metadata into
`shared-tool-runtime`. MCP uses the official SDK's stateless Streamable HTTP transport, exposes
existing tool schemas and metadata, and calls the same owning backend endpoints. Bearer tokens
and signed metadata bind exact arguments, feature/run/call, deadline, approval and idempotency.
MCP revalidates those constraints. Neither transport retries mutations automatically or invents
feature business rules. The backend retains durable idempotency and approval enforcement.

RAG owns a separate bounded SQLite metadata/vector index and prepared CPU embedding assets.
The initial feature-owned corpus is ten CC0 project-guidance documents, not live property facts
or official publisher methodology. Explicit ingestion normalizes a complete registered batch,
chunks, hashes and embeds locally, then atomically activates a version. Identical replay retains
identity/time; omitted documents are withdrawn; refresh failure retains the last active corpus.
Normal startup neither downloads models nor ingests documents. Public scope is fixed at startup;
private notes and unapproved official-source adapters remain excluded.

Grounded runs persist fixed feature/corpus scope and retrieve in each active plan. Guidance claims
reference actual retrieved IDs; current facts reference successful owning tool-call IDs. Server
validation checks scope, version and support references, projects citation metadata from recorded
results, and rechecks active corpus identity before completion. Source text is untrusted evidence,
never an instruction or mutation identifier. Confidence is an evidence-support category that the
server derives from the recorded evidence (amended 26 September, below). Absent or unusable
context forces insufficient.

Shared chat renders literal text, source excerpts, dates/kinds/versions and safe links, preserving
legacy answers and native keyboard disclosures. Service configuration/readiness is observed
separately from feature availability, provider health and corpus coverage. Every workflow disables
MCP/RAG; in-process doubles exercise policy/transport mechanics. Named local MCP/RAG validations
use the actual runner and real services with deterministic model decisions. Provider-backed and
browser evidence is a separate assessment artifact.

## Consequences and verification

The host launcher must preserve earlier AI history, verify process identity before signalling and
document port/token configuration. Token rotation requires `stack up` to recreate container
configuration as well as host processes. Its consistency-checked migration retains the old Docker
volume and never overwrites an existing host store. Ordinary shutdown preserves all durable data.
MCP and RAG remain independently stoppable without removing ordinary feature CRUD.

The approach keeps Release 2 roles behind the existing run, tool, review and persistence contracts;
it does not implement multi-agent coordination or cloud hosting early. Other feature owners can
register their own approved tools/corpora using the [adoption recipe](../../release-1/feature-adoption.md).
Their individual integration and report evidence remain their responsibility.

Reference validation covers contract bounds, scope/approval rejection, replay, withdrawal/rollback,
prepared-model identity, grounded support checks and safe browser inspection. Dense source recall
cannot prove entailment or current facts; the [evaluation record](../../release-1/retrieval-evaluation.md)
retains the observed negative results. The [handoff](../../release-1/shared-feature-1-handoff.md)
tracks exact live evidence, limitations and external assessment items.

## Amendment: evidence-derived confidence and a relevance floor (26 September 2026)

Measured history showed the original rule mislabelled supported answers. Of 45 grounded Feature 1
answers, 23 were `low` only because the model listed any evidence gap, including answers citing
two to four passages scored 0.70-0.84; `high` was unreachable. Separately, dense retrieval with a
0.35 floor returned `ready` for unrelated questions (recipes, weather, sport scored 0.42-0.50), so
insufficient context depended on the model refusing.

- Grounded retrieval applies `GROUNDING_MIN_SCORE` (0.55, in `shared_contracts.grounding`).
  A question with no passage above it retrieves `no_match` and is answered as insufficient.
- `agent_core.grounding.assess_confidence` derives the category. The model's `low` (stale or
  conflicting evidence) is kept. Otherwise: reported gaps, a cited passage below 0.65 or a single
  supporting source give `moderate`; `high` needs no gaps, strongly matching citations and at
  least two independent supports (distinct documents or tool calls). The reason text names that
  basis. Confidence still describes evidence support, not verified entailment or probability.
- Both thresholds are calibrated for `BAAI/bge-small-en-v1.5` and must be re-measured with
  `scripts/evaluate_release1_retrieval.py` if the embedding model changes.

