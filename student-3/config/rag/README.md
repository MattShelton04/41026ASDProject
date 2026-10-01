# Feature 3 RAG guidance

This corpus contains reviewed project guidance for the Suburb, Crime and Liveability Analytics
assistant. It explains the feature's evidence, methodology and limits. Current locality records,
crime observations, saved comparisons and private user data are deliberately excluded; those facts
remain behind Feature 3's read-only MCP tools.

The corpus is registered as `suburb-analytics-guidance` in `student-3/feature.yaml`. Ingest it only
into the managed host RAG service with `uv run rag-server ingest student-3/config/rag/corpus.json`.
Ingestion is explicit and a complete replacement of the previous corpus version.
