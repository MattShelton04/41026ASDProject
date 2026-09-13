# Integration verification — 13 September 2026

## Shared gateway regression

PR #111's Student 5 CI failed while reading a created AI summary through the shared edge.
The Linux service log reported `host.docker.internal could not be resolved` and HTTP 502.
The runtime nginx DNS resolver bypasses `/etc/hosts`, where Compose installs `host-gateway`.

The shared image now resolves explicit host mappings before template substitution. Unmapped
service names retain runtime Docker DNS. No feature implementation or database boundary changed.

An isolated local Linux-container check reproduced the 502 with the hook disabled, then verified:

- All four AI proxy routes with the hook enabled, including the rewritten assistant API.
- Preserved query strings, service authentication and request correlation.
- Recovery after changing the upstream container IP without restarting the gateway.

The temporary test containers and network were removed afterwards. The local shared edge was
rebuilt through `uv run scripts/dev.py stack rebuild shared-frontend`.

## All five live feature workflows

One bounded AI request per feature completed with the configured local OpenAI provider.
Every run returned a nonempty summary and findings, four recorded activity phases, a successful
feature-specific poll, and a readable shared activity record. Feature 1–4 event endpoints also
returned successfully. The saved results were rechecked after rebuilding the gateway.

| Feature | Workflow checked | Recorded run |
|---|---|---|
| Property data | Accepted property record and retrieved guidance, prompt v9 | `d78d412b-05c2-4501-a28b-a8642607abdb` |
| Sales research | Case inspection and deterministic sales summary, prompt v7 | `2f0ba855-e788-4d19-8fa4-ffb134293028` |
| Suburb analytics | Suburb snapshot and methodology, prompt v7 | `02a5a425-601f-46c6-86f0-05485911ac86` |
| Due diligence | Review inspection and evidence questions, prompt v7 | `78d81b31-8c9a-4757-8f8e-d33b0f7effda` |
| Buyer workspace | Case, evidence, notes and tasks, prompt v7 | `acc091cb-0e3c-4cb4-bc43-87fa18ef9766` |

All five shared feature shells and health endpoints responded. Case lists and evidence endpoints
for Features 2, 4 and 5 responded with the existing seeded data. These requests did not alter cases.

This is a smoke test, not exhaustive feature acceptance or a model-quality benchmark. Features
2–5 retain their v7 prompts; the Feature 1 RAG changes do not migrate those workflows. The Buyer
Workspace evidence collector still explicitly returns Suburb analytics as unavailable. Its tested
case also reported Property data as needing verification and Sales/Due diligence as partial.
Those existing fixture/integration limitations must not be described as complete evidence coverage.

## Deterministic verification and review

- `uv run python scripts/check.py`: passed; 2,016 Python tests and 221 JavaScript tests passed.
  The 47 skips include six POSIX-shell tests unavailable on Windows, two Windows symlink tests,
  and 39 opt-in PostgreSQL tests. The shell regression cases run in Linux CI.
- `uv run python -m scripts.ui_feature_smoke --output Temp/chat-ci-feature-smoke`: all 40
  cases passed across five features, four viewport widths, and empty/unavailable API states.
  This browser suite uses deterministic API doubles, separately from the live checks above.
- `git diff --check`: passed.
- A final subagent reviewed the routing hook, Docker wiring, tests and documentation and found
  no actionable issues. Its local shell checks were skipped on Windows; the parent performed
  the isolated Docker reproduction and recovery checks.
