# Shared testkit

Reusable deterministic assertions and fakes for service tests. This package is test
support only; production orchestration must remain in `agent-core` and `ai-mode`.

`ScriptedLLMProvider` returns a finite sequence of structured responses or exceptions,
records every provider request, exposes deterministic health, and fails on unexpected
extra invocations. It lets CI cover schema repair, provider failure, and exact invocation
counts without credentials or remote model calls.

The testkit also validates shared Problem Details responses. Add only genuinely reusable,
domain-neutral helpers here; feature fixtures stay in their owning student slice.

## Endpoint tests against a running service

Release 2 asks every `student-N.yml` to test two endpoint functions of its backend after the
Compose stack is up (R2-32). The testkit provides the shared parts; each slice writes its own
cases in `student-N/tests/endpoints/`.

| Name | Purpose |
|---|---|
| `endpoint` marker | Registered in the root `pyproject.toml`. Marked tests are skipped unless `PROPERTYSCOPE_ENDPOINT_BASE_URL` is set, so `pytest` and `check.py` never need Docker |
| `shared_testkit.endpoints.EndpointClient` | `httpx` client for one origin: 10 s read / 3 s connect timeouts, a fresh contract-valid `X-Request-ID` per request (override with `request_id=`), retries only for connection failures that sent nothing, `get/post/put/delete`, `get_json` |
| `EndpointClient.wait_until_ready(path)` | Polls a health route through connection errors and `5xx` until a deadline; a `4xx` fails at once because the route is wrong |
| `expect_status`, `expect_json`, `expect_problem` | Assertions that print the method, URL, request ID and a body excerpt on failure. `expect_problem` validates the shared `ProblemDetail` contract, the `application/problem+json` media type and, optionally, the echoed request ID |
| `shared_testkit.pytest_endpoints` | The `endpoint_client` session fixture (ready client, or a skip), the `endpoint_ready_path` fixture, and the skip hook |
| `python -m shared_testkit.junit_summary` | Renders a pytest JUnit XML file as a Markdown table for `$GITHUB_STEP_SUMMARY`; `--require-success` exits 1 unless something passed and nothing failed |

Environment variables:

| Variable | Default | Meaning |
|---|---|---|
| `PROPERTYSCOPE_ENDPOINT_BASE_URL` | unset (tests skip) | Service origin, for example `http://127.0.0.1:5200`. A malformed value is an error, not a skip |
| `PROPERTYSCOPE_ENDPOINT_READY_PATH` | `/health/ready` | Readiness route polled once per session (the Shared edge uses `/healthz`) |
| `PROPERTYSCOPE_ENDPOINT_READY_TIMEOUT` | `60` | Readiness deadline in seconds |

### Add endpoint tests to a slice

1. Create `student-N/tests/endpoints/conftest.py` that re-exports the plugin. If your
   `tests/` directory already has a `conftest.py`, add these lines there instead: `check.py`
   type-checks `student-1/tests` and `student-2/tests` in one mypy run, which rejects two
   modules both named `conftest`. Feature 1 adds `tests/endpoints/__init__.py` for that reason.

   ```python
   from shared_testkit.pytest_endpoints import (
       endpoint_client,
       endpoint_ready_path,
       pytest_collection_modifyitems,
   )

   __all__ = ["endpoint_client", "endpoint_ready_path", "pytest_collection_modifyitems"]
   ```

2. Write tests that mark themselves and use the fixture. Test the happy path and one failure
   case per endpoint function, assert the response shape, and delete anything you create.

   ```python
   import pytest

   from shared_testkit.endpoints import EndpointClient, expect_json, expect_problem

   pytestmark = pytest.mark.endpoint


   def test_list_returns_a_page(endpoint_client: EndpointClient) -> None:
       page = expect_json(endpoint_client.get("/api/my-feature/v1/items"), status=200)
       assert isinstance(page["items"], list)


   def test_invalid_payload_is_a_problem(endpoint_client: EndpointClient) -> None:
       request_id = endpoint_client.new_request_id()
       response = endpoint_client.post("/api/my-feature/v1/items", json={}, request_id=request_id)
       expect_problem(response, status=422, code="invalid_request", request_id=request_id)
   ```

