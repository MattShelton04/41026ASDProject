"""Terminal validation of the running host AI-mode, MCP and RAG servers.

This checks each server directly over its local HTTP interface, separately from the agent-loop
validation modes (``release1_validation``): authentication boundaries, the registered tools MCP
exposes for every enabled feature, and per-feature corpus retrieval including an
insufficient-context probe. It never prints a service token, never starts, stops or
reconfigures a service, and never ingests documents.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

import httpx
import yaml

from scripts.devtools import host_runtime
from scripts.devtools.config import REPOSITORY_ROOT
from shared_contracts import HealthStatus
from shared_contracts.deployment import DeploymentProjectionV1, TypedHealthProjection
from shared_contracts.grounding import GROUNDING_MIN_SCORE

AI_TOKEN_HEADER = "X-PropertyScope-AI-Token"
MCP_ACCEPT = "application/json, text/event-stream"
TOOLS_LIST = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
# Deliberately outside every feature's guidance, so no passage may clear the relevance floor.
OFF_TOPIC_QUERY = "What oven temperature and proofing time suit a sourdough loaf?"
KNOWN_PASSAGE_CHARS = 300


@dataclass(frozen=True, slots=True)
class Check:
    """One named observation with the evidence a reader needs to judge it."""

    service: str
    name: str
    passed: bool
    detail: str

    def as_json(self) -> dict[str, object]:
        return {
            "service": self.service,
            "check": self.name,
            "passed": self.passed,
            "detail": self.detail,
        }


@dataclass(frozen=True, slots=True)
class RegisteredFeature:
    """What one enabled feature registers with the shared AI tier."""

    feature_key: str
    tool_names: tuple[str, ...]
    corpus_id: str | None


def registered_features(root: Path = REPOSITORY_ROOT) -> tuple[RegisteredFeature, ...]:
    """Read each enabled feature's tool names and corpus from the deployment projection."""
    projection = DeploymentProjectionV1.model_validate_json(
        (root / "deployment/enabled-features.v1.json").read_text(encoding="utf-8")
    )
    features = []
    for feature in projection.features:
        if feature.ai is None:
            continue
        catalogue = yaml.safe_load((root / feature.ai.tool_catalog).read_text(encoding="utf-8"))
        names = tuple(str(tool["definition"]["name"]) for tool in catalogue.get("tools", []))
        features.append(RegisteredFeature(feature.feature_key, names, feature.ai.rag_corpus_id))
    return tuple(features)


def _http(response: httpx.Response) -> str:
    return f"HTTP {response.status_code}"


def _authenticated_ai_readiness(response: httpx.Response) -> tuple[bool, str]:
    """Accept the documented readiness body, including a provider-only outage."""
    if response.status_code not in {200, 503}:
        return False, _http(response)
    try:
        health = TypedHealthProjection.model_validate_json(response.content)
    except ValueError:
        return False, f"{_http(response)}; invalid readiness response"
    store = health.checks.get("state_store")
    provider = health.checks.get("llm_provider")
    if (
        health.service != "ai-mode"
        or health.http_status != response.status_code
        or response.headers.get("content-type", "").split(";", 1)[0] != "application/json"
        or store is None
        or not store.required
        or store.status is not HealthStatus.HEALTHY
        or provider is None
    ):
        return False, f"{_http(response)}; unexpected readiness response"
    if response.status_code == 503:
        provider_only_outage = (
            provider.required
            and provider.status is HealthStatus.UNHEALTHY
            and all(
                not check.required or check.status is HealthStatus.HEALTHY
                for name, check in health.checks.items()
                if name != "llm_provider"
            )
        )
        return (
            provider_only_outage,
            f"{_http(response)}; service token accepted; model provider not ready"
            if provider_only_outage
            else f"{_http(response)}; unexpected readiness failure",
        )
    return True, f"{_http(response)}; service token accepted; readiness {health.status.value}"


