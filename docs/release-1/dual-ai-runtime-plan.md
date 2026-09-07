# Reversible AI runtime placement

User-authorised follow-up: run AI-mode, MCP and RAG in Docker for development visibility,
while retaining the non-containerised Release 1 assessment mode. Docker placement is a
development convenience; it does not satisfy the supplied non-containerisation rubric.

## Implementation

1. Preserve base/CI Compose topology; add an optional AI overlay and a production image
   with authenticated entrypoints. Keep host loopback restrictions and permit only fixed
   internal service origins in Docker mode.
2. Add persisted `docker|host` placement to the launcher, defaulting fresh setups to Docker.
   Keep placement separate from `direct|mcp|rag|combined` capability modes. All lifecycle
   commands must respect selection; switching stops the previous owner before startup.
3. Reuse the existing exclusive AI history and RAG index/model directories through bounded
   bind mounts. Preserve credentials, immutable corpus identity and feature-owned tools.
   Generate Docker catalogue paths from enabled manifests and update proxy addresses only.
4. Document first setup, switching, RAG preparation and assessment commands. Add deterministic
   tests for topology, selection, ownership transitions, credentials and offline exclusions.
5. Run canonical checks, build/live-test Docker, switch to host, then back to Docker. Verify
   the same recorded history and corpus plus grounded chat. Resolve independent final review,
   commit focused groups and push the existing PR.

## Independent plan review

Validated review findings: retain the base host topology; prevent dual SQLite owners; make
every lifecycle command placement-aware; preserve authenticated AI entry and health checks;
use native Docker catalogue origins; keep MCP Host-header validation; avoid dependency cycles;
and update the image's missing shared-tool-runtime source. These are included above.

## Final review and live evidence

The independent code review identified two validated issues: an atomically replaced provider
secret could leave an existing container using its old mounted file, and custom RAG paths could
silently diverge between placements. Startup now recreates the AI secret consumers; unsupported
custom paths fail before stopping the host owner. Regression tests cover both conditions.

Live validation on 7 September 2026 exercised Docker → host → Docker using the existing model,
index and history. Docker chat `18e71ad0-fef6-4d1c-84df-0892433dc906` returned a cited PSI guidance
answer. Host chat `38c37745-470b-457e-989b-03074759a5db` returned a source-inventory answer with
recorded tool evidence. Both runs and the prior run `e3889f10-a094-4e85-bfe0-165a4c8ae18c` remained
readable through the shared history API after the round trip. The active corpus retained identity
`4ec85c9da899a9c086a76bed335aeaa1419793df2110bb2df8eed5a0d510f8c9`; no reingestion was performed.
Named live MCP and RAG validations passed in both placements. Docker offline startup stopped MCP
and RAG and left AI-mode running with advanced capabilities disabled. Normal startup restores the
three-service Docker runtime. These are deployment checks, not new semantic-quality evaluation.

Local logs and captured outputs remain under ignored `.propertyscope-runtime/dual-*` paths.

The final `uv run python scripts/check.py` passed: formatting, lint, architecture/generated
contracts, styles, strict typing, JavaScript compilation, 1,913 Python tests and 209 frontend
tests. All coverage thresholds passed; 38 expected skips require disposable PostgreSQL
configuration or Windows symlink privileges. Full local log:
`.propertyscope-runtime/dual-runtime-quality-gate.log`.
