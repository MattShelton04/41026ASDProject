# Feature 1 operator-guidance corpus

This complete ingestion batch supports explanations of published property coverage and diagnosis
of import failures. Ten short topics cover producer publication, partial PSI years, missing evidence,
provenance, recovery, import diagnosis, accepted discovery, crime coverage, consumer boundaries and
guidance freshness. They are project-authored explanations derived from the living Feature 1 README,
consumer guide and cited accepted ADRs, not copies of official publisher material. No operational
counts, current property facts, raw warehouse data, private notes or new Feature 4 product are included.

The text in `documents/` is dedicated to the public domain under
[CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/). This dedication applies only to these
new authored guidance texts, not to upstream datasets, model weights, other repository content or
third-party documents. `corpus.json` records that scope with each source's date, stable document ID,
safe GitHub display URL and `project_guidance` evidence kind. The source date is the guidance review
date, not a publisher update date. GitHub links use the implementation branch; citation versions and
exact excerpts remain self-contained if the branch later changes.

## Explicit ingestion

With the local Release 1 host stack running, use its RAG token in the shell environment (never in
this manifest or a prompt) and run from the repository root:

```text
uv run rag-server ingest student-1/config/rag/corpus.json
```

The manifest loader accepts only explicit Markdown/text files beneath this directory and sends a
bounded complete replacement. It does not fetch source URLs. Identical replay returns the same
version and original ingestion time. Edit source metadata and text together when guidance changes;
reingest the complete manifest. Omitted documents are withdrawn from the active version. Ingestion
does not happen merely by starting the stack. Model preparation is a separate explicit command.

## Review and extension

1. Start from an implemented owner-approved behavior and its living document or accepted ADR.
   Resolve conflicting historical text before authoring guidance. ADR-041 supersedes the old
   consumer-acceptance publication gate; a consumer receipt and producer receipt are different.
2. Write a focused bounded topic with a source basis and limitations. Never add unsupported facts,
   speculative product rules or private material. These initial topics each fit one 1,200-character
   chunk so boundaries do not split a policy assertion from its qualification.
3. Add a stable entry to the complete manifest; keep IDs stable across revisions. Register any new
   feature/corpus pair in the host RAG allowlist and AI-mode feature retrieval configuration before
   ingestion. Each feature owner supplies its own content and tests; feature backends use AI-mode
   over HTTP and never open the index.
4. Add supported and negative cases before evaluating. Version substantive question/expectation
   changes. Include expected document IDs and forbidden claims; do not change relevance thresholds
   simply to eliminate inconvenient cases. Run deterministic corpus tests and the semantic command
   in [the evaluation record](../../../docs/release-1/retrieval-evaluation.md).

`evaluation-v1.json` is a small development set frozen before the first semantic execution. Its
negative cases describe required answer behavior, not a promise that the retriever returns no
chunks. Retrieval relevance cannot establish a claim's truth, freshness or authorization. Current
facts need owning tools and generated answers need separate grounding and entailment review.
