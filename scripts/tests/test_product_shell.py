"""Product-facing shell and cross-surface navigation checks."""

from __future__ import annotations

from pathlib import Path

from shared_contracts.feature import load_feature_manifest

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def _read(relative_path: str) -> str:
    return (REPOSITORY_ROOT / relative_path).read_text(encoding="utf-8")


def test_shared_home_is_product_facing_and_keeps_planned_areas_honest() -> None:
    page = _read("shared/frontend/index.html")
    registry = _read("shared/frontend/features.js")
    script = _read("shared/frontend/app.js")

    assert "Research a property." in page
    assert "See what is known." in page
    assert 'id="property-search-form"' in page
    assert "Build the picture around a property" in page
    assert registry.count("featureKey:") == 5
    assert registry.count("implemented: false") == 4
    assert registry.count("enabled: false") == 4
    assert 'id="feature-area-list"' in page
    assert '"Not available yet"' in script
    assert "The remaining research areas will appear here as their data becomes available." in page
    assert "Start a property review" in page
    assert 'id="operations"' in page

    for assignment_copy in (
        "FEATURE 01",
        "RELEASE 0",
        "Release roadmap",
        "Design prototype",
        "semester project",
    ):
        assert assignment_copy not in page


def test_shared_home_routes_only_live_product_and_operator_surfaces() -> None:
    page = _read("shared/frontend/index.html")
    script = _read("shared/frontend/app.js")
    registry = _read("shared/frontend/features.js")

    assert 'data-config-link="propertyDiscovery"' in page
    assert 'data-config-link="dataOperations"' in page
    assert 'data-config-link="agentRuns"' in page
    assert "docs/prototype" not in page
    assert "prototype:" not in script
    assert 'id="feature-area-list"' in page
    assert "featureRegistry(config).map(homeFeatureRow)" in script
    assert registry.count("frontendBase:") == 5
    assert registry.count("implemented: true") == 1
    assert 'frontendBase: "/features/data-platform/"' in registry
    assert "http://localhost:5005" not in page
    assert "http://localhost:5005" not in script


def test_implemented_feature_manifest_matches_browser_projection() -> None:
    manifest = load_feature_manifest(REPOSITORY_ROOT / "student-1" / "feature.yaml")
    registry = _read("shared/frontend/features.js")

    assert f'featureKey: "{manifest.feature_key}"' in registry
    assert f'owner: "{manifest.owner}"' in registry
    assert f'frontendBase: "{manifest.frontend_base_path}"' in registry


def test_shared_operational_dashboards_are_routed_without_owning_domain_data() -> None:
    page = _read("shared/frontend/index.html")
    script = _read("shared/frontend/app.js")
    status = _read("shared/frontend/routes/status.js")
    evidence = _read("shared/frontend/routes/evidence.js")
    roadmap = _read("shared/frontend/routes/roadmap.js")
    features = _read("shared/frontend/routes/features.js")
    nginx = _read("shared/frontend/nginx.conf")

    for route in ("features", "system-status", "evidence", "release-roadmap"):
        assert f'href="#{route}"' in page
        assert route in script

    assert "Data status" in status
    assert "Published datasets" in evidence
    assert "Detailed availability" in roadmap
    assert "PropertyScope research areas" in features
    assert "resolver 127.0.0.11" in nginx
    assert "proxy_pass $data_platform_upstream" in nginx
    assert "proxy_pass $ai_mode_upstream" in nginx
    assert "location /api/" in nginx
    assert "application/problem+json" in nginx
    assert "location /operations/ai-mode/" in nginx
    assert "database" not in evidence.lower()
    assert "map $http_x_request_id $correlation_request_id" in nginx
    assert '"~^[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}$"' in nginx
    assert "proxy_hide_header X-Request-ID" in nginx
    assert nginx.count("proxy_set_header X-Request-ID $correlation_request_id") == 7
    assert "add_header X-Request-ID $correlation_request_id always" in nginx
    assert '"request_id":"$correlation_request_id"' in nginx


def test_property_data_and_agent_operations_link_back_to_product_home() -> None:
    feature_page = _read("student-1/frontend/index.html")
    operations_page = _read("shared/frontend/operations/ai-mode/index.html")

    assert feature_page.count("data-product-home") >= 2
    assert "Property records" in feature_page
    assert "Property search" in feature_page
    assert "Published data" in feature_page
    assert "Property records available" in feature_page

    assert "PropertyScope | Activity history" in operations_page
    assert "Recorded AI reviews" in operations_page
    assert "Research areas" in operations_page
    assert 'meta name="color-scheme" content="light"' in operations_page
    assert "http://localhost:5100" not in operations_page
