"""Static guarantees of the Azure deployment artefacts (ADR-048); no Azure, Docker or network."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
AZURE = ROOT / "deployment" / "azure"
EDGE_SERVICE = "shared-edge-proxy"
DATABASE_TIER = {
    "f1-postgres": "f1-data",
    "f1-db-api": "f1-data",
    "f1-db-loader": "f1-data",
    "f2-db-api": "f2-data",
    "f3-database": "f3-data",
    "f4-postgres": "f4-data",
    "f4-db-api": "f4-data",
    "f5-db-api": "f5-data",
}
SECRET_VARIABLES = re.compile(r"(TOKEN|PASSWORD|DATABASE_URL|API_KEY)$")


class ComposeTag:
    """A Compose merge tag (!reset / !override) with the value it carries."""

    def __init__(self, tag: str, value: object) -> None:
        self.tag = tag
        self.value = value


class ComposeLoader(yaml.SafeLoader):
    """SafeLoader that understands Compose's !reset and !override merge tags."""


def _construct_tag(loader: yaml.SafeLoader, node: yaml.Node) -> ComposeTag:
    value: object
    if isinstance(node, yaml.SequenceNode):
        value = loader.construct_sequence(node, deep=True)
    elif isinstance(node, yaml.MappingNode):
        value = loader.construct_mapping(node, deep=True)
    else:
        value = loader.construct_scalar(node)  # type: ignore[arg-type]
    return ComposeTag(node.tag, value)


ComposeLoader.add_constructor("!reset", _construct_tag)
ComposeLoader.add_constructor("!override", _construct_tag)


def _compose(name: str) -> dict[str, Any]:
    document = ComposeLoader((ROOT / name).read_text(encoding="utf-8")).get_single_data()
    assert isinstance(document, dict)
    return document


def _plain(value: object) -> object:
    return value.value if isinstance(value, ComposeTag) else value


BASE = _compose("docker-compose.yml")
AZURE_OVERRIDE = _compose("docker-compose.azure.yml")
AZURE_AI = _compose("docker-compose.azure-ai.yml")
ENABLED = _compose("deployment/enabled-features.compose.yml")


def _dockerfile_commands() -> dict[tuple[str, str], list[str]]:
    """(Dockerfile, target) -> CMD for every Python stage."""
    commands: dict[tuple[str, str], list[str]] = {}
    for dockerfile in sorted(ROOT.glob("student-*/Dockerfile")):
        stage = ""
        for line in dockerfile.read_text(encoding="utf-8").splitlines():
            if match := re.match(r"FROM \S+ AS (\S+)", line):
                stage = match.group(1)
            elif line.startswith("CMD ["):
                commands[(dockerfile.relative_to(ROOT).as_posix(), stage)] = json.loads(line[4:])
    return commands


def test_only_the_tls_edge_publishes_ports() -> None:
    services = AZURE_OVERRIDE["services"]
    assert services[EDGE_SERVICE]["ports"] == ["80:80", "443:443"]
    published = {
        name
        for name, service in {**BASE["services"], **ENABLED["services"]}.items()
        if service.get("ports")
    }
    for name in published:
        ports = services[name]["ports"]
        assert isinstance(ports, ComposeTag) and ports.tag == "!reset", name
        assert ports.value == [], name


def test_every_built_service_uses_an_acr_image_tagged_with_the_commit() -> None:
    services = AZURE_OVERRIDE["services"]
    for name, service in BASE["services"].items():
        image = services[name]["image"]
        assert image.startswith("${ACR_LOGIN_SERVER:?"), name
        if "build" in service:
            assert image.endswith(f"/propertyscope/{name}:${{IMAGE_TAG:?IMAGE_TAG is required}}")
            build = services[name]["build"]
            assert isinstance(build, ComposeTag) and build.tag == "!reset", name
        else:
            assert "/propertyscope/mirror/" in image, name


def test_no_source_bind_mounts_or_reload_and_runner_uses_a_named_cache_volume() -> None:
    for name, service in AZURE_OVERRIDE["services"].items():
        for mount in service.get("volumes", []):
            source = mount["source"] if isinstance(mount, dict) else str(mount).split(":")[0]
            if source.startswith("."):
                assert source.startswith("./deployment/azure/"), (name, source)
        assert "watch" not in service.get("develop", {}), name
    runner_mounts = AZURE_OVERRIDE["services"]["f1-runner"]["volumes"]
    assert "f1-source-cache:/var/lib/propertyscope/source-cache:ro" in runner_mounts
    assert "f1-source-cache" in AZURE_OVERRIDE["volumes"]


