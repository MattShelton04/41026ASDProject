"""Docker build validation for the cloud deployment, against a fake docker CLI."""

from __future__ import annotations

import json
import subprocess
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path

import pytest
from scripts import validate_release_images as module
from scripts.tests.cloud_fixtures import FakeDocker

SHA = "0123456789abcdef0123456789abcdef01234567"  # pragma: allowlist secret


def test_a_complete_build_passes_and_records_every_image(tmp_path: Path) -> None:
    docker = FakeDocker()

    status = module.main(
        ["--sha", SHA.upper(), "--output-dir", str(tmp_path)],
        runner=docker,
        clock=lambda: datetime(2026, 10, 20, 3, 5, tzinfo=UTC),
    )

    assert status == 0
    document = json.loads((tmp_path / "image-build.json").read_text(encoding="utf-8"))
    assert document["passed"] is True
    assert document["commit_sha"] == SHA
    assert document["checked_at"] == "2026-10-20T03:05:00+00:00"
    assert [model["name"] for model in document["compose_models"]] == ["azure", "azure-ai"]
    assert {image["service"] for image in document["images"]} == set(document["azure_services"])
    assert all(image["non_root"] for image in document["images"])
    # FakeDocker asserts placeholder Azure values; the second model adds the AI overlay.
    config_calls = [call for call in docker.calls if call[-1] == "--quiet"]
    assert config_calls[1][-6:-4] == ("-f", "docker-compose.azure-ai.yml")
    markdown = (tmp_path / "image-build.md").read_text(encoding="utf-8")
    assert "**PASSED**" in markdown and "| f1-backend |" in markdown


def test_root_images_invalid_models_and_unbuilt_azure_images_fail(tmp_path: Path) -> None:
    docker = FakeDocker(users={"f2-backend": "root"}, invalid="docker-compose.azure-ai.yml")
    docker.services = [name for name in docker.services if name != "f5-frontend"]

    status = module.main(["--sha", SHA, "--output-dir", str(tmp_path)], runner=docker)

    assert status == 1
    document = json.loads((tmp_path / "image-build.json").read_text(encoding="utf-8"))
    assert document["root_images"] == ["f2-backend"]
    assert document["unbuilt_azure_services"] == ["f5-frontend"]
    assert document["compose_models"][1] == {
        "name": "azure-ai",
        "files": [*module.BASE_FILES, module.AZURE_FILE, module.AZURE_AI_FILE],
        "valid": False,
        "detail": "service x: invalid",
    }
    markdown = (tmp_path / "image-build.md").read_text(encoding="utf-8")
    assert "Image that runs as root: f2-backend" in markdown


def test_an_image_that_was_not_built_is_reported_missing() -> None:
    docker = FakeDocker()

    def runner(
        arguments: Sequence[str], environment: Mapping[str, str]
    ) -> subprocess.CompletedProcess[str]:
        if tuple(arguments[:3]) == ("image", "inspect", "propertyscope/f3-backend:dev"):
            return subprocess.CompletedProcess(arguments, 1, "[]", "No such image")
        return docker(arguments, environment)

    document = module.validate(SHA, runner=runner)

    assert document["missing_images"] == ["f3-backend"]
    assert document["passed"] is False


def test_a_failed_image_listing_builds_nothing() -> None:
    def runner(
        arguments: Sequence[str], environment: Mapping[str, str]
    ) -> subprocess.CompletedProcess[str]:
        if arguments[-1] == "--images":
            return subprocess.CompletedProcess(arguments, 1, "", "compose: boom")
        return subprocess.CompletedProcess(arguments, 0, "", "")

    document = module.validate(SHA, runner=runner)

    assert document["images"] == [] and document["passed"] is False


def test_invalid_sha_is_rejected(tmp_path: Path) -> None:
    def runner(
        arguments: Sequence[str], environment: Mapping[str, str]
    ) -> subprocess.CompletedProcess[str]:
        raise AssertionError("must not call docker")

    assert module.main(["--sha", "abc", "--output-dir", str(tmp_path)], runner=runner) == 2


def test_run_docker_passes_the_environment_and_never_raises_on_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, object] = {}

    def fake_run(arguments: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        seen.update(arguments=arguments, **kwargs)
        return subprocess.CompletedProcess(arguments, 3, "", "")

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = module.run_docker(["compose", "config"], {"IMAGE_TAG": SHA})

    assert result.returncode == 3
    assert seen["arguments"] == ["docker", "compose", "config"]
    environment = seen["env"]
    assert isinstance(environment, dict) and environment["IMAGE_TAG"] == SHA
    assert seen["check"] is False
