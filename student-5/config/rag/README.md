# Buyer workspace public guidance corpus

Owner: Student 5 (Derek Song). Content edition: v2, 2026-10-01.
Feature: `student-5-buyer-journey`; corpus: `operator-guidance`.

Five concise team-authored documents explain buyer cases, shortlists and stages,
notes/tasks, evidence limits and responsible AI. Stable document IDs, source dates,
source links, evidence kinds and licence metadata are declared in `corpus.json`.
The shared ingestion service computes content hashes and the actual corpus version;
the edition label is not a substitute for that version.

Only public project guidance belongs here. Do not add case names, identities,
budgets, notes, tasks, private records or copied publisher content. Current buyer
facts remain owner-scoped read-only tool results, never public retrieval documents.
Source links resolve after this contribution is merged; commit IDs are pending.

## Explicit ingestion

Use the existing host-only combined runtime; no AI services belong in Compose.
The feature manifest supplies the allowed feature/corpus pair to the host launcher.
If an already running host predates the declaration, follow the shared host refresh
instructions rather than starting a second conflicting runtime.

With the prepared embedding model, combined host services and managed
`RAG_SERVICE_TOKEN` available in the shell, explicitly run from the repository root:

```text
uv run rag-server ingest student-5/config/rag/corpus.json
uv run scripts/dev.py ai validate mcp --feature student-5-buyer-journey
uv run scripts/dev.py ai validate rag --feature student-5-buyer-journey
```

Never print the token or put it in frontend code. Ingestion reads the local files;
it does not fetch source links. Reingestion replaces the whole corpus, withdrawing
omitted documents. Application startup does not ingest anything.

After ingestion, inspect the recorded corpus version and passages in
`http://localhost:5100/operations/ai-mode/knowledge/`. Try supported questions such
as "How do I manage a shortlist?" and "What happens to notes when a property is
removed?", then an unrelated question such as "How do I bake sourdough?". Record
actual citations, confidence and no-match/insufficient-context outcomes; do not
infer successful retrieval from a healthy service alone. Shared relevance thresholds
are unchanged and need corpus-specific live evaluation before assessment.