def test_databases_sit_only_on_internal_feature_networks() -> None:
    services, networks = AZURE_OVERRIDE["services"], AZURE_OVERRIDE["networks"]
    for name, network in DATABASE_TIER.items():
        override = services[name]["networks"]
        assert isinstance(override, ComposeTag) and override.tag == "!override", name
        assert override.value == [network], name
        assert networks[network]["internal"] is True


def test_secrets_are_files_and_no_credential_value_reaches_the_environment() -> None:
    for name, service in AZURE_OVERRIDE["services"].items():
        environment = _plain(service.get("environment", {}))
        assert isinstance(environment, dict)
        for variable, value in environment.items():
            if SECRET_VARIABLES.search(variable):
                assert value in ("", None), (name, variable)
        names = str(environment.get("PROPERTYSCOPE_SECRET_ENV", ""))
        for pair in names.split():
            variable, secret = pair.split("=")
            assert secret in service["secrets"], (name, secret)
            assert environment.get(variable) == "", (name, variable)
    for secret in AZURE_OVERRIDE["secrets"].values():
        assert secret["file"].startswith(
            "${PROPERTYSCOPE_SECRETS_DIR:-/opt/propertyscope/secrets}/"
        )


def test_entrypoint_shim_restates_each_dockerfile_command() -> None:
    dockerfile_commands = _dockerfile_commands()
    for document in (AZURE_OVERRIDE, AZURE_AI):
        for name, service in document["services"].items():
            if "entrypoint" not in service:
                continue
            assert service["entrypoint"] == ["/bin/sh", "/run/propertyscope/secret-env.sh"]
            build = BASE["services"][name]["build"]
            expected = dockerfile_commands[(build["dockerfile"], build["target"])]
            assert service["command"] == expected, name


def test_ai_tier_is_disabled_by_default_and_wired_through_the_host_gateway_when_enabled() -> None:
    for name, service in AZURE_OVERRIDE["services"].items():
        environment = _plain(service.get("environment", {}))
        assert isinstance(environment, dict)
        for variable in ("AI_MODE_BASE_URL", "AI_MODE_URL"):
            if variable in environment:
                assert environment[variable] == "http://127.0.0.1:9", name
        extra_hosts = service.get("extra_hosts")
        if "extra_hosts" in BASE["services"].get(name, {}):
            assert isinstance(extra_hosts, ComposeTag) and extra_hosts.value == [], name
    for name, service in AZURE_AI["services"].items():
        environment = service.get("environment", {})
        urls = [
            environment.get(key)
            for key in ("AI_MODE_BASE_URL", "AI_MODE_URL")
            if key in environment
        ]
        if urls:
            assert all(str(url).startswith("http://host.docker.internal:") for url in urls)
            assert service["extra_hosts"] == ["host.docker.internal:host-gateway"], name
        for mapping in service.get("ports", []):
            assert str(mapping).startswith("127.0.0.1:"), name


def test_restart_policies_and_log_rotation_cover_every_service() -> None:
    for name, service in AZURE_OVERRIDE["services"].items():
        assert service["restart"] == "unless-stopped", name
        assert service["logging"]["driver"] == "json-file", name
        assert service["logging"]["options"]["max-size"] == "10m", name


