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
plan over real loopback HTTP with the scripted model; OpenAI credentials and Docker are not
required. A public-API lifecycle test additionally drives idempotent create/replay,
run detail, paged events, filtered durable history, safe evidence caching, model registry,
shared Problem Details, and both protected-action review decisions through a live AI-mode
HTTP server and the real feature hops. Approval resumes the original idempotent call exactly
once; rejection persists an immutable review and proves the write was never applied.

The fixture also demonstrates two boundary conventions intended for real features:
checked-in tool catalogues are composed by the canonical quality gate, and HTTP errors
use the shared Problem Details contract across backend/database hops. Feature owners
should encode expected negative evidence such as an empty search as a successful typed
tool response; non-retryable HTTP/tool errors are reserved for requests that must fail
closed.

## Run the working preview

With Docker Desktop running and `OPENAI_API_KEY` exported in the launching shell, start the
fixture and AI-mode:

```text
uv run scripts/dev.py up
```

This development path bind-mounts the frontend and Python source, reloads Gunicorn after
Python edits, and preserves all named volumes on `uv run scripts/dev.py down`. Run
`uv run scripts/dev.py rebuild` only when dependencies, the lockfile, or Dockerfiles change.

The equivalent production-like Compose sequence without development mounts is:

```text
docker compose --file docker-compose.yml --file docker-compose.integration-test.yml --profile release-0 --profile integration-test up --detach --build --wait --wait-timeout 120 ai-mode integration-test-feature-database integration-test-feature-backend integration-test-feature-frontend
```

No model image or weights are downloaded. Open <http://localhost:5190> to:

- search the ten deterministic records through frontend -> backend -> database;
- inspect record detail and its dependency graph without invoking a model;
- create an idempotent record through the same service boundary;
- inspect the live model registry; and
- submit and poll a real multi-action Plan -> Act -> Observe -> Adapt AI-mode run;
- browse, filter, page through, and reload durable prior runs from AI-mode; and
- explicitly reuse a selected run's safe objective and result as context for a new run;
- pause a protected write for human review, inspect its arguments and idempotency key,
  then approve-and-resume or reject-without-executing it.

The console presents the run as a conversation-like transcript without claiming that
one run is a durable multi-turn conversation. Follow-up context is copied into a new
independent objective rather than implying provider-side conversation memory. It visualises every persisted phase,
tool call/result, model invocation summary, safe progress event, run/request ID, and
W3C trace context. The complete safe run-detail JSON remains available in an expandable
debug panel.

The longer-horizon preset uses `default.v3` and a six-minute client/run window. Remote-model
latency and output remain probabilistic, so retain the deterministic scripted proof and do not
present provider timings as satisfying the CRUD latency target. The platform reconstructs each
request from persisted safe state and does not use provider-side conversation state.

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
  --profile release-0 --profile integration-test config --quiet
```

This is a pattern and integration fixture, not a substitute for any student's
approved frontend/backend/database feature or its full CRUD implementation. Its review
checkpoint exercises the already-built shared policy foundation and does not claim that the
Release 2 multi-agent Reviewer role is complete.
