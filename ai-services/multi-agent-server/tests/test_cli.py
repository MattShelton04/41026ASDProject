"""Terminal interface: in-process and server mode, validation and evidence export."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
import pytest
from flask import Flask

from multi_agent_server import cli
from multi_agent_server.client import MultiAgentClient, MultiAgentClientError
from shared_contracts.multi_agent import HumanDecisionKind, HumanDecisionRequest

FIXTURES = Path(__file__).parent / "fixtures"
TEMPLATE = FIXTURES / "workflow.yaml"
TOOLS = FIXTURES / "tools.json"
RECORD_ID = "8c0d7e0e-4a3b-4c55-9a62-0d7c5f0f9a11"
TOKEN = "test-multi-agent-token-0123456789abcdef"
ENVIRONMENT = (
    "MULTI_AGENT_SERVICE_TOKEN",
    "MULTI_AGENT_BASE_URL",
    "MULTI_AGENT_PORT",
    "MULTI_AGENT_TEMPLATE_PATHS",
    "MULTI_AGENT_TOOL_CATALOG_PATHS",
    "MCP_TOOL_CATALOG_PATHS",
    "AI_MODE_TOOL_CATALOG_PATHS",
    "MULTI_AGENT_TOOL_FIXTURES",
    "MULTI_AGENT_PROVIDER",
    "MULTI_AGENT_STATE_DIR",
    "MULTI_AGENT_REPOSITORY_ROOT",
    "MULTI_AGENT_MCP_ENABLED",
    "AI_MODE_MCP_ENABLED",
)


@pytest.fixture(autouse=True)
def isolated(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    for name in ENVIRONMENT:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)


def local(*arguments: str) -> list[str]:
    command, *rest = arguments
    return [
        command,
        "--state-dir",
        "state",
        "--template-path",
        str(TEMPLATE),
        "--tool-fixtures",
        str(TOOLS),
        "--deterministic",
        *rest,
    ]


def invoke(capsys: pytest.CaptureFixture[str], *arguments: str) -> tuple[int, str, str]:
    code = cli.main(list(arguments))
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def test_in_process_workflow_end_to_end(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    code, out, _ = invoke(capsys, *local("templates"))
    assert code == 0
    assert "example-readiness-review v1 [example-feature]" in out

    input_file = tmp_path / "input.json"
    input_file.write_text(json.dumps({"record_id": RECORD_ID}), encoding="utf-8")
    code, out, _ = invoke(
        capsys,
        *local(
            "run", "--template", "example-readiness-review", "--input", f"@{input_file}", "--json"
        ),
    )
    assert code == 0
    run = json.loads(out)
    run_id = run["id"]
    assert run["state"] == "awaiting_human"

    code, out, _ = invoke(capsys, *local("status", run_id))
    assert "State:     awaiting_human" in out
    assert "recommends APPROVE" in out
    assert "Next: multi-agent-server decide" in out

    code, out, _ = invoke(
        capsys,
        *local("decide", run_id, "--decision", "correct", "--note", "Recheck", "--actor", "me"),
    )
    assert code == 0
    assert "round 2" in out
    code, out, _ = invoke(
        capsys,
        *local(
            "decide", run_id, "--decision", "partial", "--note", "Record only", "--accept", "record"
        ),
    )
    assert "-> partially_accepted" in out
    assert "Note: Record only" in out

    code, out, _ = invoke(capsys, *local("list", "--template", "example-readiness-review"))
    assert run_id in out and "partially_accepted" in out
    code, out, _ = invoke(capsys, *local("list", "--json"))
    assert json.loads(out)["count"] == 1

    code, out, _ = invoke(capsys, *local("history", run_id))
    assert "decision.recorded" in out
    code, out, _ = invoke(capsys, *local("history", run_id, "--json"))
    assert json.loads(out)["state"] == "partially_accepted"

    code, out, _ = invoke(capsys, *local("export", run_id))
    written = [Path(line) for line in out.splitlines()]
    assert [path.name for path in written] == [
        "run.json",
        "workflow_history.jsonl",
        "coordination_audit.jsonl",
        "summary.md",
    ]
    assert written[0].parent == Path("state") / "exports" / run_id
    summary = written[3].read_text(encoding="utf-8")
    assert "partially_accepted" in summary
    assert "## Coordination audit" in summary


def test_in_process_cancel_and_templates_json(capsys: pytest.CaptureFixture[str]) -> None:
    code, out, _ = invoke(capsys, *local("templates", "--json"))
    assert json.loads(out)["count"] == 1
    _, out, _ = invoke(
        capsys,
        *local(
            "run",
            "--template",
            "example-readiness-review",
            "--input",
            json.dumps({"record_id": RECORD_ID}),
            "--json",
        ),
    )
    run_id = json.loads(out)["id"]
    code, out, _ = invoke(capsys, *local("cancel", run_id, "--actor", "operator"))
    assert code == 0
    assert "cancelled" in out


def test_errors_are_reported_on_stderr(capsys: pytest.CaptureFixture[str]) -> None:
    code, _, err = invoke(capsys, *local("status", str(uuid4())))
    assert code == 1
    assert err.startswith("error: Workflow run")
    code, _, err = invoke(
        capsys, *local("run", "--template", "example-readiness-review", "--input", "[1]")
    )
    assert (code, err.strip()) == (1, "error: --input must be a JSON object")
    code, _, err = invoke(
        capsys, *local("run", "--template", "example-readiness-review", "--input", "{}")
    )
    assert code == 1
    assert "input schema" in err


def test_templates_without_manifests(capsys: pytest.CaptureFixture[str]) -> None:
    code, out, _ = invoke(capsys, "templates", "--state-dir", "state", "--deterministic")
    assert code == 0
    assert "No workflow templates are registered." in out


def test_failed_runs_exit_non_zero(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    payload = json.loads(TOOLS.read_text(encoding="utf-8"))
    for entry in payload["tools"]:
        entry.pop("result", None)
        entry["error"] = {"code": "down", "message": "Down"}
    broken = tmp_path / "broken.json"
    broken.write_text(json.dumps(payload), encoding="utf-8")
    code, out, _ = invoke(
        capsys,
        "run",
        "--state-dir",
        "state",
        "--template-path",
        str(TEMPLATE),
        "--tool-fixtures",
        str(broken),
        "--deterministic",
        "--template",
        "example-readiness-review",
        "--input",
        json.dumps({"record_id": RECORD_ID}),
    )
    assert code == 0
    assert "recommends REJECT" in out
    assert "FAIL critical" in out


def test_validate_command(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    catalog = tmp_path / "catalog.json"
    tools = json.loads(TOOLS.read_text(encoding="utf-8"))["tools"]
    catalog.write_text(
        json.dumps(
            {
                "services": [{"service": "svc", "base_url": "http://127.0.0.1:1"}],
                "tools": [
                    {
                        "definition": entry["definition"],
                        "service": "svc",
                        "method": "POST",
                        "path": f"/tools/{index}",
                    }
                    for index, entry in enumerate(tools)
                ],
            }
        ),
        encoding="utf-8",
    )
    code, out, _ = invoke(capsys, "validate", str(TEMPLATE), "--catalog", str(catalog))
    assert code == 0
    assert out.startswith(f"VALID {TEMPLATE}: example-readiness-review v1")

    code, out, _ = invoke(capsys, "validate", str(TEMPLATE))
    assert code == 1
    assert "is not registered in any tool catalogue" in out

    broken = tmp_path / "workflow.yaml"
    broken.write_text("schema_version: 1\nid: Bad\n", encoding="utf-8")
    code, out, _ = invoke(capsys, "validate", str(broken))
    assert code == 1
    assert out.startswith("INVALID")


def test_serve_uses_waitress(monkeypatch: pytest.MonkeyPatch) -> None:
    served: dict[str, Any] = {}

    def fake_serve(app: Any, **options: Any) -> None:
        served.update(options, app=app)

    import waitress

    monkeypatch.setattr(waitress, "serve", fake_serve)
    monkeypatch.setattr("multi_agent_server.app.create_app", lambda: "app")
    assert cli.main(["serve", "--port", "5999"]) == 0
    assert served == {"app": "app", "host": "127.0.0.1", "port": 5999, "threads": 8}


@pytest.fixture
def server(monkeypatch: pytest.MonkeyPatch, app: Flask) -> Flask:
    """Route the CLI's HTTP client to the in-process Flask app."""
    original = MultiAgentClient

    def wired(base_url: str, token: str, **options: Any) -> MultiAgentClient:
        assert base_url == "http://127.0.0.1:5013"
        return original(base_url, token, transport=httpx.WSGITransport(app=app))

    monkeypatch.setattr(cli, "MultiAgentClient", wired)
    return app