def test_compose_override_validates_with_dummy_values(tmp_path: Path) -> None:
    """Optional: exercises the real Compose merge when Docker happens to be installed."""
    docker = shutil.which("docker")
    if docker is None:
        pytest.skip("docker is not installed")
    for name in ("internal-token", "runner-token", "f1-postgres-password", "f1-database-url",
                 "f4-postgres-password", "f4-database-url", "edge-basic-auth",
                 "ai-mode-service-token"):  # fmt: skip
        (tmp_path / name).write_text("dummy", encoding="utf-8")
    environment = {
        **os.environ,
        "ACR_LOGIN_SERVER": "example.azurecr.io",
        "IMAGE_TAG": "0" * 40,
        "PROPERTYSCOPE_PUBLIC_HOST": "example.australiaeast.cloudapp.azure.com",
        "PROPERTYSCOPE_ACME_EMAIL": "operator@example.com",
        "PROPERTYSCOPE_SECRETS_DIR": str(tmp_path),
    }
    files = [
        "docker-compose.yml",
        "deployment/enabled-features.compose.yml",
        "docker-compose.azure.yml",
    ]
    for extra in ([], ["docker-compose.azure-ai.yml"]):
        command = [docker, "compose"]
        for file in [*files, *extra]:
            command += ["-f", file]
        try:
            completed = subprocess.run(  # noqa: S603 - fixed docker compose argv, no shell
                [*command, "--profile", "release-0", "config", "--quiet"],
                cwd=ROOT,
                env=environment,
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            pytest.skip(f"docker compose unavailable: {exc}")
        if "is not a docker command" in completed.stderr or "unknown shorthand" in completed.stderr:
            pytest.skip("docker compose plugin is not installed")
        assert completed.returncode == 0, completed.stderr


def test_bicep_keeps_the_security_baseline() -> None:
    main = (AZURE / "main.bicep").read_text(encoding="utf-8")
    registry = (AZURE / "modules/registry.bicep").read_text(encoding="utf-8")
    vault = (AZURE / "modules/keyvault.bicep").read_text(encoding="utf-8")
    network = (AZURE / "modules/network.bicep").read_text(encoding="utf-8")
    vm = (AZURE / "modules/vm.bicep").read_text(encoding="utf-8")
    access = (AZURE / "modules/access.bicep").read_text(encoding="utf-8")
    assert "targetScope = 'resourceGroup'" in main
    assert "adminUserEnabled: false" in registry
    assert "anonymousPullEnabled: false" in registry
    assert "enableRbacAuthorization: true" in vault
    assert "enablePurgeProtection: true" in vault
    assert "enableSoftDelete: true" in vault
    allowed_ports = re.findall(r"access: 'Allow'.*?destinationPortRange: '(\S+)'", network, re.S)
    assert sorted(allowed_ports) == ["443", "80"]
    assert "sku: {\n    name: 'Standard'" in network
    assert "domainNameLabel: dnsLabel" in network
    assert "type: 'SystemAssigned'" in vm
    assert "encryptionAtHost: enableEncryptionAtHost" in vm
    assert "offer: 'ubuntu-24_04-lts'" in vm
    assert "disablePasswordAuthentication: true" in vm
    assert "loadTextContent('../cloud-init.yaml')" in vm
    # AcrPull and Key Vault Secrets User for the VM identity, nothing broader.
    assert "7f951dda-4ed3-4680-a7ca-43fe172d538d" in access
    assert "4633458b-17de-408a-b874-0445c86b69e6" in access
    assert "8e3af657-a8ff-443c-a75c-2fe8c4bcb635" not in access  # Owner
    assert "b24988ac-6180-42a0-ab88-20f7382dd24c" not in access  # Contributor
    for output in ("fqdn", "acrLoginServer", "vmName", "keyVaultName"):
        assert f"output {output} string" in main
    params = (AZURE / "main.bicepparam").read_text(encoding="utf-8")
    assert "readEnvironmentVariable('AZURE_LOCATION', 'australiaeast')" in params
    assert "readEnvironmentVariable('AZURE_VM_SIZE', 'Standard_D4s_v5')" in params


def test_cloud_init_installs_the_runtime_and_disables_ssh() -> None:
    text = (AZURE / "cloud-init.yaml").read_text(encoding="utf-8")
    assert text.startswith("#cloud-config\n")
    document = yaml.safe_load(text)
    commands = "\n".join(" ".join(map(str, command)) for command in document["runcmd"])
    for package in ("docker-ce", "docker-compose-plugin", "azure-cli"):
        assert package in commands
    assert "astral.sh/uv/" in commands
    assert "systemctl disable --now ssh.socket ssh.service" in commands
    assert {user["name"] for user in document["users"] if isinstance(user, dict)} == {
        "propertyscope-ai"
    }


def test_systemd_units_match_the_host_runtime_and_run_unprivileged() -> None:
    units = {
        path.stem: path.read_text(encoding="utf-8")
        for path in (AZURE / "systemd").glob("*.service")
    }
    assert set(units) == {
        "propertyscope-ai-mode",
        "propertyscope-mcp",
        "propertyscope-rag",
        "propertyscope-multi-agent",
    }
    for service in ("ai-mode", "mcp", "rag"):
        assert (
            "ExecStart=/opt/propertyscope/src/.venv/bin/python -m scripts.devtools.host_runtime "
            f"serve {service}"
        ) in units[f"propertyscope-{service}"]
    assert (
        "ExecStart=/opt/propertyscope/src/.venv/bin/multi-agent-server serve"
        in units["propertyscope-multi-agent"]
    )
    for name, unit in units.items():
        assert "User=propertyscope-ai" in unit, name
        assert "EnvironmentFile=/opt/propertyscope/secrets/host-ai.env" in unit, name
        assert "NoNewPrivileges=yes" in unit and "ProtectSystem=strict" in unit, name
        assert "PartOf=propertyscope-ai.target" in unit, name
        assert "OPENAI_API_KEY=" not in unit, name


def test_edge_protects_operations_and_ai_routes_consistently() -> None:
    caddyfile = (AZURE / "Caddyfile").read_text(encoding="utf-8")
    nginx = (AZURE / "nginx" / "00-propertyscope-production.conf").read_text(encoding="utf-8")
    protected = re.search(r"path_regexp protected (\S+)", caddyfile)
    assert protected is not None
    caddy_pattern = re.compile(protected.group(1))
    sensitive_block = nginx.split("map $uri $propertyscope_sensitive_limit_key {", 1)[1]
    sensitive_block = sensitive_block.split("}\n", 1)[0]
    nginx_patterns = [
        re.compile(line.split()[0][1:])
        for line in sensitive_block.splitlines()
        if line.strip().startswith("~")
    ]
    sensitive = [
        "/operations/ai-mode/",
        "/api/ai-mode/runs",
        "/api/v1/runs",
        "/api/data-platform/v1/assistant/turns",
        "/api/market-intelligence/v1/cases/x/assistant/turns",
        "/api/due-diligence/v1/site-reviews/x/case-summary-runs",
        "/api/data-platform/v1/tools/search",
        "/api/data-platform/v1/jobs/abc/runs",
        "/api/data-platform/v1/dataset-releases/abc/publish",
        "/api/suburb-analytics/v1/data-imports/x",
    ]
    public = [
        "/",
        "/api/shared-health/ai-mode",
        "/api/data-platform/v1/sources",
        "/api/buyer-workspaces/v1/buyer-cases",
        "/features/data-platform/",
    ]
    for path in sensitive:
        assert caddy_pattern.search(path), path
        assert any(pattern.search(path) for pattern in nginx_patterns), path
    for path in public:
        assert not caddy_pattern.search(path), path
        assert not any(pattern.search(path) for pattern in nginx_patterns), path
    assert 'Strict-Transport-Security "max-age=31536000; includeSubDomains"' in caddyfile
    assert caddyfile.index("basic_auth @protected") < caddyfile.index(
        "import /etc/caddy/propertyscope-ai.caddy"
    )
    assert "limit_req_status 429;" in nginx


def test_production_edge_files_are_mounted_only_by_the_azure_overrides() -> None:
    for name in (
        "docker-compose.yml",
        "docker-compose.dev.yml",
        "deployment/enabled-features.compose.yml",
    ):
        assert "deployment/azure" not in (ROOT / name).read_text(encoding="utf-8"), name
    volumes = AZURE_OVERRIDE["services"]["shared-frontend"]["volumes"]
    assert any("00-propertyscope-production.conf" in str(volume) for volume in volumes)


def test_deploy_script_offers_every_documented_subcommand() -> None:
    script = (AZURE / "deploy.sh").read_text(encoding="utf-8")
    assert script.startswith("#!/usr/bin/env bash\n")
    assert "set -euo pipefail" in script
    for command in ("provision", "secrets", "push", "deploy", "smoke", "ai", "status", "logs"):
        assert re.search(rf"^\s+{command}\)", script, re.M), command
    assert "az vm run-command invoke" in script
    assert "--command-id RunShellScript" in script
    # Nothing reads a secret value back out of Key Vault on the operator's machine.
    assert "secret show" not in script.replace(
        "az keyvault secret show --vault-name $KEY_VAULT_NAME --name edge-basic-auth-password", ""
    )
