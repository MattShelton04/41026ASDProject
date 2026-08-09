# Integration test feature

This package is executable integration-test infrastructure for the shared Release 0 platform. It
is deliberately not a project-domain feature and is not owned by any `student-N`
slice. It demonstrates the required structural boundaries:

```text
AI-mode HTTP tool adapter -> test backend -> test database service -> SQLite
```

The database service alone opens SQLite. The backend owns the tool/API boundary and
calls the database over HTTP. The example supplies ten deterministic records with
priority metadata and dependency relationships, three composable read tools
(search, inspect, and dependency evidence), an idempotent create tool, and
operation-status lookup. Its longer-horizon component test executes a three-action
plan over real loopback HTTP with the scripted model; Ollama and Docker are not
required.

The fixture also demonstrates two boundary conventions intended for real features:
checked-in tool catalogues are composed by the canonical quality gate, and HTTP errors
use the shared Problem Details contract across backend/database hops. Feature owners
should encode expected negative evidence such as an empty search as a successful typed
tool response; non-retryable HTTP/tool errors are reserved for requests that must fail
closed.

## Run the working preview

With Docker Desktop running, start the fixture, AI-mode, and the pinned Ollama runtime:

```text
uv run scripts/dev.py up
```

This development path bind-mounts the frontend and Python source, reloads Gunicorn after
Python edits, and preserves all named volumes on `uv run scripts/dev.py down`. Run
`uv run scripts/dev.py rebuild` only when dependencies, the lockfile, or Dockerfiles change.

The equivalent production-like Compose sequence without development mounts is:

```text
docker compose --file docker-compose.yml --file docker-compose.integration-test.yml --profile ollama-container up --detach --wait --wait-timeout 120 ollama
docker compose --file docker-compose.yml --file docker-compose.integration-test.yml --profile ollama-container run --rm ollama-init
docker compose --file docker-compose.yml --file docker-compose.integration-test.yml --profile release-0 --profile integration-test up --detach --build --wait --wait-timeout 120 ai-mode integration-test-feature-database integration-test-feature-backend integration-test-feature-frontend
```

The first run downloads the standard Release 0 Qwen model. Open <http://localhost:5190> to:

- search the ten deterministic records through frontend -> backend -> database;
- inspect record detail and its dependency graph without invoking a model;
- create an idempotent record through the same service boundary;
- inspect the live model registry; and
- submit and poll a real multi-action Plan -> Act -> Observe -> Adapt AI-mode run.

The console presents the run as a conversation-like transcript without claiming that
one run is a durable multi-turn conversation. It visualises every persisted phase,
tool call/result, model invocation summary, safe progress event, run/request ID, and
W3C trace context. The complete safe run-detail JSON remains available in an expandable
debug panel.

The longer-horizon preset uses `default.v3` and a six-minute client/run window. Measured
CPU timings vary materially with prompt size: one warm three-tool run completed in about
153 seconds, while a one-tool verification on 9 August 2026 took about 171 seconds
(100 seconds planning and 51 seconds adapting). A small structured-output provider smoke
on the same model took 8.3 seconds. Model load was warm in those runs; prompt evaluation
and generation dominated. Rehearse and pre-warm real-model demonstrations, retain the
deterministic scripted proof, and do not present these timings as satisfying the CRUD
latency target. The platform does not yet reuse durable conversation context or provider
KV state between calls.

You can also inspect <http://localhost:5005/api/v1/model-profiles> and
<http://localhost:5005/health/ready>. Stop the preview without deleting its named data
volumes with:

```text
docker compose --file docker-compose.yml --file docker-compose.integration-test.yml down --remove-orphans
```

The UI's direct record controls are deterministic boundary checks. The longer-horizon
scenario asks the model to search, inspect, and verify dependencies. A real model may
still choose a shorter valid plan or fail to follow it, so its output is intentionally
treated as probabilistic and its full safe trace is shown in the page. The scripted
test is the deterministic proof that the core executes all three planned actions.

Validate its optional Compose topology with:

```text
docker compose --file docker-compose.yml --file docker-compose.integration-test.yml \
  --profile release-0 --profile ollama-container --profile integration-test config --quiet
```

This is a pattern and integration fixture, not a substitute for any student's
approved frontend/backend/database feature or its full CRUD implementation.
