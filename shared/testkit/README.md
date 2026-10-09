# Shared testkit

Reusable deterministic assertions and fakes for service tests. This package is test
support only; production orchestration must remain in `agent-core` and `ai-mode`.

`ScriptedLLMProvider` returns a finite sequence of structured responses or exceptions,
records every provider request, exposes deterministic health, and fails on unexpected
extra invocations. It lets CI cover schema repair, provider failure, and exact invocation
counts without credentials or remote model calls.

The testkit also validates shared Problem Details responses. Add only genuinely reusable,
domain-neutral helpers here; feature fixtures stay in their owning student slice.

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
    recommendation=HumanDecisionKind.CORRECT,      # Reviewer recommendation for every run
    failed_checks=["quality-clean"],               # these reviewer checks report FAIL
    tool_results={"my.tool.v1": {"count": 3}},     # evidence excerpts per tool
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
