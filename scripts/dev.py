"""Cross-platform Docker Compose workflow for the local integration stack."""

from __future__ import annotations

import argparse
import shlex
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
COMPOSE_FILES = (
    "docker-compose.yml",
    "docker-compose.integration-test.yml",
    "docker-compose.dev.yml",
)
PROFILES = ("release-0", "ollama-container", "integration-test")
APPLICATION_SERVICES = (
    "ai-mode",
    "integration-test-feature-database",
    "integration-test-feature-backend",
    "integration-test-feature-frontend",
)


def _compose_command(*arguments: str) -> tuple[str, ...]:
    command = ["docker", "compose"]
    for filename in COMPOSE_FILES:
        command.extend(("--file", filename))
    for profile in PROFILES:
        command.extend(("--profile", profile))
    command.extend(arguments)
    return tuple(command)


def _run(command: Sequence[str]) -> None:
    print(f"> {shlex.join(command)}", flush=True)
    subprocess.run(command, cwd=REPOSITORY_ROOT, check=True)


def _ensure_docker() -> None:
    _run(("docker", "info", "--format", "Docker Engine {{.ServerVersion}} is ready"))


def _up(*, pull_model: bool) -> None:
    _ensure_docker()
    _run(_compose_command("up", "--detach", "--wait", "--wait-timeout", "120", "ollama"))
    if pull_model:
        _run(_compose_command("run", "--rm", "ollama-init"))
    _run(
        _compose_command(
            "up",
            "--detach",
            "--wait",
            "--wait-timeout",
            "180",
            *APPLICATION_SERVICES,
        )
    )
    print("\nIntegration console: http://localhost:5190")
    print("AI-mode health:     http://localhost:5005/health/ready")


def _rebuild(services: Sequence[str]) -> None:
    _ensure_docker()
    selected = tuple(services) or APPLICATION_SERVICES
    _run(_compose_command("build", *selected))
    _run(
        _compose_command(
            "up",
            "--detach",
            "--force-recreate",
            "--wait",
            "--wait-timeout",
            "180",
            *selected,
        )
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the assignment-aligned local stack with fast source reloads."
    )
    commands = parser.add_subparsers(dest="command", required=True)

    up = commands.add_parser("up", help="Start the complete development stack")
    up.add_argument(
        "--skip-model-pull",
        action="store_true",
        help="Skip the idempotent Ollama model preparation step",
    )

    rebuild = commands.add_parser(
        "rebuild",
        help="Rebuild images after dependency or Dockerfile changes",
    )
    rebuild.add_argument(
        "services",
        nargs="*",
        choices=APPLICATION_SERVICES,
        help="Optional application services to rebuild (all by default)",
    )

    commands.add_parser("restart", help="Recreate application containers without rebuilding")
    commands.add_parser("down", help="Stop containers while preserving durable volumes")
    commands.add_parser("status", help="Show current service and health state")
    commands.add_parser("config", help="Validate the merged Compose configuration")

    logs = commands.add_parser("logs", help="Follow recent application logs")
    logs.add_argument(
        "services",
        nargs="*",
        choices=("ollama", *APPLICATION_SERVICES),
        help="Optional services to follow (all application services by default)",
    )

    commands.add_parser("test", help="Run the deterministic integration-feature tests")
    commands.add_parser("check", help="Run the complete canonical quality gate")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Execute one documented development action."""
    arguments = _parser().parse_args(argv)
    try:
        if arguments.command == "up":
            _up(pull_model=not arguments.skip_model_pull)
        elif arguments.command == "rebuild":
            _rebuild(arguments.services)
        elif arguments.command == "restart":
            _ensure_docker()
            _run(
                _compose_command(
                    "up",
                    "--detach",
                    "--force-recreate",
                    "--wait",
                    "--wait-timeout",
                    "180",
                    *APPLICATION_SERVICES,
                )
            )
        elif arguments.command == "down":
            _ensure_docker()
            _run(_compose_command("down", "--remove-orphans"))
        elif arguments.command == "status":
            _ensure_docker()
            _run(_compose_command("ps"))
        elif arguments.command == "config":
            _ensure_docker()
            _run(_compose_command("config", "--quiet"))
        elif arguments.command == "logs":
            _ensure_docker()
            selected = tuple(arguments.services) or APPLICATION_SERVICES
            _run(_compose_command("logs", "--follow", "--tail", "200", *selected))
        elif arguments.command == "test":
            _run(
                (
                    sys.executable,
                    "-m",
                    "pytest",
                    "examples/integration-test-feature/tests",
                )
            )
        elif arguments.command == "check":
            _run((sys.executable, "scripts/check.py"))
    except FileNotFoundError:
        print(
            "Docker or uv is not available on PATH. See README.md for prerequisites.",
            file=sys.stderr,
        )
        return 1
    except subprocess.CalledProcessError as exc:
        print(f"Development command failed with exit code {exc.returncode}.", file=sys.stderr)
        return exc.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
