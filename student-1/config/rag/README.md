# Property data guidance corpus

The documents in `documents/` are what the Property data assistant retrieves and cites. They explain
the datasets, the property page, searching, data updates, publishing and recovery in the same terms
the interface uses. They contain no current counts or property facts; the assistant gets those from
Property data's own tools at question time.

The text is project-written and dedicated to the public domain under
[CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/). That covers these documents only, not
the upstream datasets they describe.

## Ingest

With the local stack running and `RAG_SERVICE_TOKEN` set in the shell (never in the manifest):

```text
uv run rag-server ingest student-1/config/rag/corpus.json
```

Ingestion replaces the whole corpus. Unchanged content keeps its version; removed documents are
withdrawn. Starting the stack never ingests. Inspect the result at
`http://localhost:5100/operations/ai-mode/knowledge/`, where you can also test how a question ranks.

## Writing guidance

- Start the file with `# Title`, matching `title` in `corpus.json`. Use `##` headings; RAG chunks at
  headings and keeps each section's heading with its text. Keep each section under 1,200 characters
  (the shared corpus test reports longer ones).
- Use the names on screen ("Published data", "Use downloaded file"), not internal field names.
- Base each statement on implemented behaviour. The main sources are the Feature 1 README,
  [the consumer guide](../../DATA_PRODUCT_CONSUMER_GUIDE.md), ADR-035, ADR-038, ADR-041 and ADR-043.
  Measured figures must say when they were measured.
- Say what the data cannot show. Do not add advice, valuations or rules that are not implemented.
- Keep `document_id` values stable across revisions and update `source_date` when a document changes.

## Evaluate

`evaluation-v2.json` holds supported, unrelated, stale and injection cases. After changing documents,
run the evaluation in [retrieval-evaluation.md](../../../docs/release-1/retrieval-evaluation.md) and
commit the new baseline. Add cases for new topics before judging the result. The v1 files are kept
as the 7 September record.