def test_server_mode_uses_the_http_api(
    capsys: pytest.CaptureFixture[str], server: Flask, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MULTI_AGENT_SERVICE_TOKEN", TOKEN)

    code, out, _ = invoke(capsys, "templates", "--server")
    assert code == 0 and "example-readiness-review" in out
    code, out, _ = invoke(
        capsys,
        "run",
        "--server",
        "--template",
        "example-readiness-review",
        "--input",
        json.dumps({"record_id": RECORD_ID}),
        "--requested-by",
        "terminal",
        "--wait",
        "--json",
    )
    run_id = json.loads(out)["id"]
    assert json.loads(out)["state"] == "awaiting_human"
    code, out, _ = invoke(
        capsys,
        "list",
        "--server",
        "--template",
        "example-readiness-review",
        "--feature",
        "example-feature",
    )
    assert run_id in out
    code, out, _ = invoke(capsys, "status", run_id, "--server")
    assert "awaiting_human" in out
    code, out, _ = invoke(
        capsys, "decide", run_id, "--server", "--decision", "correct", "--note", "again", "--wait"
    )
    assert "round 2" in out
    code, out, _ = invoke(capsys, "history", run_id, "--server")
    assert "agent.handoff" in out
    code, out, _ = invoke(capsys, "cancel", run_id, "--server")
    assert "cancelled" in out
    code, out, _ = invoke(capsys, "export", run_id, "--server", "--out", "evidence")
    assert code == 0 and len(out.splitlines()) == 4
    code, _, err = invoke(capsys, "cancel", run_id, "--server")
    assert code == 1 and "HTTP 409 invalid_state_transition" in err


def test_server_mode_token_sources(
    capsys: pytest.CaptureFixture[str], server: Flask, tmp_path: Path
) -> None:
    code, _, err = invoke(capsys, "templates", "--server")
    assert code == 1 and "No service token" in err

    token_file = tmp_path / "token"
    token_file.write_text(TOKEN + "\n", encoding="utf-8")
    assert invoke(capsys, "templates", "--server", "--token-file", str(token_file))[0] == 0

    cli.HOST_TOKEN_FILE.parent.mkdir(parents=True)
    cli.HOST_TOKEN_FILE.write_text("wrong-token-wrong-token-wrong-token-0000", encoding="utf-8")
    code, _, err = invoke(capsys, "templates", "--server")
    assert code == 1 and "HTTP 401 unauthorized" in err

    code, _, err = invoke(capsys, "templates", "--server", "--deterministic")
    assert code == 1 and "configure in-process runs" in err


def test_client_errors() -> None:
    def broken(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/templates"):
            raise httpx.ConnectError("refused")
        return httpx.Response(502, text="bad gateway")

    with MultiAgentClient("http://x", TOKEN, transport=httpx.MockTransport(broken)) as client:
        with pytest.raises(MultiAgentClientError) as unreachable:
            client.templates()
        assert unreachable.value.status is None
        assert str(unreachable.value).startswith("unreachable:")
        with pytest.raises(MultiAgentClientError) as gateway:
            client.decide(
                uuid4(), HumanDecisionRequest(decision=HumanDecisionKind.APPROVE, actor="a")
            )
        assert (gateway.value.status, gateway.value.code) == (502, "http_error")
