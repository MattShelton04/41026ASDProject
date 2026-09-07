# Local retrieval service

This host-only Flask service owns a bounded SQLite vector/metadata index. Feature backends reach it
through authenticated AI-mode retrieval; no feature database is opened and no document URL is fetched.
Only registered public project-guidance corpora are admitted. Private notes, case documents and raw
warehouse records require a future owner-scoped contract and are rejected today.

## Prepare and run

From the repository root, first sync the locked workspace. Prepare semantic assets explicitly:

```text
uv sync --locked --all-packages --all-groups
uv run rag-server prepare-model
```

Preparation downloads the FastEmbed `BAAI/bge-small-en-v1.5` CPU model and hashes ONNX/tokenizer assets.
Normal startup checks the recorded hashes, uses local-files-only loading and never silently downloads
or falls back to fixtures. Missing or changed assets produce readiness 503 until prepared and restarted.
FastEmbed is pinned to 0.7.4 in this package and the workspace lock. Its local API is documented by
[Qdrant](https://qdrant.tech/documentation/edge/edge-fastembed-embeddings/).

The integrated stack owns the normal host lifecycle. For foreground diagnosis, set
`RAG_SERVICE_TOKEN` to the same generated local secret used by AI-mode, then run:

```text
uv run rag-server serve
uv run rag-server ingest student-1/config/rag/corpus.json
```

`serve` binds loopback port 5012 without a debug reloader. `--port` selects another loopback port for
both commands. The production-like host runner uses its managed WSGI server. The CLI ingestion reads
only the explicitly supplied manifest and `.md`/`.txt` paths beneath its directory. A manifest may
alternatively contain inline `text`; its HTTP payload is the normalized `CorpusIngestRequest`.

| Setting | Default / meaning |
|---|---|
| `RAG_SERVICE_TOKEN` | Required, minimum 16 characters; never place in corpus or model prompts |
| `RAG_DATABASE_PATH` | `.propertyscope-runtime/host/rag/index.sqlite3`; exclusive service owner |
| `RAG_MODEL_CACHE_PATH` | `.propertyscope-runtime/host/rag/models`; prepared local assets |
| `RAG_EMBEDDING_MODE` | `semantic`; explicit `fixture` enables deterministic lexical hashing |
| `RAG_ALLOWED_CORPORA` | `student-1-propertyscope-data-platform:operator-guidance`; comma-separated exact pairs |

Fixture mode validates mechanics and must never be reported as semantic quality. Changing embedding
identity requires complete reingestion; an old-model index reports unavailable until refreshed.

## HTTP contracts

Every route except `/health/live` requires `Authorization: Bearer <RAG_SERVICE_TOKEN>`. Readiness at
`/health/ready` distinguishes prepared semantic/fixture embeddings from unavailable assets. Requests
have a 2 MiB ceiling and malformed fields return structured problem JSON without echoing content.

| Route | Request / response |
|---|---|
| `POST /api/v1/corpora/ingest` | `CorpusIngestRequest` → `CorpusVersion`; complete replacement |
| `POST /api/v1/retrieve` | `RetrievalRequest` → `RetrievalResponse` |
| `GET /api/v1/corpora/{feature}/{corpus}` | Active `CorpusVersion`; 404 if registered but never ingested |

The neutral contracts are in `shared_contracts.retrieval`. Retrieval distinguishes `ready`, `no_match`,
`empty`, and `unavailable`. Each returned citation includes the complete excerpt, excerpt hash, normalized
character position, safe display URL, source date, ingestion time, evidence kind and immutable corpus
version. Scores are cosine relevance, not confidence probabilities. AI-mode separately validates final
claims and evidence confidence. Recheck the current-version route before claiming resumed context is
current; historical citations retain their own self-contained excerpt and version.

Ingestion normalizes Unicode/newlines, sorts documents and fingerprints the complete text and metadata,
model artifact identity/dimensions, and chunk strategy. Identical ingestion returns the original version
and timestamp. A changed batch creates a version; omitted documents disappear from active retrieval.
An empty batch explicitly withdraws everything. Embedding/transaction failure retains the previous
complete active version. Reingesting an earlier complete batch reactivates its content identity.

## Bounds and limitations

- 20 registered corpora maximum; 200 documents and 500,000 total text characters per batch.
- 60,000 characters per document; 1,200-character chunks with 120-character overlap; 1,000 chunks maximum.
- Embedding batches contain at most 16 chunks; vectors must have finite, nonzero, matching dimensions.
- Three retained versions per corpus by default (hard maximum five); SQLite main-file ceiling 512 MiB.
- Retrieval scans only one active scoped corpus. Top-k defaults to 5 (maximum 10); excerpt budget
  defaults to 5,000 characters (maximum 12,000). Complete excerpts that cannot fit are omitted.
- SQLite exclusive locking prevents a second service owner. In-process requests serialize index
  mutations and searches. This bounded local teaching deployment is not a multi-replica search service.
- Only project-authored guidance and labelled fixture evidence are currently ingestible; an official
  evidence adapter requires separate source/permission review. HTTP(S) citations are references only.
- Fixed character chunking can split prose and dense-vector relevance does not prove entailment.
  Evaluation and server-side grounded-claim validation remain necessary.

Run deterministic contracts/index/model-boundary/Flask tests without a server, downloaded model, or
network (the FastEmbed boundary is replaced for preparation tests):

```text
uv run pytest ai-services/rag-server/tests shared/contracts/tests/test_retrieval.py --no-cov
```

Live semantic retrieval is an explicit local evaluation, documented in
[`docs/release-1/retrieval-evaluation.md`](../../docs/release-1/retrieval-evaluation.md).
