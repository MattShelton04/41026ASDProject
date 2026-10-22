"""`dev.py cloud rehearse`: the pure parts of the local Azure rehearsal (no Docker, no Azure)."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
import yaml
from scripts import dev
from scripts.devtools import cloud_rehearsal as rehearsal
from scripts.devtools.cli import build_parser
from scripts.devtools.config import REPOSITORY_ROOT
from scripts.devtools.review.workflow import run_review
from scripts.tests import cloud_fixtures

COMMIT = "3f2a9c1d8e7b6a5f4e3d2c1b0a9f8e7d6c5b4a39"
REHEARSAL = REPOSITORY_ROOT / "deployment" / "azure" / "rehearsal"


def test_the_vm_gets_cloud_inits_docker_daemon_plus_the_plain_http_registry() -> None:
    cloud_init = (REPOSITORY_ROOT / "deployment" / "azure" / "cloud-init.yaml").read_text(
        encoding="utf-8"
    )
    configuration = rehearsal.daemon_configuration(
        cloud_init, insecure_registry=rehearsal.VM_REGISTRY
    )
    assert configuration["insecure-registries"] == ["ps-rehearsal-registry:5000"]
    # The production settings are carried over unchanged.
    assert configuration["userland-proxy"] is False
    assert configuration["no-new-privileges"] is True
    assert configuration["log-driver"] == "json-file"
    with pytest.raises(ValueError, match=r"daemon\.json"):
        rehearsal.daemon_configuration("write_files: []\n", insecure_registry="x:5000")


def test_key_vault_stand_in_holds_a_random_value_for_every_secret(tmp_path: Path) -> None:
    rehearsal.write_key_vault(tmp_path / "kv")
    rehearsal.write_key_vault(tmp_path / "other")
    names = sorted(path.name for path in (tmp_path / "kv").iterdir())
    assert names == sorted(rehearsal.KEY_VAULT_SECRETS)
    deploy = (REPOSITORY_ROOT / "deployment" / "azure" / "deploy.sh").read_text(encoding="utf-8")
    for name in rehearsal.KEY_VAULT_SECRETS:  # the same names deploy.sh secrets creates
        assert name in deploy
        value = (tmp_path / "kv" / name).read_text(encoding="ascii")
        assert re.fullmatch(r"[0-9a-f]{64}", value)
        assert value != (tmp_path / "other" / name).read_text(encoding="ascii")


def test_deploy_environment_targets_the_stand_ins_and_drops_azure_settings(
    tmp_path: Path,
) -> None:
    run = rehearsal.Rehearsal(output=tmp_path, commit=COMMIT, image_tag=f"{COMMIT}-dirty")
    environment = rehearsal.deploy_environment(
        run,
        {
            "PATH": "/usr/bin",
            "AZURE_SUBSCRIPTION_ID": "real-subscription",
            "ARM_CLIENT_ID": "x",
            "ACR_LOGIN_SERVER": "real.azurecr.io",
            "PROPERTYSCOPE_PUBLIC_URL": "https://real.example",
            "IMAGE_TAG": "stale",
        },
        EDGE_PASSWORD="from-the-stand-in",  # pragma: allowlist secret
    )
    assert environment["PATH"] == "/usr/bin"
    assert not any(key.startswith(("AZURE_", "ARM_")) for key in environment)
    assert "PROPERTYSCOPE_PUBLIC_URL" not in environment
    assert environment["PROPERTYSCOPE_REHEARSAL"] == "true"
    assert environment["PROPERTYSCOPE_REHEARSAL_VM"] == "ps-azure-rehearsal-vm"
    assert environment["PROPERTYSCOPE_PUSH_REGISTRY"] == "127.0.0.1:5000"
    assert environment["ACR_LOGIN_SERVER"] == "ps-rehearsal-registry:5000"
    assert environment["PUBLIC_FQDN"] == environment["PROPERTYSCOPE_PUBLIC_HOST"] == "localhost"
    assert environment["PROPERTYSCOPE_CLOUD_AI"] == "false"
    assert environment["PROPERTYSCOPE_BUILD_TAG"] == "rehearsal"  # never the shared :dev tag
    assert environment["IMAGE_TAG"] == f"{COMMIT}-dirty"
    assert environment["PROPERTYSCOPE_DEPLOY_SHA"] == COMMIT
    assert environment["PROPERTYSCOPE_CLOUD_LOG_DIR"] == (tmp_path / "cloud").as_posix()
    assert environment["EDGE_PASSWORD"] == "from-the-stand-in"  # pragma: allowlist secret


def test_only_the_untrusted_local_certificate_is_an_expected_endpoint_failure() -> None:
    results = rehearsal.parse_validation(
        "Endpoint security validation for https://localhost\n"
        "FAIL HTTPS certificate is not trusted (or the edge is down) for localhost\n"
        "PASS HTTP permanently redirects to HTTPS (308 https://localhost/features/data-platform/)\n"
        "FAIL anonymous /api/data-platform/v1/release-reviews requires operator credentials "
        "(got: 200)\n"
        "SKIP NSG rules (needs az and AZURE_RESOURCE_GROUP)\n"
        "ENDPOINT_SECURITY_FAILURES=2\n"
    )
    unexpected, expected = rehearsal.split_endpoint_results(results)
    assert expected == ["HTTPS certificate is not trusted (or the edge is down) for localhost"]
    assert unexpected == [
        "anonymous /api/data-platform/v1/release-reviews requires operator credentials (got: 200)"
    ]


def test_a_port_open_only_on_this_machine_is_not_held_against_the_deployment() -> None:
    script = rehearsal.ENDPOINT_SCRIPT.read_text(encoding="utf-8")
    ports = rehearsal.closed_port_list(script)
    assert {22, 2375, 5005, 5013, 5432, 8080} <= set(ports)
    probe = rehearsal.parse_port_probe("OPEN 80\nOPEN 443\nCLOSED 5432\nCLOSED 22\nnoise\n")
    assert probe == {80: True, 443: True, 5432: False, 22: False}
    results = [
        ("FAIL", "port 5432 is reachable from the internet"),
        ("FAIL", "port 5013 is reachable from the internet"),
    ]
    unexpected, expected = rehearsal.split_endpoint_results(results, vm_closed_ports=[5432])
    assert unexpected == ["port 5013 is reachable from the internet"]
    assert expected[0].startswith("port 5432 is reachable from the internet: a process on this")
    with pytest.raises(ValueError):
        rehearsal.closed_port_list("echo no loop\n")


def _overlay_model() -> dict[str, Any]:
    # Compose secret names, not values.
    secret_env = " ".join(
        (
            "PROPERTYSCOPE_INTERNAL_TOKEN=internal_token",  # pragma: allowlist secret
            "AI_MODE_SERVICE_TOKEN=ai_mode_service_token",  # pragma: allowlist secret
            "MULTI_AGENT_SERVICE_TOKEN=multi_agent_service_token",  # pragma: allowlist secret
        )
    )
    backend = {
        "secrets": [{"source": "ai_mode_service_token"}, {"source": "multi_agent_service_token"}],
        "environment": {
            "PROPERTYSCOPE_SECRET_ENV": secret_env,
            "MULTI_AGENT_BASE_URL": "http://host.docker.internal:5013",
            "MULTI_AGENT_SERVICE_TOKEN": "",
        },
    }
    return {
        "services": {
            **{name: json.loads(json.dumps(backend)) for name in rehearsal.MULTI_AGENT_BACKENDS},
        },
        "secrets": {
            "multi_agent_service_token": {
                "file": "/opt/propertyscope/secrets/multi-agent-service-token"
            },
            "ai_mode_service_token": {"file": "/opt/propertyscope/secrets/ai-mode-service-token"},
        },
    }


def test_ai_overlay_findings_accept_the_secret_wiring_and_catch_a_leaked_token() -> None:
    model = _overlay_model()
    findings = rehearsal.ai_overlay_findings(model)
    assert findings and all(verdict == "PASS" for verdict, _ in findings), findings

    model["services"]["f2-backend"]["secrets"] = [{"source": "ai_mode_service_token"}]
    model["services"]["f4-backend"]["environment"]["MULTI_AGENT_SERVICE_TOKEN"] = "a" * 64
    model["services"]["f3-backend"]["secrets"] = [{"source": "ai_mode_service_token"}]
    failed = [
        detail for verdict, detail in rehearsal.ai_overlay_findings(model) if verdict == "FAIL"
    ]
    assert failed == [
        "f2-backend gets multi_agent_service_token as a Compose secret",
        "f3-backend gets multi_agent_service_token as a Compose secret",
        "f4-backend has no Multi-Agent token value in its environment",
    ]


def test_ai_overlay_findings_on_the_real_overlay_files() -> None:
    """Merge the overlay files the way Compose does for the keys the findings read."""
    base = yaml.load(
        (REPOSITORY_ROOT / "docker-compose.azure-ai.yml").read_text(encoding="utf-8"),
        Loader=_ComposeLoader,  # noqa: S506 - a SafeLoader subclass that tolerates Compose tags
    )
    model: dict[str, Any] = {"services": {}, "secrets": base["secrets"]}
    for name, service in base["services"].items():
        secrets = [{"source": item} for item in service.get("secrets", [])]
        model["services"][name] = {
            "secrets": secrets,
            "environment": service.get("environment", {}),
        }
    findings = rehearsal.ai_overlay_findings(model)
    assert all(verdict == "PASS" for verdict, _ in findings), findings


class _ComposeLoader(yaml.SafeLoader):
    """Reads Compose files (merge keys and !reset/!override tags) as plain YAML."""


_ComposeLoader.add_multi_constructor(
    "!",
    lambda loader, _suffix, node: loader.construct_object(node),  # type: ignore[no-untyped-call]
)


def _rehearsal_tree(tmp_path: Path) -> rehearsal.Rehearsal:
    """What a successful rehearsal leaves in its cloud/ log directory."""
    run = rehearsal.Rehearsal(output=tmp_path / "out", commit=COMMIT, image_tag=COMMIT)
    cloud = run.cloud_dir
    (cloud / "smoke").mkdir(parents=True)
    (cloud / "report").mkdir()
    run.logs_dir.mkdir()
    document = cloud_fixtures.smoke_document(
        base_url="https://localhost", commit_sha=COMMIT, registry=rehearsal.VM_REGISTRY
    )
    (cloud / "smoke" / "cloud-smoke.json").write_text(json.dumps(document), encoding="utf-8")
    (cloud / "report" / "cloud-deployment-report.md").write_text(
        f"# Cloud deployment report\n\n| Public URL | https://localhost |\n"
        f"| Commit / image tag | `{COMMIT}` / `{COMMIT}` |\n",
        encoding="utf-8",
    )
    (cloud / "vm-deploy.log").write_text("PROPERTYSCOPE_EXIT=0\n", encoding="utf-8")
    (cloud / "outputs.txt").write_text(rehearsal.outputs_text(), encoding="utf-8")
    (cloud / "vm-deploy.payload.sh").write_text("never copied", encoding="utf-8")
    (run.logs_dir / "deploy.log").write_text("[deploy.sh 01:00:00] Deployed\n", encoding="utf-8")
    (run.output / "key-vault").mkdir()
    (run.output / "key-vault" / "internal-token").write_text("0" * 64, encoding="ascii")
    return run


def test_the_evidence_tree_is_laid_out_like_the_workflow_artifacts(tmp_path: Path) -> None:
    run = _rehearsal_tree(tmp_path)
    copied = rehearsal.build_evidence_tree(run)
    assert "cloud/cloud-deployment-report.md" in copied
    assert "cloud/smoke/cloud-smoke.json" in copied
    assert "cloud/logs/deploy.log" in copied
    assert "cloud/vm-deploy.log" in copied
    files = {path.relative_to(run.evidence_dir).as_posix() for path in run.evidence_dir.rglob("*")}
    assert not any("payload" in name or "key-vault" in name for name in files)
    # It is a scratch tree, never the committed evidence the cloud review reads by default.
    assert not run.evidence_dir.is_relative_to(REPOSITORY_ROOT / "docs")


def test_the_cloud_review_on_rehearsal_evidence_misses_only_what_cannot_exist_locally(
    tmp_path: Path,
) -> None:
    run = _rehearsal_tree(tmp_path)
    rehearsal.build_evidence_tree(run)
    result = run_review(
        "cloud", evidence_dir=run.evidence_dir, out_dir=tmp_path / "review", deterministic=True
    )
    checks = [check.model_dump(mode="json") for check in result.record.bundle.checks]
    status = {check["id"]: check["status"] for check in checks}
    for passing in (
        "cloud.report",
        "cloud.smoke-output",
        "cloud.smoke",
        "cloud.frontend",
        "cloud.ai-disabled",
        "cloud.images",
        "cloud.commit-consistency",
        "cloud.https",
        *(f"cloud.crud.student-{number}" for number in range(1, 6)),
    ):
        assert status[passing] == "passed", (passing, status)
    unexpected, expected = rehearsal.review_outcome(checks)
    assert unexpected == []
    assert expected == ["cloud.release-gate"]  # cloud.build is advisory
    assert result.record.verdict.value == "fail"  # the release gate is required
    assert (tmp_path / "review" / "cloud-review.md").is_file()


def test_the_review_cli_reads_an_alternate_evidence_root(tmp_path: Path) -> None:
    run = _rehearsal_tree(tmp_path)
    rehearsal.build_evidence_tree(run)
    out = tmp_path / "cli-review"
    status = dev.main(
        [
            "ai",
            "review",
            "cloud",
            "--deterministic",
            "--evidence-dir",
            str(run.evidence_dir),
            "--out",
            str(out),
        ]
    )
    assert status == 1  # the gate is missing, so the review fails as it should
    report = (out / "cloud-review.md").read_text(encoding="utf-8")
    assert "cloud.release-gate" in report


def test_summary_names_the_rehearsal_and_lists_gaps_and_problems(tmp_path: Path) -> None:
    run = rehearsal.Rehearsal(output=tmp_path, commit=COMMIT, image_tag=COMMIT)
    run.stage("push").outcome = "success"
    run.stage("smoke").outcome, run.stage("smoke").detail = "failure", "1|2 checks"
    run.results.update(
        {"verdict": "FAILED", "problems": ["smoke: failure"], "expected_gaps": ["gate"]}
    )
    text = rehearsal.render_summary(run)
    assert "NOT the Azure deployment" in text
    assert "| smoke | failure | 1\\|2 checks |" in text
    assert "- gate" in text and "- smoke: failure" in text


def test_output_must_stay_in_the_git_ignored_runtime_store(tmp_path: Path) -> None:
    arguments = build_parser().parse_args(["cloud", "rehearse", "--output-dir", str(tmp_path)])
    with pytest.raises(RuntimeError, match=r"\.propertyscope-runtime"):
        rehearsal.run(arguments, bash="bash")


def test_cli_options() -> None:
    arguments = build_parser().parse_args(["cloud", "rehearse", "--keep", "--reuse-images"])
    assert arguments.action == "rehearse"
    assert arguments.keep and arguments.reuse_images and not arguments.keep_images
    assert arguments.output_dir == rehearsal.DEFAULT_OUTPUT


def test_rehearsal_infrastructure_is_isolated_and_loopback_only() -> None:
    compose = yaml.safe_load((REHEARSAL / "compose.yml").read_text(encoding="utf-8"))
    assert compose["name"] == rehearsal.PROJECT == "ps-azure-rehearsal"
    services = compose["services"]
    assert services["registry"]["container_name"] == rehearsal.REGISTRY_CONTAINER
    assert services["vm"]["container_name"] == rehearsal.VM_CONTAINER
    for service in services.values():
        for port in service.get("ports", []):
            assert str(port).startswith("127.0.0.1:"), port
    assert sorted(services["vm"]["ports"]) == ["127.0.0.1:443:443", "127.0.0.1:80:80"]
    # Unix socket only: no Docker API port, like the Azure VM.
    assert services["vm"]["command"] == ["dockerd", "--host=unix:///var/run/docker.sock"]
    assert not any(
        str(image).startswith("propertyscope/")
        for image in (s.get("image") for s in services.values())
    )
