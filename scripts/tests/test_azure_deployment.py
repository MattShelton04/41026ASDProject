"""Static guarantees of the Azure deployment artefacts (ADR-048); no Azure, Docker or network."""

from __future__ import annotations

import base64
import io
import json
import os
import re
import shutil
import subprocess
import tarfile
from pathlib import Path
from typing import Any

import pytest
import yaml
from scripts.devtools import cloud

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
RUN_ID = "0b8f0e64-5d0c-4e43-9a59-2b1f3c4d5e6f"


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
                 "ai-mode-service-token", "multi-agent-service-token"):  # fmt: skip
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


def test_https_can_be_limited_to_listed_sources_while_http_stays_open() -> None:
    network = (AZURE / "modules/network.bicep").read_text(encoding="utf-8")
    rules = dict(
        re.findall(r"name: '(Allow\w+Inbound)'\s*properties: \{(.*?)\n {8}\}", network, re.S)
    )
    assert set(rules) == {"AllowHttpsInbound", "AllowHttpInbound"}
    # Azure rejects a service tag (the Internet default) in the plural list, so one source uses
    # the singular property and only a longer list uses sourceAddressPrefixes.
    assert "var singleHttpsSource = length(allowedHttpsSourcePrefixes) == 1" in network
    https = rules["AllowHttpsInbound"]
    assert "sourceAddressPrefix: singleHttpsSource ? allowedHttpsSourcePrefixes[0] : null" in https
    assert "sourceAddressPrefixes: singleHttpsSource ? [] : allowedHttpsSourcePrefixes" in https
    # ACME HTTP-01 validation and renewal come from unpublished addresses: 80 is never limited.
    assert "sourceAddressPrefix: 'Internet'" in rules["AllowHttpInbound"]
    assert "allowedHttpsSourcePrefixes" not in rules["AllowHttpInbound"]
    main = (AZURE / "main.bicep").read_text(encoding="utf-8")
    assert "allowedHttpsSourcePrefixes: allowedHttpsSourcePrefixes" in main
    assert re.search(
        r"@minLength\(1\)\nparam allowedHttpsSourcePrefixes array = \[\n  'Internet'\n\]", main
    )
    for name in ("main.bicepparam", "dev.bicepparam"):
        params = (AZURE / name).read_text(encoding="utf-8")
        assert "readEnvironmentVariable('AZURE_ALLOWED_HTTPS_SOURCES', '')" in params, name
        assert (
            "param allowedHttpsSourcePrefixes = empty(httpsSourcesSetting) ? ['Internet'] "
            ": split(httpsSourcesSetting, ',')"
        ) in params, name


def test_site_wide_login_is_on_by_default_and_spares_only_liveness() -> None:
    caddyfile = (AZURE / "Caddyfile").read_text(encoding="utf-8")
    on = (AZURE / "caddy" / "site-auth-on.caddy").read_text(encoding="utf-8")
    off = (AZURE / "caddy" / "site-auth-off.caddy").read_text(encoding="utf-8")
    assert "@site_login not path /healthz\n" in caddyfile
    # Operator check, then the site login, then the AI tier and the proxy.
    order = [
        caddyfile.index("basic_auth @protected"),
        caddyfile.index("import /etc/caddy/propertyscope-site-auth.caddy"),
        caddyfile.index("import /etc/caddy/propertyscope-ai.caddy"),
        caddyfile.index("reverse_proxy shared-frontend:8080"),
    ]
    assert order == sorted(order)
    assert 'basic_auth @site_login bcrypt "PropertyScope NSW" {' in on
    assert "import /run/secrets/edge_site_auth" in on
    assert "basic_auth" not in off
    # Caddy's own error answers (the 401 login challenges) carry the site's security headers too.
    errors = caddyfile.split("handle_errors {", 1)[1].split("\n\t}\n", 1)[0]
    assert "import security_headers" in errors
    assert caddyfile.count("import security_headers") == 2
    edge = AZURE_OVERRIDE["services"]["shared-edge-proxy"]
    assert (
        "./deployment/azure/caddy/site-auth-${PROPERTYSCOPE_SITE_AUTH:-on}.caddy:"
        "/etc/caddy/propertyscope-site-auth.caddy:ro"
    ) in edge["volumes"]
    assert edge["secrets"] == ["edge_basic_auth", "edge_site_auth"]
    assert AZURE_OVERRIDE["secrets"]["edge_site_auth"]["file"].endswith("/edge-site-auth")
    deploy = (AZURE / "deploy.sh").read_text(encoding="utf-8")
    assert "export PROPERTYSCOPE_SITE_AUTH=${PROPERTYSCOPE_SITE_AUTH:-on}" in deploy
    assert "edge-site-password)" in deploy  # one of REQUIRED_SECRETS


