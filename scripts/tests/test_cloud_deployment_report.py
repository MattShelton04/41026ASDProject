"""Cloud deployment report built from recorded deployment logs."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from scripts import cloud_deployment_report as report

VM_LOG = """[stdout]
[10:00:01] Pulling abc images
PROPERTYSCOPE_RESULT={"action":"deploy","image_tag":"abc123","cloud_ai":"false","containers_running":20,"containers_total":20,"ai_units":{"ai-mode":"inactive","mcp":"inactive"}}
PROPERTYSCOPE_EXIT=0
"""


def _smoke(passed: bool) -> dict[str, object]:
    return {
        "base_url": "https://demo.australiaeast.cloudapp.azure.com",
        "passed": passed,
        "summary": {
            "total": 2,
            "passed": 2 if passed else 1,
            "failed": 0 if passed else 1,
            "by_owner": {"shared": {"passed": 1, "failed": 0}},
        },
        "checks": [
            {"name": "Shared home page", "owner": "shared", "category": "frontend",
             "passed": True, "detail": "HTTP 200 text/html"},
            {"name": "AI tier disabled by default", "owner": "shared", "category": "ai",
             "passed": passed, "detail": "disabled: HTTP 503, code ai_disabled"},
        ],
    }  # fmt: skip


def _log_dir(tmp_path: Path, *, smoke_passed: bool = True) -> Path:
    log_dir = tmp_path / "cloud"
    (log_dir / "smoke").mkdir(parents=True)
    (log_dir / "outputs.txt").write_text(
        "resource_group=rg-propertyscope-prod\nfqdn=demo.australiaeast.cloudapp.azure.com\n"
        "public_url=https://demo.australiaeast.cloudapp.azure.com\n",
        encoding="utf-8",
    )
    (log_dir / "image-tag.txt").write_text("abc123\n", encoding="utf-8")
    (log_dir / "vm-deploy.log").write_text(VM_LOG, encoding="utf-8")
    (log_dir / "vm-deploy.payload.sh").write_text("secret-free but noisy", encoding="utf-8")
    (log_dir / "smoke" / "cloud-smoke.json").write_text(
        json.dumps(_smoke(smoke_passed)), encoding="utf-8"
    )
    (log_dir / "endpoint-security.txt").write_text(
        "Endpoint security validation\nPASS HTTP permanently redirects to HTTPS (308)\n"
        "FAIL port 22 is reachable from the internet\nENDPOINT_SECURITY_FAILURES=1\n",
        encoding="utf-8",
    )
    return log_dir


GITHUB = {
    "GITHUB_SERVER_URL": "https://github.com",
    "GITHUB_REPOSITORY": "owner/repo",
    "GITHUB_RUN_ID": "42",
    "GITHUB_EVENT_NAME": "workflow_run",
    "GITHUB_ACTOR": "deployer",
    "PROPERTYSCOPE_DEPLOY_SHA": "abc123",
    "PROPERTYSCOPE_CI_RUN_URL": "https://github.com/owner/repo/actions/runs/41",
}
SUCCESS = {"provision": "success", "push": "success", "deploy": "success", "smoke": "success"}


def test_successful_deployment_report(tmp_path: Path) -> None:
    evidence = report.collect(_log_dir(tmp_path), stages=SUCCESS, environment=GITHUB)
    markdown = report.render(evidence)

    assert evidence.verdict == "SUCCEEDED"
    assert evidence.vm_result is not None and evidence.vm_result["containers_running"] == 20
    assert "| Result | **SUCCEEDED** |" in markdown
    assert "https://github.com/owner/repo/actions/runs/42" in markdown
    assert "https://github.com/owner/repo/actions/runs/41" in markdown
    assert "Containers running: 20 of 20" in markdown
    assert "flag off (PROPERTYSCOPE_CLOUD_AI), edge reports disabled" in markdown
    assert "| FAIL | port 22 is reachable from the internet |" in markdown
    assert "release-decision.md" in markdown
    assert "vm-deploy.payload.sh" not in evidence.evidence_files


@pytest.mark.parametrize(
    ("stages", "smoke_passed"),
    [
        ({**SUCCESS, "deploy": "failure"}, True),
        ({**SUCCESS, "provision": "failure"}, True),
        (SUCCESS, False),
        ({}, True),
    ],
)
def test_any_failed_required_stage_or_smoke_fails_the_report(
    tmp_path: Path, stages: dict[str, str], smoke_passed: bool
) -> None:
    evidence = report.collect(
        _log_dir(tmp_path, smoke_passed=smoke_passed), stages=stages, environment={}
    )
    assert evidence.verdict == "FAILED"


def test_missing_logs_still_produce_a_report(tmp_path: Path) -> None:
    evidence = report.collect(tmp_path, stages={}, environment={})
    markdown = report.render(evidence)

    assert "No Bicep outputs were recorded." in markdown
    assert "No smoke-test results were recorded." in markdown
    assert "local run (no GitHub Actions run)" in markdown


def test_main_writes_markdown_and_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for key, value in GITHUB.items():
        monkeypatch.setenv(key, value)
    output = tmp_path / "report"
    arguments = ["--log-dir", str(_log_dir(tmp_path)), "--output-dir", str(output)]
    for stage, outcome in SUCCESS.items():
        arguments += ["--stage", f"{stage}={outcome}"]

    assert report.main(arguments) == 0

    document = json.loads((output / "cloud-deployment-report.json").read_text(encoding="utf-8"))
    assert document["verdict"] == "SUCCEEDED"
    assert document["image_tag"] == "abc123"
    assert (
        (output / "cloud-deployment-report.md")
        .read_text(encoding="utf-8")
        .startswith("# Cloud deployment report")
    )


def test_unknown_stage_is_rejected(tmp_path: Path) -> None:
    assert report.main(["--log-dir", str(tmp_path), "--stage", "launch=success"]) == 2


def test_vm_result_parser_ignores_malformed_lines() -> None:
    assert report.parse_vm_result("PROPERTYSCOPE_RESULT={broken\n") is None
    assert report.parse_vm_result(VM_LOG) == json.loads(VM_LOG.splitlines()[2].split("=", 1)[1])


def test_release_gate_section_comes_from_the_gate_record(tmp_path: Path) -> None:
    from scripts.tests import cloud_fixtures

    sha = "3f2a9c1d8e7b6a5f4e3d2c1b0a9f8e7d6c5b4a39"
    log_dir = _log_dir(tmp_path)
    (log_dir / "gate").mkdir()
    gate = cloud_fixtures.release_gate_document(sha=sha, repository="owner/repo")
    (log_dir / "gate" / "release-gate.json").write_text(json.dumps(gate), encoding="utf-8")

    evidence = report.collect(log_dir, stages=SUCCESS, environment=GITHUB)
    markdown = report.render(evidence)

    assert f"| Release gate | PASSED for `{sha[:12]}` |" in markdown
    assert "## Release gate" in markdown
    assert f"**PASSED** for `{sha}` on `main`" in markdown
    for name in ("Integration CI", *(f"Student {n} CI" for n in range(1, 6))):
        assert f"| {name} | success |" in markdown, name
    summary = evidence.as_json()["release_gate"]
    assert summary["passed"] is True and summary["file"] == "gate/release-gate.json"
    assert len(summary["workflows"]) == 6


def test_a_failed_or_missing_release_gate_is_stated(tmp_path: Path) -> None:
    log_dir = _log_dir(tmp_path)
    markdown = report.render(report.collect(log_dir, stages=SUCCESS, environment={}))
    assert "| Release gate | not recorded |" in markdown
    assert "No release-gate record was found" in markdown

    (log_dir / "release-gate.json").write_text(
        json.dumps({"passed": False, "deploy_sha": "abc", "workflows": []}), encoding="utf-8"
    )
    evidence = report.collect(log_dir, stages=SUCCESS, environment={})
    markdown = report.render(evidence)
    assert "| Release gate | FAILED for `abc` |" in markdown
    assert "The record lists no workflows." in markdown


def test_vm_images_and_a_notice_are_reported(tmp_path: Path) -> None:
    log_dir = _log_dir(tmp_path)
    image = "reg/propertyscope/f1-backend:abc123@sha256:" + "a" * 64
    (log_dir / "vm-deploy.log").write_text(
        f'PROPERTYSCOPE_IMAGES={{"f1-backend":"{image}"}}\n' + VM_LOG, encoding="utf-8"
    )
    evidence = report.collect(log_dir, stages=SUCCESS, environment={})
    evidence.notice = "LOCAL REHEARSAL - not Azure."
    markdown = report.render(evidence)
    assert markdown.splitlines()[2] == "**LOCAL REHEARSAL - not Azure.**"
    assert f"| f1-backend | `{image}` |" in markdown
    assert evidence.as_json()["vm_images"] == {"f1-backend": image}
    assert report.parse_vm_images('PROPERTYSCOPE_IMAGES={"cut":\n') == {}


def test_a_skipped_provision_still_counts_as_a_successful_redeploy(tmp_path: Path) -> None:
    stages = {**SUCCESS, "provision": "skipped"}
    evidence = report.collect(_log_dir(tmp_path), stages=stages, environment={})
    assert evidence.verdict == "SUCCEEDED"
