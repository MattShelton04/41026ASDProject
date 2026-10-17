"""Validate the Docker images and Compose models a cloud deployment ships (R2-43).

``cloud-deployment.yml`` runs this in its *Docker build and validation* job, after building every
release image (``propertyscope/<service>:dev``, the same set ``deploy.sh push`` builds), and before
any Azure step. It checks that:

- the Compose model the VM runs is valid: ``docker-compose.yml``,
  ``deployment/enabled-features.compose.yml`` and ``docker-compose.azure.yml``, with and without
  the bonus ``docker-compose.azure-ai.yml`` overlay;
- every image the Azure overlay pins to ``${IMAGE_TAG}`` is one this repository builds;
- every built image exists locally and runs as a non-root user, recording its ID and size.

It writes ``image-build.json`` and ``image-build.md`` for the deployment evidence. Only the Docker
CLI is used, read-only (``config`` and ``image inspect``); nothing is pushed or started::

    python scripts/validate_release_images.py --sha <40-hex commit> --output-dir build/

Exit status: 0 when every check passed, 1 otherwise, 2 for invalid arguments.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
BUILD_JSON = "image-build.json"
BUILD_MARKDOWN = "image-build.md"
BASE_FILES = ("docker-compose.yml", "deployment/enabled-features.compose.yml")
AZURE_FILE = "docker-compose.azure.yml"
AZURE_AI_FILE = "docker-compose.azure-ai.yml"
PROFILE = "release-0"
COMMIT_SHA = re.compile(r"[0-9a-f]{40}")
BUILT_IMAGE = re.compile(r"^propertyscope/([a-z0-9][a-z0-9-]*):dev$", re.M)
AZURE_IMAGE = re.compile(r"/propertyscope/([a-z0-9][a-z0-9-]*):\$\{IMAGE_TAG\b")
# Placeholder values: config validation needs them set, never real ones.
PLACEHOLDER_ENVIRONMENT = {
    "ACR_LOGIN_SERVER": "validation.azurecr.io",
    "PROPERTYSCOPE_PUBLIC_HOST": "validation.invalid",
    "PROPERTYSCOPE_ACME_EMAIL": "operator@validation.invalid",
}

Runner = Callable[[Sequence[str], Mapping[str, str]], subprocess.CompletedProcess[str]]


def run_docker(
    arguments: Sequence[str], environment: Mapping[str, str]
) -> subprocess.CompletedProcess[str]:
    """Run one read-only docker command from the repository root."""
    return subprocess.run(  # noqa: S603 - fixed docker argv built by this script, no shell
        ["docker", *arguments],  # noqa: S607 - docker is resolved from PATH like in deploy.sh
        cwd=REPOSITORY_ROOT,
        env={**os.environ, **environment},
        check=False,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        timeout=300,
    )


def compose_arguments(*files: str) -> list[str]:
    arguments = ["compose", "--project-name", "propertyscope-validation"]
    for name in (*BASE_FILES, *files):
        arguments += ["-f", name]
    return [*arguments, "--profile", PROFILE]


def azure_services(text: str) -> list[str]:
    return sorted(set(AZURE_IMAGE.findall(text)))


def _last_line(result: subprocess.CompletedProcess[str]) -> str:
    lines = (result.stderr or result.stdout or "").strip().splitlines()
    return lines[-1][:300] if lines else f"exit status {result.returncode}"


def validate(
    sha: str, *, runner: Runner = run_docker, root: Path = REPOSITORY_ROOT
) -> dict[str, Any]:
    """Run every check and return the image-build document (without timestamps)."""
    environment = {**PLACEHOLDER_ENVIRONMENT, "IMAGE_TAG": sha}
    models: list[dict[str, Any]] = []
    for name, files in (("azure", (AZURE_FILE,)), ("azure-ai", (AZURE_FILE, AZURE_AI_FILE))):
        result = runner([*compose_arguments(*files), "config", "--quiet"], environment)
        models.append(
            {
                "name": name,
                "files": [*BASE_FILES, *files],
                "valid": result.returncode == 0,
                "detail": "" if result.returncode == 0 else _last_line(result),
            }
        )
    listed = runner([*compose_arguments(), "config", "--images"], environment)
    built = sorted(set(BUILT_IMAGE.findall(listed.stdout.replace("\r", ""))))
    if listed.returncode != 0:
        built = []
    azure_path = root / AZURE_FILE
    pinned = azure_services(azure_path.read_text(encoding="utf-8")) if azure_path.is_file() else []
    images: list[dict[str, Any]] = []
    missing: list[str] = []
    for service in built:
        image = f"propertyscope/{service}:dev"
        inspected = runner(["image", "inspect", image], {})
        try:
            details = json.loads(inspected.stdout)[0] if inspected.returncode == 0 else None
        except (json.JSONDecodeError, IndexError, KeyError):
            details = None
        if not isinstance(details, dict):
            missing.append(service)
            continue
        config = details.get("Config") if isinstance(details.get("Config"), dict) else {}
        user = str((config or {}).get("User") or "")
        images.append(
            {
                "service": service,
                "image": image,
                "id": str(details.get("Id", "")),
                "size_bytes": details.get("Size"),
                "user": user,
                "non_root": user.split(":", 1)[0] not in {"", "root", "0"},
                "created": details.get("Created"),
            }
        )
    unbuilt = [service for service in pinned if service not in built]
    root_images = [image["service"] for image in images if not image["non_root"]]
    passed = (
        all(model["valid"] for model in models)
        and bool(images)
        and bool(pinned)
        and not missing
        and not unbuilt
        and not root_images
    )
    return {
        "schema_version": 1,
        "tool": "scripts/validate_release_images.py",
        "commit_sha": sha,
        "passed": passed,
        "compose_models": models,
        "azure_services": pinned,
        "images": images,
        "missing_images": missing,
        "unbuilt_azure_services": unbuilt,
        "root_images": root_images,
    }


def render_markdown(document: Mapping[str, Any]) -> str:
    verdict = "PASSED" if document["passed"] else "FAILED"
    lines = [
        "## Docker build and validation",
        "",
        f"**{verdict}** for `{document['commit_sha']}`: {len(document['images'])} image(s) built; "
        f"{len(document['azure_services'])} pinned to `IMAGE_TAG` in `{AZURE_FILE}`.",
        "",
        "| Compose model | Valid | Detail |",
        "|---|---|---|",
    ]
    for model in document["compose_models"]:
        lines.append(
            f"| {model['name']} | {'yes' if model['valid'] else 'no'} | {model['detail']} |"
        )
    lines += ["", "| Service | Image ID | Size (MB) | User |", "|---|---|---|---|"]
    for image in document["images"]:
        size = image["size_bytes"]
        megabytes = f"{size / 1_000_000:.0f}" if isinstance(size, int) else "?"
        user = image["user"] or "root (not set)"
        lines.append(f"| {image['service']} | `{image['id'][7:19]}` | {megabytes} | {user} |")
    for key, label in (
        ("missing_images", "Built image not found"),
        ("unbuilt_azure_services", "Azure image this repository does not build"),
        ("root_images", "Image that runs as root"),
    ):
        if document[key]:
            lines += ["", f"{label}: {', '.join(document[key])}"]
    lines.append("")
    return "\n".join(lines)


def main(
    argv: Sequence[str] | None = None,
    *,
    runner: Runner = run_docker,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--sha", required=True, help="The 40-character commit being deployed")
    parser.add_argument("--output-dir", type=Path, required=True)
    arguments = parser.parse_args(argv)
    sha = str(arguments.sha).strip().lower()
    if not COMMIT_SHA.fullmatch(sha):
        print("--sha must be a full 40-character commit SHA", file=sys.stderr)
        return 2
    document = {**validate(sha, runner=runner), "checked_at": clock().isoformat(timespec="seconds")}
    arguments.output_dir.mkdir(parents=True, exist_ok=True)
    (arguments.output_dir / BUILD_JSON).write_text(
        json.dumps(document, indent=2) + "\n", encoding="utf-8"
    )
    (arguments.output_dir / BUILD_MARKDOWN).write_text(render_markdown(document), encoding="utf-8")
    print(
        f"Image validation {'PASSED' if document['passed'] else 'FAILED'}: "
        f"{len(document['images'])} image(s) for {sha}"
    )
    return 0 if document["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
