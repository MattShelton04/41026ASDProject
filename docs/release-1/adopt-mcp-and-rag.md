# Adopt shared MCP and RAG in your feature

The shortest path from a working Release 0 feature to the Release 1 rubric's MCP and RAG
requirements. [feature-adoption.md](feature-adoption.md) is the full contract and explains *why*
each boundary exists; this page is the ordered checklist.

**Copy Feature 3's UI wiring, not Feature 1's.** Feature 3 is the minimal integration: one
import, one stylesheet, one Dockerfile line. Feature 1 is the full-featured reference with a
shared canvas, operations routes and its own evidence history — far more than the rubric asks for.

One caveat: copy Feature 3's *frontend* wiring, not its backend run proxy. Feature 3 forwards
`GET /api/v1/agent-runs/<id>` for any run id (`student-3/.../app.py:385-389`), with no feature-key
or allowlist ownership check. Features 1, 2 and 4 all check ownership before returning a run, and
step 1 above assumes you do too. Do not propagate that gap.

---

## Step 1 — Approve the grounded allowlist *before* you register a corpus

Do this first. Once your feature has a registered corpus, `ai-mode` rewrites every run it
creates (`ai-services/ai-mode/src/ai_mode/api.py:71-78`). It:

1. injects `grounding: {corpus_id: ...}`;
2. **overwrites `prompt_set` to `default.v9`** — your `default.v7` is silently replaced;
3. appends `context.retrieve.v1` to `tool_allowlist`.

If your backend validates an exact allowlist when reading a run back, (3) makes it reject its own
runs the moment step 3 of this guide lands.

```python
from shared_contracts.grounding import grounded_allowlist_variants

TOOL_ALLOWLIST = ("market.cases.inspect.v1", "market.sales.summary.v1")
APPROVED_TOOL_ALLOWLISTS = grounded_allowlist_variants(TOOL_ALLOWLIST)
```

Now replace the comparison. **Coerce the wire value first** — AI-mode returns `tool_allowlist` as
a JSON *list*, and `list in tuple-of-tuples` is always `False`, so the obvious transcription
silently 404s every turn:

```python
# before
owned = ... and run.get("tool_allowlist") == list(TOOL_ALLOWLIST)

# after — note tuple(...)
allowlist = run.get("tool_allowlist")
owned = ... and isinstance(allowlist, list) and tuple(allowlist) in APPROVED_TOOL_ALLOWLISTS
```

This widens the approved set by one known tool; it does not relax ownership to an unrestricted
read. Feature 1's version is `student-1/.../assistant_routes.py:536-541`.

Lock it in by handing the shared assertion **your own predicate**, so the test exercises the real
comparison rather than the constant:

```python
from shared_testkit import assert_grounded_allowlist_accepted


def test_grounded_runs_stay_readable() -> None:
    def accepts(wire_allowlist: list[str]) -> bool:
        return tuple(wire_allowlist) in APPROVED_TOOL_ALLOWLISTS

    assert_grounded_allowlist_accepted(accepts, TOOL_ALLOWLIST)
```

`shared_testkit` is a dev dependency — add it to your slice's `[dependency-groups].dev` in
`student-N/pyproject.toml`.

> Features 2 and 4 both compare with `run.get("tool_allowlist") == list(TOOL_ALLOWLIST)` today
> (`student-2/.../api.py:285`, `student-4/.../api.py:265`). Feature 5 creates runs but does not
> re-validate the allowlist on read, so it is unaffected.

## Step 2 — Write your guidance corpus

Copy [`templates/rag-corpus/`](templates/rag-corpus/) into `student-N/config/rag/` and replace
every `REPLACE` marker. Aim for eight to ten short topics; Feature 1's each fit one 1,200-character
chunk so a policy assertion is never split from its qualification.

Write *project and operator guidance*: what your feature does, where its records come from, what
its evidence cannot establish. At least one topic must state your limits — the rubric marks
insufficient-context handling as explicitly as successful retrieval, and you cannot demonstrate a
defensible refusal without documented gaps.

