"""Grouped command-line interface for local stack, UI, and data workflows."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from scripts.devtools.config import (
    APPLICATION_SERVICES,
    BUILD_SERVICES,
    COLLECTION_JOBS,
    DEFAULT_UI_FIXTURE_PORT,
    PRODUCTION_BUILD_SERVICES,
    UI_FIXTURE_SCENARIOS,
)
from scripts.devtools.runtime_settings import AI_CAPABILITY_MODES, AI_SERVICE_PORTS

_FIXTURE_PORT_HELP = (
    f"Loopback fixture port (default: $PROPERTYSCOPE_UI_FIXTURE_PORT or {DEFAULT_UI_FIXTURE_PORT})"
)


def _add_offline_option(command: argparse.ArgumentParser) -> None:
    command.add_argument(
        "--offline",
        action="store_true",
        help="Run data/non-AI workflows without requiring a live provider credential",
    )


def _add_env_file_option(command: argparse.ArgumentParser) -> None:
    command.add_argument(
        "--env-file",
        type=Path,
        help="Load provider settings from this dotenv file instead of the optional root .env",
    )


def _stack_commands(root: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    stack = root.add_parser(
        "stack", help="Operate the Compose feature stack together with the host AI services"
    )
    commands = stack.add_subparsers(dest="action", required=True)

    up = commands.add_parser(
        "up", help="Start host AI-mode/MCP/RAG processes and the reloadable Compose stack"
    )
    up.add_argument(
        "--build",
        action="store_true",
        help="Rebuild application images before starting the stack",
    )
    up.add_argument(
        "--no-reload",
        action="store_true",
        help="Use built images without source mounts/reload polling; add --build after edits",
    )
    _add_offline_option(up)
    _add_env_file_option(up)
    # Retired placement switch (ADR-046), kept hidden so older instructions fail helpfully.
    up.add_argument("--ai-runtime", default=None, help=argparse.SUPPRESS)

    build = commands.add_parser(
        "build", help="Build production-like Release 0 images without starting containers"
    )
    build.add_argument("services", nargs="*", choices=PRODUCTION_BUILD_SERVICES)

    rebuild = commands.add_parser(
        "rebuild", help="Rebuild and recreate changed development services"
    )
    rebuild.add_argument("services", nargs="*", choices=BUILD_SERVICES)
    _add_offline_option(rebuild)
    _add_env_file_option(rebuild)

    restart = commands.add_parser(
        "restart", help="Recreate application containers without rebuilding images"
    )
    restart.add_argument("services", nargs="*", choices=APPLICATION_SERVICES)
    _add_offline_option(restart)
    _add_env_file_option(restart)

    for name, help_text in (
        ("down", "Stop containers while preserving durable volumes"),
        ("reset", "Stop the stack and delete only its labelled durable volumes"),
        ("status", "Show current service and health state"),
        ("config", "Validate the merged Compose configuration"),
    ):
        commands.add_parser(name, help=help_text)

    doctor = commands.add_parser("doctor", help="Validate Docker and the Compose model")
    _add_env_file_option(doctor)

    logs = commands.add_parser(
        "logs", help="Show recent container logs and follow them (host AI logs: ai logs)"
    )
    logs.add_argument("services", nargs="*", choices=APPLICATION_SERVICES)
    logs.add_argument(
        "--no-follow",
        dest="follow",
        action="store_false",
        help="Print recent lines and exit (use from scripts and coding agents)",
    )
    logs.add_argument(
        "--tail", type=int, default=200, help="Recent lines per service (default: 200)"
    )


def _ui_commands(root: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    ui = root.add_parser("ui", help="Serve and audit deterministic browser fixtures")
    commands = ui.add_subparsers(dest="action", required=True)

    serve = commands.add_parser("serve", help="Serve Shared and Feature 1 fixtures without Docker")
    serve.add_argument("--port", type=int, default=None, help=_FIXTURE_PORT_HELP)
    serve.add_argument(
        "--scenario",
        choices=UI_FIXTURE_SCENARIOS,
        default=os.environ.get("PROPERTYSCOPE_UI_SCENARIO", "populated"),
        help="Deterministic API fixture state to serve (default: populated)",
    )

    smoke = commands.add_parser("smoke", help="Run the minimal Playwright render smoke")
    smoke.add_argument("--port", type=int, default=None, help=_FIXTURE_PORT_HELP)
    smoke.add_argument(
        "--scenario",
        choices=UI_FIXTURE_SCENARIOS,
        default="populated",
        help="Deterministic API fixture state to render (default: populated)",
    )
    smoke.add_argument(
        "--all-routes",
        action="store_true",
        help="Render every fixture route, not only the core set",
    )

    screenshots = commands.add_parser(
        "readme-screenshots",
        help="Refresh the deterministic screenshots embedded in the root README",
    )
    screenshots.add_argument("--port", type=int, default=None, help=_FIXTURE_PORT_HELP)
    screenshots.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Screenshot directory (default: docs/images/readme)",
    )

    audit = commands.add_parser("audit", help="Run a resumable browser interaction audit")
    audit.add_argument(
        "profile",
        choices=("quick", "full"),
        help="quick: core routes at two widths; full: the route/state/four-viewport matrix",
    )
    audit.add_argument("--port", type=int, default=None, help=_FIXTURE_PORT_HELP)
    audit.add_argument("--output", type=Path, default=None, help="Artifact directory")
    audit.add_argument("--resume", type=Path, default=None, help="Resume artifact directory")
    audit.add_argument(
        "--workspace",
        action="append",
        default=[],
        help="Limit to a workspace, e.g. shared or feature-1-property-discovery (repeatable)",
    )
    audit.add_argument(
        "--route-group", action="append", default=[], help="Limit to a route group (repeatable)"
    )
    audit.add_argument("--route", action="append", default=[], help="Limit to a route (repeatable)")
    audit.add_argument(
        "--scenario", action="append", default=[], help="Limit to a fixture scenario (repeatable)"
    )
    audit.add_argument(
        "--viewport", action="append", default=[], help="Limit to a viewport (repeatable)"
    )
    audit.add_argument("--shard-index", type=int, default=0, help="Zero-based shard to run")
    audit.add_argument("--shard-total", type=int, default=1, help="Number of stable shards")
    audit.add_argument(
        "--allow-destructive",
        action="store_true",
        help="Also exercise controls that mutate fixture state",
    )


def _data_commands(root: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    data = root.add_parser("data", help="Acquire and operate Feature 1 source data")
    commands = data.add_subparsers(dest="action", required=True)

    collect = commands.add_parser(
        "collect", help="Plan, queue, and optionally wait for a registered acquisition"
    )
    collect.add_argument(
        "job",
        choices=COLLECTION_JOBS,
        help="Registered job profile (student-1/config/job-profiles)",
    )
    collect.add_argument(
        "--wait",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Wait for the run to reach a terminal state (default); --no-wait only queues it",
    )
    collect.add_argument(
        "--timeout", type=int, default=900, help="Seconds to wait before giving up (default: 900)"
    )
    collect.add_argument(
        "--base-url",
        default=None,
        help="Feature 1 API root (default: http://127.0.0.1:$PROPERTYSCOPE_PORT/api/data-platform/v1)",
    )

    sync_psi = commands.add_parser(
        "sync-psi", help="Acquire official PSI archives into the read-only app cache"
    )
    sync_psi.add_argument(
        "--all", action="store_true", help="Every annual archive since 1990 plus this year's weeks"
    )
    sync_psi.add_argument(
        "--year", type=int, action="append", default=[], help="One annual archive (repeatable)"
    )
    sync_psi.add_argument(
        "--week",
        action="append",
        default=[],
        metavar="YYYY-MM-DD",
        help="One Monday weekly archive (repeatable)",
    )
    sync_psi.add_argument(
        "--current-weekly", action="store_true", help="Every Monday archive so far this year"
    )


def _operator_commands(root: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    operator = root.add_parser("operator", help="Inspect review and publication readiness")
    commands = operator.add_subparsers(dest="action", required=True)
    report = commands.add_parser("report", help="Print a read-only operational evidence report")
    report.add_argument("--base-url", help="Feature 1 API root (default: from PROPERTYSCOPE_PORT)")
    report.add_argument("--feature-health-url", help="Feature 1 readiness URL override")
    report.add_argument("--ai-health-url", help="AI-mode health URL override")


def _ai_commands(root: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    ai = root.add_parser(
        "ai", help="Operate the non-containerised AI-mode, MCP and RAG host processes"
    )
    commands = ai.add_subparsers(dest="action", required=True)
    start = commands.add_parser("start", help="Start or reconfigure the host AI services")
    start.add_argument("--mode", choices=AI_CAPABILITY_MODES, default="combined")
    _add_offline_option(start)
    _add_env_file_option(start)
    commands.add_parser("status", help="Show host AI process state and local URLs")
    validate = commands.add_parser(
        "validate", help="Capture a local MCP or RAG four-phase validation"
    )
    validate.add_argument("mode", choices=("mcp", "rag"))
    validate.add_argument("--output", type=Path, default=None)
    validate.add_argument("--query", default=None)
    validate.add_argument(
        "--corpus", default=None, help="Override the feature's registered corpus (RAG mode)"
    )
    validate.add_argument(
        "--feature", default=None, help="Feature key to validate; defaults to Feature 1"
    )
    validate.add_argument(
        "--tool",
        default=None,
        help="Registered tool to call (MCP mode); defaults to an "
        "argument-free read-only tool owned by the feature",
    )
    _add_env_file_option(validate)
    probe = commands.add_parser(
        "probe",
        help="Check the running MCP and RAG servers directly: auth, tools, corpora, retrieval",
    )
    probe.add_argument("--output", type=Path, default=None, help="Also write JSON evidence here")
    _add_env_file_option(probe)
    for action, help_text in (
        ("stop", "Stop host AI services while preserving their data"),
        ("logs", "Print recent host AI service logs"),
    ):
        command = commands.add_parser(action, help=help_text)
        command.add_argument("services", nargs="*", choices=tuple(AI_SERVICE_PORTS))
    foreground = commands.add_parser("serve", help="Run one host service in the foreground")
    foreground.add_argument("service", choices=tuple(AI_SERVICE_PORTS))


def build_parser() -> argparse.ArgumentParser:
    """Build the discoverable development command tree."""
    parser = argparse.ArgumentParser(
        description="Operate PropertyScope development stacks, UI fixtures, and source data."
    )
    parser.set_defaults(env_file=None)
    groups = parser.add_subparsers(dest="group", required=True)
    _stack_commands(groups)
    _ui_commands(groups)
    _data_commands(groups)
    _operator_commands(groups)
    _ai_commands(groups)
    return parser
