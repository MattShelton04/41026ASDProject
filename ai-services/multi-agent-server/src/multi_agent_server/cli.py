"""Terminal interface: serve the API, or run, inspect, decide and export workflows.

Every workflow command works in one of two modes:

* **in-process** (default): the command opens the state store directly and runs the agents
  synchronously in this process, so ``run`` returns once the run reaches ``awaiting_human``.
  Use it offline with ``--deterministic`` and ``--tool-fixtures``. Do not use it against a
  state directory that a running server is using.
* **server** (``--server [URL]``): the command calls a running server's HTTP API with the
  service token (``MULTI_AGENT_SERVICE_TOKEN`` or the host runtime's token file). This is the
  integrated path: the server's Worker reaches feature tools through MCP.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Protocol
from uuid import UUID

from multi_agent_server.client import MultiAgentClient, MultiAgentClientError
from multi_agent_server.errors import MultiAgentError
from multi_agent_server.evidence import export_run
from multi_agent_server.service import WorkflowService, not_accepted_step_ids
from multi_agent_server.settings import (
    DEFAULT_PORT,
    MultiAgentSettings,
    SettingsError,
    build_gateway,
    build_service,
)
from multi_agent_server.templates import validate_manifest
from multi_agent_server.terminal import Cursors, follow, interactive_review, trail_lines
from shared_contracts.multi_agent import (
    FindingOutcome,
    HumanDecisionKind,
    HumanDecisionRequest,
    WorkflowRun,
    WorkflowRunHistory,
    WorkflowRunPage,
    WorkflowRunRequest,
    WorkflowState,
    WorkflowTemplateList,
)

HOST_TOKEN_FILE = Path(".propertyscope-runtime/host/multi-agent.token")


class Backend(Protocol):
    """Operations shared by the in-process and HTTP modes."""

    def templates(self) -> WorkflowTemplateList: ...
    def start(self, request: WorkflowRunRequest) -> WorkflowRun: ...
    def run(self, run_id: UUID) -> WorkflowRun: ...
    def runs(
        self, template_id: str | None, feature_id: str | None, limit: int
    ) -> WorkflowRunPage: ...
    def decide(self, run_id: UUID, request: HumanDecisionRequest) -> WorkflowRun: ...
    def cancel(self, run_id: UUID, actor: str) -> WorkflowRun: ...
    def history(
        self, run_id: UUID, after_history: int = 0, after_audit: int = 0
    ) -> WorkflowRunHistory: ...
    def wait(self, run_id: UUID, timeout: float) -> WorkflowRun: ...
    def close(self) -> None: ...


class LocalBackend:
    """Runs agents synchronously in this process against the local state store."""

    def __init__(self, service: WorkflowService) -> None:
        self._service = service

    def templates(self) -> WorkflowTemplateList:
        return self._service.describe_templates()

    def start(self, request: WorkflowRunRequest) -> WorkflowRun:
        return self._service.create_run(request, request_id=f"cli-{os.getpid()}")

    def run(self, run_id: UUID) -> WorkflowRun:
        return self._service.get_run(run_id)

    def runs(self, template_id: str | None, feature_id: str | None, limit: int) -> WorkflowRunPage:
        return self._service.list_runs(template_id=template_id, feature_id=feature_id, limit=limit)

    def decide(self, run_id: UUID, request: HumanDecisionRequest) -> WorkflowRun:
        return self._service.decide(run_id, request, request_id=f"cli-{os.getpid()}")

    def cancel(self, run_id: UUID, actor: str) -> WorkflowRun:
        return self._service.cancel(run_id, actor=actor, request_id=f"cli-{os.getpid()}")

    def history(
        self, run_id: UUID, after_history: int = 0, after_audit: int = 0
    ) -> WorkflowRunHistory:
        return self._service.history(run_id, after_history=after_history, after_audit=after_audit)

    def wait(self, run_id: UUID, timeout: float) -> WorkflowRun:
        return self._service.wait(run_id, timeout=timeout)

    def close(self) -> None:
        self._service.close()


class RemoteBackend:
    """Calls a running server over HTTP."""

    def __init__(self, client: MultiAgentClient) -> None:
        self._client = client

    def templates(self) -> WorkflowTemplateList:
        return self._client.templates()

    def start(self, request: WorkflowRunRequest) -> WorkflowRun:
        return self._client.start(request)

    def run(self, run_id: UUID) -> WorkflowRun:
        return self._client.run(run_id)

    def runs(self, template_id: str | None, feature_id: str | None, limit: int) -> WorkflowRunPage:
        filters: dict[str, str | int] = {"limit": limit}
        if template_id:
            filters["template_id"] = template_id
        if feature_id:
            filters["feature_id"] = feature_id
        return self._client.runs(**filters)

    def decide(self, run_id: UUID, request: HumanDecisionRequest) -> WorkflowRun:
        return self._client.decide(run_id, request)

    def cancel(self, run_id: UUID, actor: str) -> WorkflowRun:
        return self._client.cancel(run_id, actor=actor)

    def history(
        self, run_id: UUID, after_history: int = 0, after_audit: int = 0
    ) -> WorkflowRunHistory:
        return self._client.history(run_id, after_history=after_history, after_audit=after_audit)

    def wait(self, run_id: UUID, timeout: float) -> WorkflowRun:
        return self._client.wait(run_id, timeout=timeout)

    def close(self) -> None:
        self._client.close()


def _common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--server",
        nargs="?",
        const="",
        default=None,
        metavar="URL",
        help="Use a running server over HTTP (default URL: $MULTI_AGENT_BASE_URL or "
        f"http://127.0.0.1:$MULTI_AGENT_PORT, port {DEFAULT_PORT})",
    )
    parser.add_argument("--token-file", type=Path, help="Service token file for --server")
    parser.add_argument("--state-dir", type=Path, help="In-process state directory")
    parser.add_argument(
        "--template-path",
        action="append",
        type=Path,
        default=[],
        help="Register this manifest instead of discovering enabled features (repeatable)",
    )
    parser.add_argument("--tool-fixtures", type=Path, help="Serve tool results from a JSON fixture")
    parser.add_argument(
        "--deterministic",
        action="store_true",
        help="Use the deterministic provider (no model calls)",
    )
    parser.add_argument("--json", action="store_true", help="Print the full JSON response")


def build_parser() -> argparse.ArgumentParser:
    """The ``multi-agent-server`` command tree."""
    parser = argparse.ArgumentParser(prog="multi-agent-server", description=__doc__.split("\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)
    serve = commands.add_parser("serve", help="Serve the HTTP API in the foreground")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument(
        "--port", type=int, default=int(os.environ.get("MULTI_AGENT_PORT", DEFAULT_PORT))
    )
    validate = commands.add_parser("validate", help="Validate a workflow manifest")
    validate.add_argument("manifest", type=Path)
    validate.add_argument(
        "--catalog",
        action="append",
        type=Path,
        default=[],
        help="Tool catalogue to check tools against (default: enabled features' catalogues)",
    )
    templates = commands.add_parser("templates", help="List registered workflow templates")
    _common(templates)
    run = commands.add_parser("run", help="Start a workflow run")
    _common(run)
    run.add_argument("--template", required=True, help="Workflow template ID")
    run.add_argument("--input", default="{}", help="JSON object, or @path to a JSON file")
    run.add_argument("--requested-by", default=None)
    run.add_argument("--wait", action="store_true", help="Wait until a human decision is needed")
    run.add_argument(
        "--follow",
        action="store_true",
        help="Print each hand-off, tool call and state change as the agents work (implies --wait)",
    )
    run.add_argument(
        "--review",
        action="store_true",
        help="Follow the agents, then ask for the human decision here (interactive)",
    )
    run.add_argument("--actor", default=None, help="Default decision name for --review")
    run.add_argument("--timeout", type=float, default=300.0)
    status = commands.add_parser("status", help="Show a run")
    _common(status)
    status.add_argument("run_id", type=UUID)
    runs = commands.add_parser("list", help="List recent runs")
    _common(runs)
    runs.add_argument("--template", default=None)
    runs.add_argument("--feature", default=None)
    runs.add_argument("--limit", type=int, default=20)
    decide = commands.add_parser("decide", help="Record the human decision for a run")
    _common(decide)
    decide.add_argument("run_id", type=UUID)
    decide.add_argument(
        "--decision", required=True, choices=[kind.value for kind in HumanDecisionKind]
    )
    decide.add_argument("--note", default="")
    decide.add_argument("--actor", default=_default_actor())
    decide.add_argument(
        "--accept",
        action="append",
        default=[],
        metavar="STEP_ID",
        help="Accepted step for --decision partial (repeatable)",
    )
    decide.add_argument(
        "--wait", action="store_true", help="After a correction, wait for the re-run"
    )
    decide.add_argument("--timeout", type=float, default=300.0)
    review = commands.add_parser(
        "review",
        help="Interactive human review: follow the agents, show the evidence, record a decision",
    )
    _common(review)
    review.add_argument("run_id", type=UUID)
    review.add_argument("--actor", default=None, help="Default name recorded with the decision")
    review.add_argument("--timeout", type=float, default=300.0)
    cancel = commands.add_parser("cancel", help="Cancel an unfinished run")
    _common(cancel)
    cancel.add_argument("run_id", type=UUID)
    cancel.add_argument("--actor", default="terminal")
    history = commands.add_parser("history", help="Show a run's history and audit trail")
    _common(history)
    history.add_argument("run_id", type=UUID)
    export = commands.add_parser("export", help="Write run.json, both JSONL logs and summary.md")
    _common(export)
    export.add_argument("run_id", type=UUID)
    export.add_argument("--out", type=Path, default=None, help="Output directory")
    return parser


def _token(arguments: argparse.Namespace) -> str:
    if arguments.token_file is not None:
        return str(arguments.token_file.read_text(encoding="utf-8").strip())
    token = os.environ.get("MULTI_AGENT_SERVICE_TOKEN", "").strip()
    if token:
        return token
    if HOST_TOKEN_FILE.is_file():
        return HOST_TOKEN_FILE.read_text(encoding="utf-8").strip()
    raise SettingsError(
        "No service token: set MULTI_AGENT_SERVICE_TOKEN or pass --token-file "
        f"(the host runtime writes {HOST_TOKEN_FILE.as_posix()})"
    )


def _settings(arguments: argparse.Namespace) -> MultiAgentSettings:
    settings = MultiAgentSettings.from_environment(require_token=False)
    if arguments.state_dir is not None:
        settings = dataclasses.replace(settings, state_directory=arguments.state_dir)
    if arguments.template_path:
        settings = dataclasses.replace(settings, template_paths=tuple(arguments.template_path))
    if arguments.tool_fixtures is not None:
        settings = dataclasses.replace(settings, tool_fixture_path=arguments.tool_fixtures)
    if arguments.deterministic:
        settings = dataclasses.replace(settings, provider="deterministic")
    return settings


def _backend(arguments: argparse.Namespace) -> Backend:
    if arguments.server is not None:
        url = (
            arguments.server
            or os.environ.get("MULTI_AGENT_BASE_URL", "").strip()
            or (f"http://127.0.0.1:{os.environ.get('MULTI_AGENT_PORT', DEFAULT_PORT)}")
        )
        if arguments.deterministic or arguments.tool_fixtures or arguments.template_path:
            raise SettingsError(
                "--deterministic, --tool-fixtures and --template-path configure in-process runs; "
                "configure the server with MULTI_AGENT_* variables instead"
            )
        return RemoteBackend(MultiAgentClient(url, _token(arguments)))
    return LocalBackend(build_service(_settings(arguments), inline=True))


def _default_actor() -> str:
    return os.environ.get("USERNAME") or os.environ.get("USER") or "terminal"


def _say(line: str) -> None:
    print(line, flush=True)


def _review(
    backend: Backend,
    run_id: UUID,
    actor: str | None,
    timeout: float,
    follow_from: Cursors | None = None,
) -> int:
    return interactive_review(
        backend,
        run_id,
        actor=actor or _default_actor(),
        ask=input,
        say=_say,
        render=lambda run: render_run(run, next_steps=False),
        follow_from=follow_from,
        timeout=timeout,
    )


def _input(value: str) -> dict[str, object]:
    raw = Path(value[1:]).read_text(encoding="utf-8") if value.startswith("@") else value
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise SettingsError("--input must be a JSON object")
    return payload


def render_run(run: WorkflowRun, *, next_steps: bool = True) -> str:
    """Readable terminal summary of a run."""
    lines = [
        f"Run {run.id}",
        f"  State:     {run.state.value} (round {run.round}, {run.provider_mode} agents)",
        f"  Template:  {run.template_id} {run.template_version} for {run.feature_id}",
        f"  Requested: {run.requested_by} at {run.created_at.isoformat()}",
        "  Stages:    "
        + " -> ".join(f"{stage.stage.value}:{stage.status}" for stage in run.stages),
    ]
    if run.plan is not None:
        lines.append(f"\nPlanner ({run.plan.produced_by.provider}): {run.plan.summary}")
        for step in run.plan.steps:
            arguments = json.dumps(step.arguments, sort_keys=True)
            lines.append(f"  {step.index}. {step.title} [{step.tool} {arguments}]")
    if run.worker_output is not None:
        lines.append(
            f"\nWorker ({run.worker_output.produced_by.provider}): {run.worker_output.summary}"
        )
        for result in run.worker_output.steps:
            lines.append(f"  - {result.step_id}: {result.status}")
            lines.extend(f"      {finding}" for finding in result.findings)
    if run.review is not None:
        lines.append(
            f"\nReviewer ({run.review.produced_by.provider}) recommends "
            f"{run.review.recommendation.value.upper()}: {run.review.summary}"
        )
        for finding in run.review.findings:
            mark = "FAIL" if finding.outcome is FindingOutcome.FAIL else finding.outcome.value
            lines.append(f"  [{mark} {finding.severity.value}] {finding.message}")
            if finding.recommendation and finding.outcome is FindingOutcome.FAIL:
                lines.append(f"      -> {finding.recommendation}")
    for decision in run.decisions:
        lines.append(
            f"\nHuman decision (round {decision.round}): {decision.decision.value} by "
            f"{decision.actor} at {decision.decided_at.isoformat()} -> "
            f"{decision.resulting_state.value}"
            + (f"\n  Note: {decision.note}" if decision.note else "")
        )
        if decision.accepted_step_ids:
            left_out = not_accepted_step_ids(run, decision.accepted_step_ids)
            lines.append(
                f"  Accepted steps: {', '.join(decision.accepted_step_ids)}"
                + (f"; not accepted: {', '.join(left_out)}" if left_out else "")
            )
    if run.error is not None:
        stage = f" (during {run.error.stage.value})" if run.error.stage else ""
        lines.append(f"\nFailed{stage}: {run.error.code}: {run.error.message}")
    if next_steps and run.state is WorkflowState.AWAITING_HUMAN:
        lines.append(
            f"\nNext: multi-agent-server review {run.id}   (interactive), or\n"
            f"      multi-agent-server decide {run.id} --decision "
            'approve|correct|partial|reject --note "..."'
        )
    return "\n".join(lines)


def _print_run(run: WorkflowRun, as_json: bool) -> None:
    print(json.dumps(run.model_dump(mode="json"), indent=2) if as_json else render_run(run))


def _validate(arguments: argparse.Namespace) -> int:
    settings = MultiAgentSettings.from_environment(require_token=False)
    if arguments.catalog:
        settings = dataclasses.replace(settings, tool_catalog_paths=tuple(arguments.catalog))
    # Definitions only: validation never calls a tool.
    gateway = build_gateway(
        dataclasses.replace(settings, tool_transport="none", tool_fixture_path=None)
    )
    template, issues = validate_manifest(
        arguments.manifest, gateway=gateway, root=settings.repository_root
    )
    if template is None or issues:
        print(f"INVALID {arguments.manifest}")
        for issue in issues:
            print(f"  - {issue}")
        return 1
    print(
        f"VALID {arguments.manifest}: {template.id} {template.version} for {template.feature_id} "
        f"({len(template.steps)} step(s), {len(template.reviewer_checks)} check(s), "
        f"tools: {', '.join(template.allowed_tools)})"
    )
    return 0


def _serve(arguments: argparse.Namespace) -> int:
    from waitress import serve

    from multi_agent_server.app import create_app

    serve(create_app(), host=arguments.host, port=arguments.port, threads=8)
    return 0


def _workflow(arguments: argparse.Namespace) -> int:
    backend = _backend(arguments)
    try:
        command = arguments.command
        if command == "templates":
            listing = backend.templates()
            if arguments.json:
                print(json.dumps(listing.model_dump(mode="json"), indent=2))
            else:
                for item in listing.items:
                    template = item.template
                    tools = ", ".join(
                        f"{tool.name}{'' if tool.available else ' (unavailable)'}"
                        for tool in item.tools
                    )
                    print(
                        f"{template.id} {template.version} [{template.feature_id}] {template.title}"
                    )
                    required = json.dumps(item.input_schema.get("required", []))
                    print(f"  inputs: {required}; tools: {tools}")
                if not listing.items:
                    print("No workflow templates are registered.")
            return 0
        if command == "run":
            run = backend.start(
                WorkflowRunRequest(
                    template_id=arguments.template,
                    input=_input(arguments.input),
                    requested_by=arguments.requested_by
                    or (arguments.actor if arguments.review else None),
                )
            )
            if arguments.review:
                return _review(
                    backend,
                    run.id,
                    arguments.actor or arguments.requested_by,
                    arguments.timeout,
                    follow_from=Cursors(),
                )
            if arguments.follow:
                _say(f"Run {run.id} started; following the agents...")
                run, _ = follow(backend, run.id, say=_say, timeout=arguments.timeout)
                _say("")
            elif arguments.wait:
                run = backend.wait(run.id, arguments.timeout)
            _print_run(run, arguments.json)
            return 1 if run.state is WorkflowState.FAILED else 0
        if command == "status":
            _print_run(backend.run(arguments.run_id), arguments.json)
            return 0
        if command == "list":
            page = backend.runs(arguments.template, arguments.feature, arguments.limit)
            if arguments.json:
                print(json.dumps(page.model_dump(mode="json"), indent=2))
            for summary in [] if arguments.json else page.items:
                print(
                    f"{summary.id}  {summary.state.value:<19} {summary.template_id} "
                    f"{summary.created_at.isoformat()} by {summary.requested_by}"
                )
            return 0
        if command == "decide":
            run = backend.decide(
                arguments.run_id,
                HumanDecisionRequest(
                    decision=HumanDecisionKind(arguments.decision),
                    note=arguments.note,
                    actor=arguments.actor,
                    accepted_step_ids=tuple(arguments.accept),
                ),
            )
            if arguments.wait:
                run = backend.wait(run.id, arguments.timeout)
            _print_run(run, arguments.json)
            return 0
        if command == "review":
            return _review(backend, arguments.run_id, arguments.actor, arguments.timeout)
        if command == "cancel":
            _print_run(backend.cancel(arguments.run_id, arguments.actor), arguments.json)
            return 0
        if command == "history":
            history = backend.history(arguments.run_id)
            if arguments.json:
                print(json.dumps(history.model_dump(mode="json"), indent=2))
                return 0
            print(
                f"Run {history.run_id} is {history.state.value}: "
                f"{len(history.history)} transition(s) (==), {len(history.audit)} "
                "coordination event(s) (.)"
            )
            for line in trail_lines(history):
                print(line)
            return 0
        run = backend.run(arguments.run_id)
        history = backend.history(arguments.run_id)
        destination = arguments.out or (
            _settings(arguments).state_directory / "exports" / str(run.id)
        )
        run_template = next(
            (
                item.template
                for item in backend.templates().items
                if item.template.id == run.template_id
                and item.template.version == run.template_version
            ),
            None,
        )
        for path in export_run(run, history, destination, run_template):
            print(path.as_posix())
        return 0
    finally:
        backend.close()


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point for ``uv run multi-agent-server``."""
    arguments = build_parser().parse_args(argv)
    try:
        if arguments.command == "serve":
            return _serve(arguments)
        if arguments.command == "validate":
            return _validate(arguments)
        return _workflow(arguments)
    except (MultiAgentError, MultiAgentClientError, SettingsError, ValueError, OSError) as exc:
        detail = exc.detail if isinstance(exc, MultiAgentError) else str(exc)
        print(f"error: {detail}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
