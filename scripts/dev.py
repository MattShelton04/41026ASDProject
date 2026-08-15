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
FULL_DATA_COMPOSE_FILE = "docker-compose.full-data.yml"
GPU_COMPOSE_FILE = "docker-compose.gpu.yml"
PROFILES = ("release-0", "ollama-container", "integration-test")
APPLICATION_SERVICES = (
    "propertyscope-shared-frontend",
    "ai-mode",
    "integration-test-feature-database",
    "integration-test-feature-backend",
    "integration-test-feature-frontend",
    "propertyscope-database-api",
    "propertyscope-database-loader",
    "propertyscope-backend",
    "propertyscope-runner",
    "propertyscope-frontend",
)
BUILD_SERVICES = APPLICATION_SERVICES
FULL_DATA_PROJECT_NAME = "41026-asd-propertyscope-full-data"


def _compose_command(
    *arguments: str, full_data: bool = False, gpu: bool = False
) -> tuple[str, ...]:
    command = ["docker", "compose"]
    if full_data:
        command.extend(("--project-name", FULL_DATA_PROJECT_NAME))
    for filename in COMPOSE_FILES:
        command.extend(("--file", filename))
    if full_data:
        command.extend(("--file", FULL_DATA_COMPOSE_FILE))
    if gpu:
        command.extend(("--file", GPU_COMPOSE_FILE))
    profiles = (*PROFILES, "full-data") if full_data else PROFILES
    for profile in profiles:
        command.extend(("--profile", profile))
    command.extend(arguments)
    return tuple(command)


def _run(command: Sequence[str]) -> None:
    print(f"> {shlex.join(command)}", flush=True)
    subprocess.run(command, cwd=REPOSITORY_ROOT, check=True)


def _ensure_docker() -> None:
    _run(("docker", "info", "--format", "Docker Engine {{.ServerVersion}} is ready"))


def _nvidia_runtime_available() -> bool:
    """Return whether this Docker daemon advertises the NVIDIA runtime."""
    try:
        completed = subprocess.run(
            ("docker", "info", "--format", "{{json .Runtimes}}"),
            cwd=REPOSITORY_ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return False
    return '"nvidia"' in completed.stdout.lower()


def _up(*, pull_model: bool, full_data: bool, cpu_only: bool, require_gpu: bool) -> None:
    _ensure_docker()
    nvidia_available = _nvidia_runtime_available()
    if require_gpu and not nvidia_available:
        raise RuntimeError(
            "--gpu was requested, but Docker does not advertise the NVIDIA runtime. "
            "Use --cpu-only or repair Docker GPU support."
        )
    gpu = not cpu_only and nvidia_available
    print(f"Ollama acceleration: {'NVIDIA GPU' if gpu else 'CPU'}", flush=True)
    _run(
        _compose_command(
            "up",
            "--detach",
            "--wait",
            "--wait-timeout",
            "120",
            "ollama",
            full_data=full_data,
            gpu=gpu,
        )
    )
    if pull_model:
        _run(_compose_command("run", "--rm", "ollama-init", full_data=full_data, gpu=gpu))
    _run(
        _compose_command(
            "up",
            "--detach",
            "--wait",
            "--wait-timeout",
            "180",
            *APPLICATION_SERVICES,
            full_data=full_data,
            gpu=gpu,
        )
    )
    print("\nIntegration console: http://localhost:5190")
    print("AI-mode health:     http://localhost:5005/health/ready")
    print("PropertyScope home: http://localhost:5100")
    print("PropertyScope:      http://localhost:5200")
    if full_data:
        print("Full-data mode:     enabled in an isolated Compose project")


def _rebuild(services: Sequence[str], *, full_data: bool) -> None:
    _ensure_docker()
    selected = tuple(services) or APPLICATION_SERVICES
    _run(_compose_command("build", *selected, full_data=full_data))
    _run(
        _compose_command(
            "up",
            "--detach",
            "--force-recreate",
            "--wait",
            "--wait-timeout",
            "180",
            *selected,
            full_data=full_data,
        )
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the assignment-aligned local stack with fast source reloads."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    parser.set_defaults(full_data=False)

    def add_full_data_option(command: argparse.ArgumentParser) -> None:
        command.add_argument(
            "--full-data",
            action="store_true",
            help="Use the isolated, opt-in source-scale PropertyScope profile",
        )

    up = commands.add_parser("up", help="Start the complete development stack")
    up.add_argument(
        "--skip-model-pull",
        action="store_true",
        help="Skip the idempotent Ollama model preparation step",
    )
    acceleration = up.add_mutually_exclusive_group()
    acceleration.add_argument(
        "--cpu-only",
        action="store_true",
        help="Disable automatic NVIDIA acceleration for Ollama",
    )
    acceleration.add_argument(
        "--gpu",
        action="store_true",
        help="Require NVIDIA acceleration and fail if Docker cannot provide it",
    )
    add_full_data_option(up)

    rebuild = commands.add_parser(
        "rebuild",
        help="Rebuild images after dependency or Dockerfile changes",
    )
    rebuild.add_argument(
        "services",
        nargs="*",
        choices=BUILD_SERVICES,
        help="Optional application services to rebuild (all by default)",
    )
    add_full_data_option(rebuild)

    restart = commands.add_parser(
        "restart", help="Recreate application containers without rebuilding"
    )
    add_full_data_option(restart)
    down = commands.add_parser("down", help="Stop containers while preserving durable volumes")
    add_full_data_option(down)
    status = commands.add_parser("status", help="Show current service and health state")
    add_full_data_option(status)
    config_command = commands.add_parser("config", help="Validate the merged Compose configuration")
    add_full_data_option(config_command)

    logs = commands.add_parser("logs", help="Follow recent application logs")
    logs.add_argument(
        "services",
        nargs="*",
        choices=("ollama", *APPLICATION_SERVICES),
        help="Optional services to follow (all application services by default)",
    )
    add_full_data_option(logs)

    commands.add_parser("test", help="Run the deterministic integration-feature tests")
    commands.add_parser("check", help="Run the complete canonical quality gate")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Execute one documented development action."""
    arguments = _parser().parse_args(argv)
    try:
        if arguments.command == "up":
            _up(
                pull_model=not arguments.skip_model_pull,
                full_data=arguments.full_data,
                cpu_only=arguments.cpu_only,
                require_gpu=arguments.gpu,
            )
        elif arguments.command == "rebuild":
            _rebuild(arguments.services, full_data=arguments.full_data)
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
                    full_data=arguments.full_data,
                )
            )
        elif arguments.command == "down":
            _ensure_docker()
            _run(_compose_command("down", "--remove-orphans", full_data=arguments.full_data))
        elif arguments.command == "status":
            _ensure_docker()
            _run(_compose_command("ps", full_data=arguments.full_data))
        elif arguments.command == "config":
            _ensure_docker()
            _run(_compose_command("config", "--quiet", full_data=arguments.full_data))
        elif arguments.command == "logs":
            _ensure_docker()
            selected = tuple(arguments.services) or APPLICATION_SERVICES
            _run(
                _compose_command(
                    "logs",
                    "--follow",
                    "--tail",
                    "200",
                    *selected,
                    full_data=arguments.full_data,
                )
            )
        elif arguments.command == "test":
            _run(
                (
                    sys.executable,
                    "-m",
                    "pytest",
                    "examples/integration-test-feature/tests",
                    "student-1/tests",
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
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