def _probe_ai_mode(client: httpx.Client, url: str, token: str) -> list[Check]:
    live = client.get(f"{url}/health/live")
    anonymous = client.get(f"{url}/health/ready")
    authenticated = client.get(f"{url}/health/ready", headers={AI_TOKEN_HEADER: token})
    token_accepted, authenticated_detail = _authenticated_ai_readiness(authenticated)
    return [
        Check("ai-mode", "liveness", live.status_code == 200, _http(live)),
        Check(
            "ai-mode",
            "rejects an unauthenticated caller",
            anonymous.status_code == 401,
            _http(anonymous),
        ),
        Check(
            "ai-mode",
            "accepts the service token",
            token_accepted,
            authenticated_detail,
        ),
    ]


def _probe_mcp(
    client: httpx.Client, url: str, token: str, features: tuple[RegisteredFeature, ...]
) -> list[Check]:
    headers = {"Authorization": f"Bearer {token}", "Accept": MCP_ACCEPT}
    anonymous = client.post(url, json=TOOLS_LIST, headers={"Accept": MCP_ACCEPT})
    health = client.get(f"{url.removesuffix('/mcp')}/health", headers=headers)
    checks = [
        Check(
            "mcp",
            "rejects an unauthenticated caller",
            anonymous.status_code == 401,
            _http(anonymous),
        ),
        Check(
            "mcp",
            "health",
            health.status_code == 200,
            f"{_http(health)}; {health.json().get('registered_tools', '?')} tools registered"
            if health.status_code == 200
            else _http(health),
        ),
    ]
    listed = client.post(url, json=TOOLS_LIST, headers=headers)
    if listed.status_code != 200:
        return [*checks, Check("mcp", "tools/list", False, _http(listed))]
    tools = listed.json().get("result", {}).get("tools", [])
    exposed = {str(tool.get("name")) for tool in tools if isinstance(tool, dict)}
    checks.append(Check("mcp", "tools/list", bool(exposed), f"{len(exposed)} tools exposed"))
    for feature in features:
        missing = sorted(set(feature.tool_names) - exposed)
        checks.append(
            Check(
                "mcp",
                f"{feature.feature_key} tools",
                not missing,
                f"missing {', '.join(missing)}" if missing else f"{len(feature.tool_names)} listed",
            )
        )
    return checks


def _retrieve(
    client: httpx.Client,
    url: str,
    headers: Mapping[str, str],
    feature: RegisteredFeature,
    query: str,
) -> dict[str, object]:
    response = client.post(
        f"{url}/api/v1/retrieve",
        headers=headers,
        json={
            "feature_key": feature.feature_key,
            "corpus_id": feature.corpus_id,
            "query": query,
            "top_k": 3,
            "min_score": GROUNDING_MIN_SCORE,
        },
    )
    response.raise_for_status()
    value = response.json()
    if not isinstance(value, dict):
        raise RuntimeError("RAG returned a malformed retrieval response")
    return value


def _probe_corpus(
    client: httpx.Client, url: str, headers: Mapping[str, str], feature: RegisteredFeature
) -> list[Check]:
    name = feature.feature_key
    contents = client.get(
        f"{url}/api/v1/corpora/{name}/{feature.corpus_id}/chunks", headers=headers
    )
    if contents.status_code != 200:
        return [Check("rag", f"{name} corpus", False, f"{_http(contents)}; ingest it first")]
    body = contents.json()
    version = body["version"]
    checks = [
        Check(
            "rag",
            f"{name} corpus",
            bool(body["chunks"]),
            f"{feature.corpus_id} {version['corpus_version'][:12]}: "
            f"{version['document_count']} documents, {version['chunk_count']} chunks",
        )
    ]
    if not body["chunks"]:
        return checks
    known = _retrieve(
        client, url, headers, feature, body["chunks"][0]["excerpt"][:KNOWN_PASSAGE_CHARS]
    )
    citations = known.get("citations")
    cited = citations if isinstance(citations, list) else []
    top = cited[0] if cited else {}
    checks.append(
        Check(
            "rag",
            f"{name} grounded retrieval",
            known.get("status") == "ready" and bool(cited),
            f"{known.get('status')}; {len(cited)} citations; "
            f"top '{top.get('title', '-')}' score {top.get('score', '-')}",
        )
    )
    off_topic = _retrieve(client, url, headers, feature, OFF_TOPIC_QUERY)
    checks.append(
        Check(
            "rag",
            f"{name} insufficient context",
            off_topic.get("status") == "no_match",
            f"{off_topic.get('status')} for an off-topic question "
            f"(relevance floor {GROUNDING_MIN_SCORE})",
        )
    )
    return checks


