# Feature 3 RAG guidance

This corpus contains reviewed project guidance for the Suburb, Crime and Liveability Analytics
assistant. It explains the feature's evidence, methodology and limits. Current locality records,
crime observations, saved comparisons and private user data are deliberately excluded; those facts
remain behind Feature 3's read-only MCP tools.

The corpus is registered as `suburb-analytics-guidance` in `student-3/feature.yaml`. The checked-in
manifest contains only reviewed guidance. To add assistant-only locality evidence, build a complete
runtime manifest from Feature 1's accepted `abs-geography-2021` and `nsw-amenities` releases:

```text
uv run python student-3/config/rag/build_locality_corpus.py
uv run rag-server ingest .propertyscope-runtime/host/rag/suburb-analytics-generated.json
```

The source adapter verifies the accepted artifact record counts and SHA-256 digests, uses geometry
only while associating the configured supported localities with LGA and facility records, and emits
no coordinates or polygons. Generated runtime data is intentionally Git-ignored. Edit
`supported-localities.json` to change the bounded locality set; exact ABS locality names are
required. Each generated document identifies its accepted releases and retains official evidence
labelling. Ingestion is explicit and a complete replacement of the previous corpus version.

Rebuild and reingest after either accepted release changes. The representative-point LGA match is
not an official suburb-to-LGA crosswalk, and facility records do not establish service quality,
accessibility, route frequency or travel time.
