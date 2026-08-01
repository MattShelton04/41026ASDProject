# Integration test feature

This package is executable integration-test infrastructure for the shared Release 0 platform. It
is deliberately not a project-domain feature and is not owned by any `student-N`
slice. It demonstrates the required structural boundaries:

```text
AI-mode HTTP tool adapter -> test backend -> test database service -> SQLite
```

The database service alone opens SQLite. The backend owns the tool/API boundary and
calls the database over HTTP. The example supplies ten deterministic records, a
read-only search tool, an idempotent create tool, and operation-status lookup. Its
component tests use real loopback HTTP with the scripted model; Ollama and Docker are
not required.

Validate its optional Compose topology with:

```text
docker compose --file docker-compose.yml --file docker-compose.integration-test.yml \
  --profile release-0 --profile integration-test config --quiet
```

This is a pattern and integration fixture, not a substitute for any student's
approved frontend/backend/database feature or its full CRUD implementation.
