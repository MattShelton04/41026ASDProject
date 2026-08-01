# Shared contracts

Strict, domain-neutral Pydantic contracts shared across HTTP/service boundaries.
Feature entities and business rules must not be added here.

The package currently defines correlation headers, health and Problem Details payloads,
agent runs/steps/limits, plans and adaptations, typed tool definitions/calls/results,
observations, and human review records. All contracts reject undocumented fields and
validate assignment after construction.

JSON Schema snapshots and the AI-mode OpenAPI 3.1 document are generated from these
models:

```text
uv run python scripts/generate_contracts.py
uv run python scripts/generate_contracts.py --check
```

The canonical repository check runs drift verification. Change a model and its generated
artefacts together; use a new API version for breaking changes.
