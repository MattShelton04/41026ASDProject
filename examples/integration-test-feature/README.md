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

## Run the working preview

With Docker Desktop running, start the fixture, AI-mode, and the pinned Ollama runtime:

```text
docker compose --file docker-compose.yml --file docker-compose.integration-test.yml --profile ollama-container up --detach --wait --wait-timeout 120 ollama
docker compose --file docker-compose.yml --file docker-compose.integration-test.yml --profile ollama-container run --rm ollama-init
docker compose --file docker-compose.yml --file docker-compose.integration-test.yml --profile release-0 --profile integration-test up --detach --build --wait --wait-timeout 120 ai-mode integration-test-feature-database integration-test-feature-backend integration-test-feature-frontend
```

The first run downloads the small Qwen model. Open <http://localhost:5190> to:

- search the ten deterministic records through frontend -> backend -> database;
- create an idempotent record through the same service boundary;
- inspect the live model registry; and
- submit and poll a real Plan -> Act -> Observe -> Adapt AI-mode run.

You can also inspect <http://localhost:5005/api/v1/model-profiles> and
<http://localhost:5005/health/ready>. Stop the preview without deleting its named data
volumes with:

```text
docker compose --file docker-compose.yml --file docker-compose.integration-test.yml down --remove-orphans
```

The UI's direct record controls are deterministic boundary checks. The AI objective uses
the real selected model, so its output is intentionally treated as probabilistic and its
full safe trace is shown in the page.

Validate its optional Compose topology with:

```text
docker compose --file docker-compose.yml --file docker-compose.integration-test.yml \
  --profile release-0 --profile ollama-container --profile integration-test config --quiet
```

This is a pattern and integration fixture, not a substitute for any student's
approved frontend/backend/database feature or its full CRUD implementation.
