# Agentic-loop review outputs

This folder holds the Release 2 review reports and validation logs written by the shared
agentic loop. Generate them from the real evidence after the feature freeze; do not edit them by
hand.

| File | Written by |
|---|---|
| `multi-agent-review.md`, `multi-agent-validation-log.jsonl` | `uv run scripts/dev.py ai review multi-agent` |
| `testing-review.md`, `testing-validation-log.jsonl` | `uv run scripts/dev.py ai review testing` |
| `cloud-review.md`, `cloud-validation-log.jsonl` | `uv run scripts/dev.py ai review cloud` and `ai review decide` |

The human release decision itself is written to `../cloud/release-decision.md`.

- Each `*-review.md` is overwritten by the latest review of that mode. It records the verdict, the
  AI-mode run ID (shown in Activity history), the prompt set and model, every input file with its
  SHA-256, the checklist, findings, risks and recommendations.
- Each `*-validation-log.jsonl` is append-only: one JSON object per review attempt, completed
  review or human decision. Keep earlier lines; they are the audit trail.
- A report whose engine is `deterministic` or `deterministic-fallback` was produced without a
  model. Use the AI-mode run for the report evidence unless the provider was unavailable, and say
  so if it was.

See [review-modes.md](../../review-modes.md) for the evidence each mode reads, the checks, the
output schema and the log format.
