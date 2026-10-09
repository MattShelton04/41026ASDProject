"""Prove the public Feature 1 edge survives backend container recreation."""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from collections.abc import Callable, Sequence
from pathlib import Path

import httpx

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.devtools.config import COMPOSE_FILES, PROFILES, REPOSITORY_ROOT


def _compose(*arguments: str) -> tuple[str, ...]:
    command = ["docker", "compose"]
    for filename in COMPOSE_FILES:
        command.extend(("--file", filename))
    for profile in PROFILES:
        command.extend(("--profile", profile))
    command.extend(arguments)
    return tuple(command)


def _capture(command: Sequence[str]) -> str:
    return subprocess.run(  # noqa: S603 - argv built by this script, no shell
        command,
        cwd=REPOSITORY_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _run(command: Sequence[str]) -> None:
    subprocess.run(command, cwd=REPOSITORY_ROOT, check=True)  # noqa: S603 - argv built by this script, no shell


def _ready(url: str) -> bool:
    try:
        response = httpx.get(url, headers={"Accept": "application/json"}, timeout=5.0)
        payload = response.json()
    except (httpx.HTTPError, ValueError):
        return False
    return (
        response.status_code == 200
        and isinstance(payload, dict)
        and payload.get("http_status") == 200
    )


def validate_recreation(
    *,
    health_url: str,
    capture: Callable[[Sequence[str]], str] = _capture,
    run: Callable[[Sequence[str]], None] = _run,
    ready: Callable[[str], bool] = _ready,
    timeout_seconds: float = 90.0,
) -> tuple[str, str]:
    """Recreate only the backend and require the unchanged edge to recover."""
    if not ready(health_url):
        raise RuntimeError("port 5200 must be healthy before the backend recreation test")
    before = capture(_compose("ps", "--quiet", "f1-backend"))
    if not before:
        raise RuntimeError("f1-backend is not running")
    run((sys.executable, "scripts/dev.py", "stack", "rebuild", "f1-backend", "--offline"))
    after = capture(_compose("ps", "--quiet", "f1-backend"))
    if not after or after == before:
        raise RuntimeError("f1-backend container was not recreated")
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if ready(health_url):
            return before, after
        time.sleep(1)
    raise RuntimeError("port 5200 did not recover after f1-backend recreation")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--health-url", default="http://127.0.0.1:5200/health/ready")
    arguments = parser.parse_args()
    try:
        before, after = validate_recreation(health_url=arguments.health_url)
    except (RuntimeError, FileNotFoundError, subprocess.CalledProcessError) as exc:
        print(f"Nginx recreation validation failed: {exc}", file=sys.stderr)
        return 1
    print(f"Nginx recreation validation passed: {before[:12]} -> {after[:12]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
