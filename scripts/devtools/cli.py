"""Grouped command-line interface for local stack, UI, and data workflows."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from scripts.devtools.ai_runtime import DOCKER_SERVICES
from scripts.devtools.config import (
    APPLICATION_SERVICES,
    BUILD_SERVICES,
    COLLECTION_JOBS,
    PRODUCTION_BUILD_SERVICES,
    PROPERTYSCOPE_API_URL,
    UI_FIXTURE_SCENARIOS,
)
from scripts.devtools.runtime_settings import AI_CAPABILITY_MODES, AI_PLACEMENTS


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
    stack = root.add_parser("stack", help="Build and operate Compose stacks")
    commands = stack.add_subparsers(dest="action", required=True)

    up = commands.add_parser("up", help="Start the reloadable development stack")
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
    up.add_argument(
        "--ai-runtime",
        choices=AI_PLACEMENTS,
        default=None,
        help="Select and remember AI placement; fresh setups default to Docker",
    )

    build = commands.add_parser(
        "build", help="Build production-like Release 0 images without starting containers"
    )
    build.add_argument(
        "services", nargs="*", choices=(*PRODUCTION_BUILD_SERVICES, *DOCKER_SERVICES)
    )

    rebuild = commands.add_parser(
        "rebuild", help="Rebuild and recreate changed development services"
    )
    rebuild.add_argument("services", nargs="*", choices=(*BUILD_SERVICES, *DOCKER_SERVICES))
    _add_offline_option(rebuild)
    _add_env_file_option(rebuild)

    restart = commands.add_parser(
        "restart", help="Recreate application containers without rebuilding images"
    )
    restart.add_argument("services", nargs="*", choices=(*APPLICATION_SERVICES, *DOCKER_SERVICES))
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

    logs = commands.add_parser("logs", help="Follow recent application logs")
    logs.add_argument("services", nargs="*", choices=(*APPLICATION_SERVICES, *DOCKER_SERVICES))


def _ui_commands(root: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    ui = root.add_parser("ui", help="Serve and audit deterministic browser fixtures")
    commands = ui.add_subparsers(dest="action", required=True)

    serve = commands.add_parser("serve", help="Serve Shared and Feature 1 fixtures without Docker")
    serve.add_argument("--port", type=int, default=None, help="Loopback port (default: 5300)")
    serve.add_argument(
        "--scenario",
        choices=UI_FIXTURE_SCENARIOS,
        default=os.environ.get("PROPERTYSCOPE_UI_SCENARIO", "populated"),
    )

    smoke = commands.add_parser("smoke", help="Run the minimal Playwright render smoke")
    smoke.add_argument("--port", type=int, default=None, help="Loopback port (default: 5300)")
    smoke.add_argument("--scenario", choices=UI_FIXTURE_SCENARIOS, default="populated")
    smoke.add_argument("--all-routes", action="store_true")

    screenshots = commands.add_parser(
        "readme-screenshots",
        help="Refresh the deterministic screenshots embedded in the root README",
    )
    screenshots.add_argument("--port", type=int, default=None, help="Loopback fixture port")
    screenshots.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Screenshot directory (default: docs/images/readme)",
    )

    audit = commands.add_parser("audit", help="Run a resumable browser interaction audit")
    audit.add_argument("profile", choices=("quick", "full"))
    audit.add_argument("--port", type=int, default=None, help="Loopback fixture port")
    audit.add_argument("--output", type=Path, default=None, help="Artifact directory")
    audit.add_argument("--resume", type=Path, default=None, help="Resume artifact directory")
    audit.add_argument("--workspace", action="append", default=[])
    audit.add_argument("--route-group", action="append", default=[])
    audit.add_argument("--route", action="append", default=[])
    audit.add_argument("--scenario", action="append", default=[])
    audit.add_argument("--viewport", action="append", default=[])
    audit.add_argument("--shard-index", type=int, default=0)
    audit.add_argument("--shard-total", type=int, default=1)
    audit.add_argument("--allow-destructive", action="store_true")


def _data_commands(root: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    data = root.add_parser("data", help="Acquire and operate Feature 1 source data")
    commands = data.add_subparsers(dest="action", required=True)

    collect = commands.add_parser(
        "collect", help="Plan, queue, and optionally wait for a registered acquisition"
    )
    collect.add_argument("job", choices=COLLECTION_JOBS)
    collect.add_argument("--wait", action=argparse.BooleanOptionalAction, default=True)
    collect.add_argument("--timeout", type=int, default=900)
    collect.add_argument("--base-url", default=PROPERTYSCOPE_API_URL)

    sync_psi = commands.add_parser(
        "sync-psi", help="Acquire official PSI archives into the read-only app cache"
    )
    sync_psi.add_argument("--all", action="store_true")
    sync_psi.add_argument("--year", type=int, action="append", default=[])
    sync_psi.add_argument("--week", action="append", default=[], metavar="YYYY-MM-DD")
    sync_psi.add_argument("--current-weekly", action="store_true")


def _operator_commands(root: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    operator = root.add_parser("operator", help="Inspect review and publication readiness")
    commands = operator.add_subparsers(dest="action", required=True)
    report = commands.add_parser("report", help="Print a read-only operational evidence report")
    report.add_argument("--base-url")
    report.add_argument("--feature-health-url")
    report.add_argument("--ai-health-url")


def _ai_commands(root: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    ai = root.add_parser("ai", help="Operate AI services in the selected runtime")
    commands = ai.add_subparsers(dest="action", required=True)
    start = commands.add_parser("start", help="Start AI services in the selected placement")
    start.add_argument("--mode", choices=AI_CAPABILITY_MODES, default="combined")
    _add_offline_option(start)
    _add_env_file_option(start)
    commands.add_parser("status", help="Show AI container or host process state")
    validate = commands.add_parser(
        "validate", help="Capture a local MCP or RAG four-phase validation"
    )
    validate.add_argument("mode", choices=("mcp", "rag"))
    validate.add_argument("--output", type=Path, default=None)
    validate.add_argument("--query", default=None)
    validate.add_argument("--corpus", default="operator-guidance")
    _add_env_file_option(validate)
    for action in ("stop", "logs"):
        command = commands.add_parser(
            action, help=f"{action.title()} AI services in the selected placement"
        )
        command.add_argument("services", nargs="*", choices=("ai-mode", "mcp", "rag"))
    foreground = commands.add_parser("serve", help="Run one service in the foreground")
    foreground.add_argument("service", choices=("ai-mode", "mcp", "rag"))


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
