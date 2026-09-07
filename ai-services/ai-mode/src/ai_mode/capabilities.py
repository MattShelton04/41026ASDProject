"""Safe runtime capability projection; optional retrieval never gates ordinary CRUD."""

import httpx

from ai_mode.configuration import Settings


def capability_snapshot(settings: Settings) -> dict[str, object]:
    services: list[dict[str, object]] = []
    for name, enabled, base_url, token in (
        ("mcp", settings.mcp_enabled, settings.mcp_server_url.removesuffix("/mcp"), settings.mcp_service_token),
        ("rag", settings.rag_enabled, settings.rag_server_url, settings.rag_service_token),
    ):
        state, detail = "disabled", "This capability is disabled in the current local mode."
        if enabled:
            try:
                response = httpx.get(base_url + "/health/ready", headers={"Authorization": f"Bearer {token}"}, timeout=1, follow_redirects=False)
                state = "ready" if response.status_code == 200 else "unavailable"
            except httpx.HTTPError:
                state = "unavailable"
            detail = "Local service is ready." if state == "ready" else "Local service is unavailable; ordinary feature records remain accessible."
        services.append({"id": name, "implemented": True, "enabled": enabled, "status": state, "detail": detail})
    return {"release": "release-1", "deployment_mode": "local", "services": services,
            "grounding_features": [feature for feature, _ in settings.rag_corpora] if settings.rag_enabled else []}