def _probe_rag(
    client: httpx.Client, url: str, token: str, features: tuple[RegisteredFeature, ...]
) -> list[Check]:
    headers = {"Authorization": f"Bearer {token}"}
    anonymous = client.get(f"{url}/health/ready")
    ready = client.get(f"{url}/health/ready", headers=headers)
    model = ready.json().get("embedding_model", "?") if ready.status_code in {200, 503} else "-"
    checks = [
        Check(
            "rag",
            "rejects an unauthenticated caller",
            anonymous.status_code == 401,
            _http(anonymous),
        ),
        Check("rag", "embedding model ready", ready.status_code == 200, f"{_http(ready)}; {model}"),
    ]
    if ready.status_code != 200:
        return checks
    for feature in features:
        if feature.corpus_id is None:
            checks.append(
                Check("rag", f"{feature.feature_key} corpus", False, "no corpus registered")
            )
        else:
            checks.extend(_probe_corpus(client, url, headers, feature))
    return checks


def probe(
    environment: Mapping[str, str],
    *,
    client: httpx.Client | None = None,
    features: tuple[RegisteredFeature, ...] | None = None,
    output: Path | None = None,
) -> dict[str, object]:
    """Probe the already running host services and return JSON-serialisable evidence."""
    if environment.get("CI", "").lower() in {"true", "1"}:
        raise RuntimeError("Live MCP/RAG probing is local-only; CI keeps both disabled")
    resolved = host_runtime.prepare_environment(environment, mode="combined")
    registered = registered_features() if features is None else features
    urls = {service: host_runtime.local_url(service, resolved) for service in host_runtime.SERVICES}
    session = client or httpx.Client(timeout=60.0, follow_redirects=False)
    probes: dict[str, Callable[[], list[Check]]] = {
        "ai-mode": lambda: _probe_ai_mode(
            session, urls["ai-mode"], resolved["AI_MODE_SERVICE_TOKEN"]
        ),
        "mcp": lambda: _probe_mcp(session, urls["mcp"], resolved["MCP_SERVICE_TOKEN"], registered),
        "rag": lambda: _probe_rag(session, urls["rag"], resolved["RAG_SERVICE_TOKEN"], registered),
    }
    checks: list[Check] = []
    try:
        for service, run in probes.items():
            try:
                checks.extend(run())
            except httpx.HTTPError as exc:
                checks.append(
                    Check(
                        service, "reachable", False, f"{type(exc).__name__}; see `dev.py ai status`"
                    )
                )
    finally:
        if client is None:
            session.close()
    evidence: dict[str, object] = {
        "schema_version": "1.0",
        "passed": bool(checks) and all(check.passed for check in checks),
        "services": urls,
        "checks": [check.as_json() for check in checks],
    }
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    return evidence


def render(evidence: Mapping[str, object]) -> str:
    """Format probe evidence as a terminal table suitable for the report."""
    lines = ["Host AI services (not containerised):"]
    services = evidence.get("services")
    if isinstance(services, dict):
        lines.extend(f"  {name:<8} {url}" for name, url in services.items())
    lines.append("")
    checks = evidence.get("checks")
    for check in checks if isinstance(checks, list) else []:
        mark = "PASS" if check["passed"] else "FAIL"
        lines.append(f"{mark}  {check['service']:<8} {check['check']:<44} {check['detail']}")
    lines.append("")
    lines.append("All checks passed." if evidence.get("passed") else "Some checks failed.")
    return "\n".join(lines)