Do not author official methodology, valuations, legal advice or inspection findings. Current
database facts belong in your MCP tools, not the corpus.

Validate before ingesting:

```python
from pathlib import Path
from shared_testkit import assert_corpus_manifest


def test_corpus_manifest_is_ingestible() -> None:
    assert_corpus_manifest(
        Path("student-N/config/rag/corpus.json"),
        feature_key="student-N-your-feature",
        corpus_id="operator-guidance",
    )
```

## Step 3 — Register the corpus in your own manifest

Add two lines to `student-N/feature.yaml` under `onboarding.ai`:

```yaml
  ai:
    tool_catalog: student-N/tool-catalog.yaml
    runtime_path: /etc/ai-mode/your-feature-tools.yaml
    rag_corpus: student-N/config/rag/corpus.json
    rag_corpus_id: operator-guidance
```

Then regenerate the projection and ingest:

```text
uv run python scripts/generate_deployment.py
uv run rag-server ingest student-N/config/rag/corpus.json
```

That is the whole registration. `RAG_ALLOWED_CORPORA` and `AI_MODE_RAG_CORPORA` are derived from
these declarations by the host launcher, so **you never edit a shared file and never conflict with
another owner**. `scripts/validate_architecture.py` fails if your manifest's own `feature_key` or
`corpus_id` disagrees with what you declared, or if the file is missing.

Ingestion needs `RAG_SERVICE_TOKEN` in your shell and the host stack running in combined mode. It
does not fetch document URLs, and reingestion is a complete replacement — omitted documents are
withdrawn.

## Step 4 — Adopt the shared assistant UI

Three edits, copied from Feature 3.

`student-N/Dockerfile`, beside the existing shared asset copies:

```dockerfile
COPY shared/frontend/ai-chat /usr/share/nginx/html/ai-chat
```

`student-N/frontend/index.html`, with the other stylesheets:

```html
<link rel="stylesheet" href="./ai-chat/styles.css">
```

> **Feature 5:** these three edits assume your backend already exposes `/assistant/turns` with
> read/events/cancel subroutes, as Features 1-4 do. Feature 5 has no such routes — it has
> `/buyer-cases/<id>/case-summary-runs` (`student-5/.../api.py:1258`). Add the assistant routes
> first, or the frontend has nothing to call.

`student-N/frontend/app.js`:

```javascript
import { createFeatureAssistant } from "./ai-chat/index.js";

createFeatureAssistant({
  root: document.querySelector("#assistant-root"),
  apiRoot: `${API}/assistant`,
  featureKey: "student-N-your-feature",
  featureLabel: "Your feature",
  returnTo: "/features/your-feature/#assistant",
  scopes: [{ id: "feature", label: "Your feature", description: "What this scope covers." }],
});
```

The shared renderer handles source citations, confidence categories, insufficient-context and
unavailable-service states, and safe-link rejection — all of which criterion 4 marks. Do not
hand-roll these: Features 2 and 4 currently render the answer text only and would score against
that criterion with an otherwise working integration.

See `student-3/frontend/app.js` for the full option set, including `contextOptions` for grounding
a question in a selected record.

## Step 5 — Validate and capture evidence

```text
uv run python scripts/check.py
uv run python -m scripts.dev ai validate mcp --feature student-N-your-feature
uv run python -m scripts.dev ai validate rag --feature student-N-your-feature
```

`--corpus` is resolved from your manifest automatically. For MCP, the loop calls an argument-free
read-only tool you own; pass `--tool` if you need a specific one. If you get *"every … tool
requires arguments"*, register a no-argument capabilities tool as Feature 1 does — it is useful in
its own right.

Then capture, through your own frontend, what the rubric asks for:

- one successful MCP interaction returning a structured tool result;
- one grounded RAG answer showing citations and a confidence category;
- one insufficient-context response where your corpus genuinely cannot help;
- your `student-N.yml` workflow run link, with MCP and RAG disabled in CI.

`assert_grounded_answer(answer, expect_citations=...)` from `shared_testkit` pins the answer shape
for both the supported and insufficient cases.