3. Run them against your local stack:
   `PROPERTYSCOPE_ENDPOINT_BASE_URL=http://localhost:<port> uv run pytest student-N/tests/endpoints -m endpoint --no-cov -q`.

4. Add the steps below to the job in `student-N.yml` that starts the stack, after
   `up --wait` and any seeding, and add `"shared/testkit/**"` to both `paths:` filters. The
   artifact must be named `student-N-endpoint-tests` so `scripts/collect_ci_evidence.py` can
   find it. `scripts/tests/test_workflow_consistency.py` checks all of this for every slice
   that has a `tests/endpoints` directory.

   ```yaml
         - name: Run Feature N endpoint tests
           env:
             # Your feature's host port (see the port table in AGENTS.md).
             PROPERTYSCOPE_ENDPOINT_BASE_URL: http://127.0.0.1:5300
             PROPERTYSCOPE_ENDPOINT_READY_PATH: /health/ready
           run: uv run --locked pytest student-N/tests/endpoints -m endpoint --no-cov -q -rA --junitxml=endpoint-results/student-N-endpoints.xml
         - name: Publish endpoint test summary
           if: ${{ !cancelled() && hashFiles('endpoint-results/*.xml') != '' }}
           run: uv run --locked python -m shared_testkit.junit_summary endpoint-results/student-N-endpoints.xml --title "Feature N endpoint tests" --output endpoint-results/student-N-endpoints.md --require-success >> "$GITHUB_STEP_SUMMARY"
         - name: Upload endpoint test results
           if: ${{ !cancelled() && hashFiles('endpoint-results/*.xml') != '' }}
           uses: actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a # v7.0.1
           with:
             name: student-N-endpoint-tests
             path: endpoint-results/
             if-no-files-found: error
             retention-days: 30
   ```

   The job needs `uv sync --locked --all-packages --all-groups` (or `uv run --locked`, which
   syncs) before these steps. `student-1.yml` is the working reference.

5. After a green run on `main`, record it with
   `uv run python scripts/collect_ci_evidence.py --student N` (see
   [`docs/release-2/evidence/ci/README.md`](../../docs/release-2/evidence/ci/README.md)).

## Multi-Agent Server fake

`FakeMultiAgentServer` is an in-memory implementation of the Multi-Agent Server HTTP API
(`/api/v1/multi-agent`, see `shared/contracts/openapi/multi-agent.v1.openapi.json`). It uses the
same bearer-token authentication, Problem Details codes, state rules (one correction round) and
generated response contracts as `ai-services/multi-agent-server`, but runs no agents, models or
tools. A parity test in the server package runs one scenario against both and compares them.

```python
from shared_testkit import FAKE_MULTI_AGENT_TOKEN, FakeMultiAgentServer
from shared_contracts.multi_agent import HumanDecisionKind, WorkflowTemplate

fake = FakeMultiAgentServer(
    [WorkflowTemplate.model_validate(yaml.safe_load(manifest.read_text()))],
    recommendation=HumanDecisionKind.CORRECT,  # Reviewer recommendation for every run
    failed_checks=["quality-clean"],  # these reviewer checks report FAIL
    tool_results={"my.tool.v1": {"count": 3}},  # evidence excerpts per tool
)

# 1. httpx clients
client = httpx.Client(transport=fake.transport(), base_url="http://multi-agent")
# 2. any WSGI-capable client: httpx.WSGITransport(app=fake)
# 3. code that opens sockets (requests/urllib): a loopback server on an ephemeral port
with fake.serve() as base_url:
    app.config["MULTI_AGENT_BASE_URL"] = base_url
```

Started runs settle immediately at `awaiting_human`. Pass `auto_settle=False` to keep them in
`planning` and drive them with `fake.settle(run_id, ...)` or `fake.fail(run_id, code=...)` to
test polling and failure paths. `fake.requests` records every request; `fake.run(run_id)` and
`fake.runs()` expose snapshots. Feature code and tests must not import `multi_agent_server`.