def test_workflow_hands_the_viewer_password_only_to_smoke_and_endpoint_validation() -> None:
    workflow = yaml.safe_load(
        (ROOT / ".github" / "workflows" / "cloud-deployment.yml").read_text(encoding="utf-8")
    )
    job = workflow["jobs"]["deploy"]
    assert job["env"]["PROPERTYSCOPE_SITE_AUTH"] == "${{ vars.PROPERTYSCOPE_SITE_AUTH || 'on' }}"
    assert job["env"]["AZURE_ALLOWED_HTTPS_SOURCES"] == "${{ vars.AZURE_ALLOWED_HTTPS_SOURCES }}"
    assert "PROPERTYSCOPE_SITE_PASSWORD" not in job["env"]
    holders = sorted(
        step["id"]
        for step in job["steps"]
        if "secrets.PROPERTYSCOPE_SITE_PASSWORD" in str(step.get("env", {}))
    )
    assert holders == ["endpoint_security", "smoke"]


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
        if path.stem != "propertyscope-imds-guard"
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


def test_imds_guard_unit_drops_container_traffic_to_the_metadata_service() -> None:
    unit = (AZURE / "systemd" / "propertyscope-imds-guard.service").read_text(encoding="utf-8")
    rule = "DOCKER-USER -d 169.254.169.254/32 -j DROP"
    # Idempotent: inserts the rule only when the check finds it missing.
    assert f"iptables -w -C {rule} || iptables -w -I {rule}" in unit
    assert "Type=oneshot" in unit and "RemainAfterExit=yes" in unit
    # Ordered after Docker, and re-applied whenever Docker (re)starts.
    for line in ("After=docker.service", "PartOf=docker.service"):
        assert line in unit
    assert "WantedBy=multi-user.target docker.service" in unit
    script = (AZURE / "vm" / "propertyscope-vm.sh").read_text(encoding="utf-8")
    deploy = script[script.index("deploy() {") :]
    # Installed before any container starts.
    assert deploy.index("install_imds_guard") < deploy.index('compose "${up_arguments[@]}"')
    validate = script[script.index("validate_data() {") :]
    assert "validate_imds_guard" in validate


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
        # Feature 1's Multi-Agent proxy: starts paid model runs and records human decisions.
        "/api/data-platform/v1/release-reviews",
        "/api/data-platform/v1/release-reviews/template",
        f"/api/data-platform/v1/release-reviews/{RUN_ID}",
        f"/api/data-platform/v1/release-reviews/{RUN_ID}/decision",
        f"/api/data-platform/v1/release-reviews/{RUN_ID}/cancel",
        f"/api/data-platform/v1/release-reviews/{RUN_ID}/history",
        # The same collections are covered for any feature, at any depth.
        "/api/market-intelligence/v1/release-reviews",
        "/api/due-diligence/v1/site-reviews/x/release-reviews",
        "/api/buyer-workspaces/v1/buyer-cases/x/multi-agent/runs",
        "/api/suburb-analytics/v1/agent-runs",
    ]
    public = [
        "/",
        "/api/shared-health/ai-mode",
        "/api/data-platform/v1/sources",
        "/api/data-platform/v1/dataset-releases/abc",
        "/api/buyer-workspaces/v1/buyer-cases",
        "/api/due-diligence/v1/site-reviews/x",
        "/features/data-platform/",
        "/fragments/rate-limit-probe",
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
    for command in (
        "provision",
        "secrets",
        "push",
        "deploy",
        "smoke",
        "ai",
        "status",
        "logs",
        "source-cache",
        "ai-probe",
    ):
        assert re.search(rf"^\s+{command}\)", script, re.M), command
    assert "az vm run-command invoke" in script
    assert "--command-id RunShellScript" in script
    # Nothing reads a secret value back out of Key Vault on the operator's machine.
    assert "secret show" not in script.replace(
        "az keyvault secret show --vault-name $KEY_VAULT_NAME --name edge-basic-auth-password", ""
    )


# --- Multi-Agent wiring --------------------------------------------------------------------------

MULTI_AGENT_BACKENDS = sorted(
    name
    for name, service in BASE["services"].items()
    if "MULTI_AGENT_BASE_URL" in service.get("environment", {})
)


def test_multi_agent_backends_are_the_ones_the_overlays_wire() -> None:
    # Feature 3 declares no Multi-Agent connection locally, so the Azure files leave it alone.
    assert MULTI_AGENT_BACKENDS == ["f1-backend", "f2-backend", "f4-backend", "f5-backend"]


def test_baseline_closes_the_multi_agent_server_and_blanks_its_token() -> None:
    for name in MULTI_AGENT_BACKENDS:
        environment = _plain(AZURE_OVERRIDE["services"][name]["environment"])
        assert isinstance(environment, dict)
        assert environment["MULTI_AGENT_BASE_URL"] == "http://127.0.0.1:9", name
        assert environment["MULTI_AGENT_SERVICE_TOKEN"] == "", name
    f3 = AZURE_OVERRIDE["services"]["f3-backend"]["environment"]
    assert "MULTI_AGENT_SERVICE_TOKEN" not in f3


def test_ai_overlay_hands_each_multi_agent_backend_its_token_as_a_compose_secret() -> None:
    secret = AZURE_AI["secrets"]["multi_agent_service_token"]
    assert secret["file"] == (
        "${PROPERTYSCOPE_SECRETS_DIR:-/opt/propertyscope/secrets}/multi-agent-service-token"
    )
    for name in MULTI_AGENT_BACKENDS:
        service = AZURE_AI["services"][name]
        pairs = dict(
            pair.split("=") for pair in service["environment"]["PROPERTYSCOPE_SECRET_ENV"].split()
        )
        assert pairs["MULTI_AGENT_SERVICE_TOKEN"] == "multi_agent_service_token", name
        assert pairs["AI_MODE_SERVICE_TOKEN"] == "ai_mode_service_token", name
        assert "multi_agent_service_token" in service["secrets"], name
        assert service["environment"]["MULTI_AGENT_BASE_URL"].startswith(
            "http://host.docker.internal:"
        )
        # The baseline still mounts the shim and blanks the variable the shim fills.
        assert "entrypoint" in AZURE_OVERRIDE["services"][name], name
    # Pairs the baseline already lists stay listed when the overlay replaces the variable.
    for name in MULTI_AGENT_BACKENDS:
        baseline = _plain(AZURE_OVERRIDE["services"][name]["environment"])
        assert isinstance(baseline, dict)
        overlay = AZURE_AI["services"][name]["environment"]["PROPERTYSCOPE_SECRET_ENV"].split()
        assert set(baseline["PROPERTYSCOPE_SECRET_ENV"].split()) <= set(overlay), name
    f3 = AZURE_AI["services"]["f3-backend"]
    assert "multi_agent_service_token" not in f3["secrets"]


def test_vm_renders_compose_readable_entry_tokens_and_root_only_host_tokens() -> None:
    script = (AZURE / "vm" / "propertyscope-vm.sh").read_text(encoding="utf-8")
    assert "for name in ai-mode-service-token multi-agent-service-token; do" in script
    assert 'write_secret "$name" "$value" 0444' in script
    assert "for name in mcp-service-token rag-service-token; do" in script
    assert 'write_secret "$name" "$value" 0400' in script
    removal = script.split("remove_ai_secrets() {", 1)[1].split("\n}\n", 1)[0]
    assert "multi-agent-service-token" in removal


# --- Health checks -------------------------------------------------------------------------------


def test_services_without_an_image_health_check_gain_one_in_azure() -> None:
    services = AZURE_OVERRIDE["services"]
    caddy = services[EDGE_SERVICE]["healthcheck"]["test"]
    assert caddy == [
        "CMD",
        "wget",
        "--quiet",
        "--tries=1",
        "--spider",
        "http://127.0.0.1:8079/healthz",
    ]
    caddyfile = (AZURE / "Caddyfile").read_text(encoding="utf-8")
    site = caddyfile.split("http://127.0.0.1:8079 {", 1)[1].split("\n}", 1)[0]
    assert "bind 127.0.0.1" in site and 'respond /healthz "ok" 200' in site
    assert "8079" not in str(services[EDGE_SERVICE]["ports"])
    # The workers have no HTTP surface: each check reaches the dependency it polls, on a network
    # the worker actually joins in Azure.
    runner = " ".join(services["f1-runner"]["healthcheck"]["test"])
    assert "http://f1-backend:5201/health/live" in runner
    assert "networks" not in services["f1-runner"]  # stays on shared-platform with f1-backend
    loader = " ".join(services["f1-db-loader"]["healthcheck"]["test"])
    assert "('f1-postgres', 5432)" in loader
    assert _plain(services["f1-db-loader"]["networks"]) == _plain(
        services["f1-postgres"]["networks"]
    )
    routes = (ROOT / "student-1/backend/src/propertyscope_data_platform/api.py").read_text(
        encoding="utf-8"
    )
    assert '@api.get("/health/live")' in routes


# --- Edge rate limiting --------------------------------------------------------------------------


def _nginx_api_limit_patterns() -> list[re.Pattern[str]]:
    nginx = (AZURE / "nginx" / "00-propertyscope-production.conf").read_text(encoding="utf-8")
    block = nginx.split("map $uri $propertyscope_api_limit_key {", 1)[1].split("}\n", 1)[0]
    return [
        re.compile(line.split()[0][1:])
        for line in block.splitlines()
        if line.strip().startswith("~")
    ]


def test_b5_rate_limit_probe_reaches_limit_req() -> None:
    """The probe must not be answered by an nginx `return`, which runs before limit_req."""
    validator = (AZURE / "validate-endpoint-security.sh").read_text(encoding="utf-8")
    probe = re.search(r"RATE_LIMIT_PROBE=\$\{RATE_LIMIT_PROBE:-(\S+)\}", validator)
    assert probe is not None
    path = probe.group(1)
    assert "/api/rate-limit-probe" not in validator
    assert any(pattern.search(path) for pattern in _nginx_api_limit_patterns())
    edge = (ROOT / "shared/frontend/nginx.conf").read_text(encoding="utf-8")
    location = edge.split("location /fragments/ {", 1)[1].split("}", 1)[0]
    assert "try_files $uri =404;" in location and "return" not in location
    assert path.startswith("/fragments/")
    generated = (ROOT / "shared/frontend/generated/enabled-feature-routes.conf").read_text(
        encoding="utf-8"
    )
    # No feature fragment route (which would proxy to a backend) claims the probe.
    assert not any(
        path.startswith(prefix)
        for prefix in re.findall(r"location \^~ (/fragments/\S+)", generated)
    )
    iac = (AZURE / "validate-iac.sh").read_text(encoding="utf-8")
    assert f"readonly RATE_LIMIT_PROBE={path}" in iac


# --- systemd -------------------------------------------------------------------------------------


def test_ai_units_tolerate_a_missing_runtime_store_and_the_vm_creates_it() -> None:
    for path in (AZURE / "systemd").glob("*.service"):
        if path.stem == "propertyscope-imds-guard":
            continue  # a root oneshot that only sets an iptables rule
        unit = path.read_text(encoding="utf-8")
        paths = re.findall(r"^ReadWritePaths=(.+)$", unit, re.M)
        assert paths, path.name
        for value in paths:
            assert all(item.startswith("-") for item in value.split()), (path.name, value)
    script = (AZURE / "vm" / "propertyscope-vm.sh").read_text(encoding="utf-8")
    assert "readonly RUNTIME_DIR=$SRC_DIR/.propertyscope-runtime" in script
    assert 'install -d -m 0750 -o "$AI_USER" -g "$AI_USER" "$RUNTIME_DIR"' in script
    # Created before the units start.
    start = script.split("start_ai_tier() {", 1)[1]
    assert start.index("checkout_source") < start.index("systemctl enable --now")


# --- Bicep and provisioning ----------------------------------------------------------------------


def test_bicep_guards_empty_parameters_and_the_conditional_vm_output() -> None:
    main = (AZURE / "main.bicep").read_text(encoding="utf-8")
    assert "virtualMachine!.outputs.principalId" in main
    assert "virtualMachine.outputs" not in main
    assert "var publicDnsLabel = empty(dnsLabel) ?" in main
    assert "dnsLabel: publicDnsLabel" in main
    assert "registries@2025-04-01" in (AZURE / "modules/registry.bicep").read_text(encoding="utf-8")
    for name in ("main.bicepparam", "dev.bicepparam"):
        params = (AZURE / name).read_text(encoding="utf-8")
        assert "bool(readEnvironmentVariable" not in params, name
        assert "int(readEnvironmentVariable" not in params, name
        assert (
            "param location = empty(locationSetting) ? 'australiaeast' : locationSetting" in params
        )
    production = (AZURE / "main.bicepparam").read_text(encoding="utf-8")
    assert (
        "param dnsLabel = empty(dnsLabelSetting) ? 'propertyscope-nsw-g20' : dnsLabelSetting"
        in production
    )


def test_provision_recovers_a_soft_deleted_vault_before_deploying() -> None:
    script = (AZURE / "deploy.sh").read_text(encoding="utf-8")
    provision = script.split("cmd_provision() {", 1)[1].split("\n}\n", 1)[0]
    assert provision.index("az group create") < provision.index("recover_deleted_key_vault")
    assert provision.index("recover_deleted_key_vault") < provision.index("az deployment group")
    recover = script.split("recover_deleted_key_vault() {", 1)[1].split("\n}\n", 1)[0]
    assert "az_query keyvault list-deleted" in recover
    assert "run az keyvault recover" in recover
    assert "AZURE_KEY_VAULT_NAME_SEED" in recover
    main = (AZURE / "main.bicep").read_text(encoding="utf-8")
    assert "uniqueString(resourceGroup().id, keyVaultNameSeed)" in main
    assert "enablePurgeProtection: true" in (AZURE / "modules/keyvault.bicep").read_text(
        encoding="utf-8"
    )


def test_ci_runs_the_offline_iac_validation() -> None:
    workflow = yaml.safe_load(
        (ROOT / ".github/workflows/integration-ci.yml").read_text(encoding="utf-8")
    )
    job = workflow["jobs"]["iac-lint"]
    runs = "\n".join(step.get("run", "") for step in job["steps"])
    assert "az bicep install --version" in runs
    assert "bash deployment/azure/validate-iac.sh --strict" in runs
    assert "az login" not in runs and "azure/login" not in str(job)
    assert job["timeout-minutes"] <= 15
    iac = (AZURE / "validate-iac.sh").read_text(encoding="utf-8")
    for script in (
        "deployment/azure/deploy.sh",
        "deployment/azure/vm/propertyscope-vm.sh",
        "deployment/azure/validate-endpoint-security.sh",
        "deployment/azure/validate-data-security.sh",
    ):
        assert f"    {script}\n" in iac, script


# --- Shell behaviour (runs only where a POSIX bash is available) ---------------------------------


def _bash() -> str:
    try:
        return cloud.bash_executable()
    except RuntimeError:
        pytest.skip("bash is not installed")


def _run_bash(script: str, tmp_path: Path, **environment: str) -> subprocess.CompletedProcess[str]:
    harness = tmp_path / "harness.sh"
    harness.write_bytes(script.encode("utf-8"))
    return subprocess.run(  # noqa: S603 - fixed bash and a harness written by this test
        [_bash(), harness.as_posix(), tmp_path.as_posix()],
        cwd=ROOT,
        env={**os.environ, **environment},
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


# Sources the VM script (its functions only) with curl, jq and sleep replaced by fakes. Each curl
# call takes the next "<status>:<body>" from RESPONSES (the last one repeats); kv_get's `-w`
# calls print the body and the status, `-f` calls fail on anything but 200.
VM_HARNESS = r"""
set -euo pipefail
WORK=$1
source deployment/azure/vm/propertyscope-vm.sh
set +e
echo 0 >"$WORK/calls"
: >"$WORK/sleeps"
read -r -a RESPONSES <<<"$FAKE_RESPONSES"
curl() {
    local count entry status body
    count=$(<"$WORK/calls")
    echo $((count + 1)) >"$WORK/calls"
    entry=${RESPONSES[count]:-${RESPONSES[${#RESPONSES[@]}-1]}}
    status=${entry%%:*}
    body=${entry#*:}
    if [[ " $* " == *" -w "* ]]; then
        printf '%s\n%s' "$body" "$status"
    elif [[ $status == 200 ]]; then
        printf '%s' "$body"
    else
        return 22
    fi
}
jq() {
    local key=${2#.} input value
    input=$(cat)
    value=$(sed -n "s/.*\"$key\":\"\([^\"]*\)\".*/\1/p" <<<"$input")
    [[ -n $value ]] || return 1
    printf '%s\n' "$value"
}
sleep() { printf '%s ' "$1" >>"$WORK/sleeps"; }
"""


@pytest.mark.parametrize(
    ("responses", "call", "status", "output", "calls", "sleeps"),
    [
        ('403:{} 403:{} 200:{"value":"s3cret"}', "kv_get internal-token", 0, "s3cret", 3, "5 10"),
        ('000: 503:{} 200:{"value":"s3cret"}', "kv_get internal-token", 0, "s3cret", 3, "5 10"),
        ("404:{}", "kv_get openai-api-key optional", 3, "", 1, ""),
        ("404:{}", "kv_get internal-token", 1, "", 1, ""),
        ("400:{}", "kv_get internal-token", 1, "", 1, ""),
        ("403:{}", "kv_get internal-token", 1, "", 4, "5 10 20"),
        (
            '400:{} 400:{} 200:{"access_token":"tok"}',
            "imds_token https://vault.azure.net",
            0,
            "tok",
            3,
            "5 10",
        ),
        ("400:{}", "imds_token https://vault.azure.net", 1, "", 4, "5 10 20"),
    ],
    ids=[
        "kv-403-propagation",
        "kv-network-and-5xx",
        "kv-optional-missing",
        "kv-required-missing",
        "kv-bad-request",
        "kv-gives-up",
        "imds-identity-not-ready",
        "imds-gives-up",
    ],
)
def test_vm_azure_calls_retry_with_bounded_backoff(
    tmp_path: Path,
    responses: str,
    call: str,
    status: int,
    output: str,
    calls: int,
    sleeps: str,
) -> None:
    script = VM_HARNESS + f'value=$({call})\nrc=$?\nprintf "rc=%s value=%s\\n" "$rc" "$value"\n'
    completed = _run_bash(
        script,
        tmp_path,
        FAKE_RESPONSES=responses,
        PROPERTYSCOPE_AUTH_RETRY_ATTEMPTS="4",
        KEY_VAULT_NAME="example-kv",
        KV_TOKEN="token",
    )
    assert f"rc={status} value={output}\n" in completed.stdout, completed.stderr
    assert (tmp_path / "calls").read_text(encoding="utf-8").strip() == str(calls)
    assert (tmp_path / "sleeps").read_text(encoding="utf-8").strip() == sleeps


def test_vm_backoff_grows_to_a_one_minute_cap(tmp_path: Path) -> None:
    script = VM_HARNESS + (
        "for attempt in $(seq 1 12); do\n"
        '    backoff "$attempt" probe 2>/dev/null || echo "stop=$attempt"\n'
        "done\n"
    )
    completed = _run_bash(script, tmp_path, FAKE_RESPONSES="200:{}")
    assert "stop=12" in completed.stdout, completed.stderr
    assert (tmp_path / "sleeps").read_text(encoding="utf-8").split() == [
        "5", "10", "20", "40", "60", "60", "60", "60", "60", "60", "60",
    ]  # fmt: skip


def test_vm_pull_logs_in_again_until_acr_accepts_the_identity(tmp_path: Path) -> None:
    script = VM_HARNESS + (
        'echo 0 >"$WORK/pulls"; echo 0 >"$WORK/logins"\n'
        'compose() { local n; n=$(<"$WORK/pulls"); echo $((n + 1)) >"$WORK/pulls"; ((n >= 2)); }\n'
        'acr_login() { local n; n=$(<"$WORK/logins"); echo $((n + 1)) >"$WORK/logins"; }\n'
        'pull_images && echo "pulled pulls=$(<"$WORK/pulls") logins=$(<"$WORK/logins")"\n'
    )
    completed = _run_bash(
        script, tmp_path, FAKE_RESPONSES="200:{}", IMAGE_TAG="abc", ACR_LOGIN_SERVER="x.azurecr.io"
    )
    assert "pulled pulls=3 logins=2" in completed.stdout, completed.stderr


def test_vm_settings_are_validated(tmp_path: Path) -> None:
    script = VM_HARNESS + ("(validate_settings) && echo valid\n")
    good = _run_bash(script, tmp_path, FAKE_RESPONSES="200:{}")
    assert "valid" in good.stdout, good.stderr
    bad = _run_bash(
        script, tmp_path, FAKE_RESPONSES="200:{}", PROPERTYSCOPE_STARTUP_WAIT_SECONDS="soon"
    )
    assert "valid" not in bad.stdout
    assert "PROPERTYSCOPE_STARTUP_WAIT_SECONDS" in bad.stderr


@pytest.mark.parametrize(
    ("site_auth", "expected", "reads"),
    [
        (
            "on",
            "viewer $2a$hash(pw-edge-site-password)\n"
            "propertyscope-operator $2a$hash(pw-edge-basic-auth-password)",
            True,
        ),
        ("off", "propertyscope-operator $2a$hash(pw-edge-basic-auth-password)", False),
    ],
    ids=["site-login-on", "site-login-off"],
)
def test_vm_renders_the_site_login_for_the_viewer_and_the_operator(
    tmp_path: Path, site_auth: str, expected: str, reads: bool
) -> None:
    script = VM_HARNESS + (
        "imds_token() { printf token; }\n"
        'kv_get() { echo "$1" >>"$WORK/reads"; printf "pw-%s" "$1"; }\n'
        'caddy_hash() { printf "\\$2a\\$hash(%s)" "$1"; }\n'
        "jq() { printf x; }\n"
        'write_secret() { printf "%s" "$2" >"$WORK/secret-$1"; }\n'
        "render_application_secrets >/dev/null\n"
    )
    completed = _run_bash(
        script,
        tmp_path,
        FAKE_RESPONSES="200:{}",
        KEY_VAULT_NAME="example-kv",
        PROPERTYSCOPE_SITE_AUTH=site_auth,
        PROPERTYSCOPE_SITE_USER="viewer",
    )
    assert completed.returncode == 0, completed.stderr
    assert (tmp_path / "secret-edge-site-auth").read_text(encoding="utf-8") == expected
    assert (tmp_path / "secret-edge-basic-auth").read_text(encoding="utf-8") == (
        "propertyscope-operator $2a$hash(pw-edge-basic-auth-password)"
    )
    reads_site = "edge-site-password" in (tmp_path / "reads").read_text(encoding="utf-8")
    assert reads_site is reads


@pytest.mark.parametrize(
    ("variables", "message"),
    [
        ({"PROPERTYSCOPE_SITE_AUTH": "maybe"}, "PROPERTYSCOPE_SITE_AUTH must be on or off"),
        ({"PROPERTYSCOPE_SITE_USER": "Viewer Name"}, "3-32 lower-case characters"),
        ({"PROPERTYSCOPE_SITE_USER": "propertyscope-operator"}, "must differ from the operator"),
    ],
    ids=["bad-toggle", "bad-user", "same-as-operator"],
)
def test_vm_rejects_bad_site_login_settings(
    tmp_path: Path, variables: dict[str, str], message: str
) -> None:
    completed = _run_bash(
        VM_HARNESS + "(validate_settings) && echo valid\n",
        tmp_path,
        FAKE_RESPONSES="200:{}",
        **variables,
    )
    assert "valid" not in completed.stdout
    assert message in completed.stderr


def test_dry_run_deploy_payload_is_valid_bash_and_ships_the_bundle(tmp_path: Path) -> None:
    completed = subprocess.run(  # noqa: S603 - fixed bash and repository script
        [_bash(), "deployment/azure/deploy.sh", "--dry-run", "deploy"],
        cwd=ROOT,
        env={
            **os.environ,
            "PROPERTYSCOPE_CLOUD_LOG_DIR": tmp_path.as_posix(),
            "AZURE_ENV_FILE": (tmp_path / "missing.env").as_posix(),
            "PROPERTYSCOPE_ACME_EMAIL": "operator@example.com",
            "IMAGE_TAG": "0" * 40,
            "PROPERTYSCOPE_STARTUP_WAIT_SECONDS": "1200",
        },
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    payload = tmp_path / "vm-deploy.payload.sh"
    text = payload.read_text(encoding="utf-8")
    assert "export PROPERTYSCOPE_STARTUP_WAIT_SECONDS=1200" in text
    # Root's tar keeps the operator checkout's modes (found by the local rehearsal: a 0600 nginx
    # include broke the edge), so the payload makes the bundle readable for non-root containers.
    extract = text.index("| tar -xzf - -C /opt/propertyscope/app")
    normalise = text.index("chmod -R u=rwX,go=rX /opt/propertyscope/app/deployment")
    assert extract < normalise < text.index("propertyscope-vm.sh deploy")
    syntax = subprocess.run(  # noqa: S603 - fixed bash and the payload just written
        [_bash(), "-n", payload.as_posix()], capture_output=True, text=True, check=False
    )
    assert syntax.returncode == 0, syntax.stderr
    encoded = re.search(r"printf '%s' '([A-Za-z0-9+/=]+)' \| base64 -d", text)
    assert encoded is not None
    with tarfile.open(fileobj=io.BytesIO(base64.b64decode(encoded.group(1))), mode="r:gz") as tar:
        names = set(tar.getnames())
    for required in (
        "docker-compose.azure.yml",
        "docker-compose.azure-ai.yml",
        "deployment/azure/Caddyfile",
        "deployment/azure/vm/propertyscope-vm.sh",
        "deployment/azure/systemd/propertyscope-multi-agent.service",
        "deployment/azure/nginx/00-propertyscope-production.conf",
    ):
        assert required in names, required


# --- PSI source cache ----------------------------------------------------------------------------


def test_vm_advertises_exactly_the_cached_psi_partitions(tmp_path: Path) -> None:
    cache = tmp_path / "volume"
    (cache / "psi" / "weekly").mkdir(parents=True)
    for name in (
        "psi/2024.zip",
        "psi/1990.zip",
        "psi/weekly/20261012.zip",
        "psi/weekly/20260105.zip",
    ):
        (cache / name).write_bytes(b"zip")
    for ignored in ("psi/notes.txt", "psi/weekly/latest.zip", "psi/202.zip"):
        (cache / ignored).write_bytes(b"x")
    script = VM_HARNESS + (
        f'source_cache_dir() {{ printf "%s" "{cache.as_posix()}"; }}\n'
        "psi_cache_environment\n"
        'source_cache_dir() { printf ""; }\n'
        "psi_cache_environment\n"
    )
    completed = _run_bash(script, tmp_path, FAKE_RESPONSES="200:{}")
    assert completed.stdout.splitlines() == [
        "PROPERTYSCOPE_PSI_CACHED_YEARS=1990,2024",
        "PROPERTYSCOPE_PSI_CACHED_WEEKS=2026-01-05,2026-10-12",
        "PROPERTYSCOPE_PSI_CACHED_YEARS=",
        "PROPERTYSCOPE_PSI_CACHED_WEEKS=",
    ], completed.stderr


@pytest.mark.parametrize(
    "image",
    [
        "evil.azurecr.io/propertyscope/source-cache:psi-1",
        "x.azurecr.io/propertyscope/f1-backend:psi-1",
        "x.azurecr.io/propertyscope/source-cache:psi 1",
    ],
    ids=["other-registry", "other-repository", "bad-tag"],
)
def test_vm_loads_source_cache_images_only_from_its_own_registry(
    tmp_path: Path, image: str
) -> None:
    script = VM_HARNESS + "(load_source_cache) && echo loaded\n"
    completed = _run_bash(
        script,
        tmp_path,
        FAKE_RESPONSES="200:{}",
        ACR_LOGIN_SERVER="x.azurecr.io",
        PROPERTYSCOPE_SOURCE_CACHE_IMAGE=image,
    )
    assert "loaded" not in completed.stdout
    assert "must be x.azurecr.io/propertyscope/source-cache:<tag>" in completed.stderr


def test_dry_run_source_cache_names_the_image_by_content_and_loads_it_on_the_vm(
    tmp_path: Path,
) -> None:
    cache = tmp_path / "cache"
    (cache / "psi" / "weekly").mkdir(parents=True)
    (cache / "psi" / "2024.zip").write_bytes(b"annual")
    (cache / "psi" / "weekly" / "20261012.zip").write_bytes(b"weekly")

    def dry_run() -> str:
        completed = subprocess.run(  # noqa: S603 - fixed bash and repository script
            [
                _bash(),
                "deployment/azure/deploy.sh",
                "--dry-run",
                "source-cache",
                "--no-sync",
                "--cache-dir",
                cache.as_posix(),
            ],
            cwd=ROOT,
            env={
                **os.environ,
                "PROPERTYSCOPE_CLOUD_LOG_DIR": tmp_path.as_posix(),
                "AZURE_ENV_FILE": (tmp_path / "missing.env").as_posix(),
            },
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        assert completed.returncode == 0, completed.stderr
        match = re.search(r"source-cache:(psi-[0-9a-f]{16})", completed.stderr)
        assert match is not None, completed.stderr
        return match.group(1)

    first = dry_run()
    assert dry_run() == first
    (cache / "psi" / "2025.zip").write_bytes(b"new year")
    assert dry_run() != first
    text = (tmp_path / "vm-load-source-cache.payload.sh").read_text(encoding="utf-8")
    assert re.search(
        r"^export PROPERTYSCOPE_SOURCE_CACHE_IMAGE=\S+/propertyscope/source-cache:psi-", text, re.M
    )
    assert "propertyscope-vm.sh load-source-cache" in text
    assert "base64 -d" not in text  # uses the installed deployment, ships no bundle


def _deploy(
    tmp_path: Path, *arguments: str, **environment: str
) -> subprocess.CompletedProcess[str]:
    base = {
        key: value for key, value in os.environ.items() if key != "PROPERTYSCOPE_OPERATOR_PASSWORD"
    }
    return subprocess.run(  # noqa: S603 - fixed bash and repository script
        [_bash(), "deployment/azure/deploy.sh", *arguments],
        cwd=ROOT,
        env={
            **base,
            "PROPERTYSCOPE_CLOUD_LOG_DIR": tmp_path.as_posix(),
            "AZURE_ENV_FILE": (tmp_path / "missing.env").as_posix(),
            "PROPERTYSCOPE_PUBLIC_URL": "https://cloud.test",
            **environment,
        },
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


def test_ai_probe_needs_the_operator_password_from_the_environment(tmp_path: Path) -> None:
    completed = _deploy(tmp_path, "ai-probe")

    assert completed.returncode != 0
    assert (
        "set PROPERTYSCOPE_OPERATOR_PASSWORD to the Key Vault secret edge-basic-auth-password"
        in (completed.stderr)
    )


def test_ai_probe_runs_the_probe_without_the_password_on_its_command_line(tmp_path: Path) -> None:
    sentinel = "operator-sentinel-value"  # pragma: allowlist secret
    completed = _deploy(
        tmp_path,
        "--dry-run",
        "ai-probe",
        "--commit-sha",
        "0" * 40,
        PROPERTYSCOPE_OPERATOR_PASSWORD=sentinel,
    )

    assert completed.returncode == 0, completed.stderr
    assert "scripts/cloud_ai_probe.py --base-url https://cloud.test" in completed.stderr
    assert f"--commit-sha {'0' * 40}" in completed.stderr
    assert sentinel not in completed.stderr + completed.stdout
