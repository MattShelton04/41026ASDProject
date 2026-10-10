"""Product-facing shell and cross-surface navigation checks."""

from __future__ import annotations

import re
from pathlib import Path

from shared_contracts.feature import load_feature_manifest

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def _read(relative_path: str) -> str:
    return (REPOSITORY_ROOT / relative_path).read_text(encoding="utf-8")


def _token_rgb(tokens: str, name: str) -> tuple[int, int, int]:
    match = re.search(rf"{re.escape(name)}:\s*#(?P<hex>[0-9a-fA-F]{{6}})", tokens)
    assert match, f"missing six-digit colour token {name}"
    value = match.group("hex")
    return tuple(int(value[index : index + 2], 16) for index in (0, 2, 4))  # type: ignore[return-value]


def _contrast(first: tuple[int, int, int], second: tuple[int, int, int]) -> float:
    def luminance(colour: tuple[int, int, int]) -> float:
        channels = [value / 255 for value in colour]
        linear = [
            value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4
            for value in channels
        ]
        return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]

    lighter, darker = sorted((luminance(first), luminance(second)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


def test_shared_home_is_product_facing_and_keeps_planned_areas_honest() -> None:
    page = _read("shared/frontend/index.html")
    registry = _read("shared/frontend/features.js")
    enabled_registry = _read("shared/frontend/generated/enabled-features.js")
    script = _read("shared/frontend/app.js")
    fragment = _read("shared/frontend/fragments/research-areas.html")

    assert "<h1>" in page
    assert 'id="property-search-form"' in page
    assert 'aria-labelledby="research-heading"' in page
    assert registry.count('featureKey: "') == 5
    assert registry.count("implemented: false") == 4
    assert enabled_registry.count('"featureKey"') == 5
    assert 'id="feature-area-list"' in page
    assert fragment.count("Not available yet") == 0
    assert "renderHomeFeatures" not in script
    assert "planned and not available yet" not in page
    assert "ILLUSTRATION · NOT PROPERTY EVIDENCE" in page
    assert page.count('data-story-area="') == 5
    assert page.count('data-scene-target="') == 5
    assert 'style="--h:' not in page  # The deployed CSP rejects inline chart styles.
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
    enabled_registry = _read("shared/frontend/generated/enabled-features.js")
    fragment = _read("shared/frontend/fragments/research-areas.html")

    assert 'data-config-link="propertyDiscovery"' in page
    assert 'data-config-link="dataOperations"' in page
    assert 'data-config-link="agentRuns"' in page
    assert "docs/prototype" not in page
    assert "prototype:" not in script
    assert 'id="feature-area-list"' in page
    assert 'hx-get="/fragments/research-areas.html"' in page
    assert fragment.count("data-feature-id=") == 5
    assert "homeFeatureRow" not in script
    assert registry.count("frontendBase:") >= 5
    assert '"frontendBase": "/features/data-platform/"' in enabled_registry
    assert "http://localhost:5005" not in page
    assert "http://localhost:5005" not in script


def test_implemented_feature_manifest_matches_browser_projection() -> None:
    manifest = load_feature_manifest(REPOSITORY_ROOT / "student-1" / "feature.yaml")
    registry = _read("shared/frontend/generated/enabled-features.js")

    assert f'"featureKey": "{manifest.feature_key}"' in registry
    assert f'"owner": "{manifest.owner}"' in registry
    assert f'"frontendBase": "{manifest.frontend_base_path}"' in registry


def test_shared_operational_dashboards_are_routed_without_owning_domain_data() -> None:
    page = _read("shared/frontend/index.html")
    script = _read("shared/frontend/app.js")
    status = _read("shared/frontend/routes/status.js")
    evidence = _read("shared/frontend/routes/evidence.js")
    roadmap = _read("shared/frontend/routes/roadmap.js")
    features = _read("shared/frontend/routes/features.js")
    nginx = _read("shared/frontend/nginx.conf")
    enabled_nginx = _read("shared/frontend/generated/enabled-feature-routes.conf")
    complete_nginx = nginx + enabled_nginx

    for route in ("features", "system-status", "evidence", "release-roadmap"):
        assert f'href="#{route}"' in page
        assert route in script

    assert "Data status" in status
    assert "Published datasets" in evidence
    assert "Detailed availability" in roadmap
    assert "featureRegistry(config).map(featureCard)" in features
    assert "resolver 127.0.0.11" in nginx
    assert "proxy_pass $enabled_feature_0_backend" in enabled_nginx
    assert "proxy_pass $ai_mode_upstream" in nginx
    assert "set $ai_mode_upstream http://${AI_MODE_HOST}:${AI_MODE_PORT};" in nginx
    assert "upstream ai_mode_host" not in nginx
    assert "location /api/" in nginx
    assert "application/problem+json" in nginx
    assert "location /operations/ai-mode/" in nginx
    assert "location ^~ /fragments/data-platform/" in enabled_nginx
    assert "database" not in evidence.lower()
    assert "dependencies?.database" not in status
    assert 'target_feature === "feature-1"' not in evidence
    assert '"/api/data-platform/v1/dataset-releases' not in evidence
    assert "map $http_x_request_id $correlation_request_id" in nginx
    assert '"~^[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}$"' in nginx
    assert "proxy_hide_header X-Request-ID" in nginx
    assert complete_nginx.count("proxy_set_header X-Request-ID $correlation_request_id") >= 8
    assert "add_header X-Request-ID $correlation_request_id always" in nginx
    assert '"request_id":"$correlation_request_id"' in nginx
    health_routes = re.findall(r"location ~ (\^/\S+) \{", nginx)
    assert health_routes
    for invented_path in ("/health/live", "/healthz/ready", "/healthcheck"):
        assert any(re.match(route, invented_path) for route in health_routes)


def test_property_data_and_agent_operations_link_back_to_product_home() -> None:
    feature_page = _read("student-1/frontend/index.html")
    operations_page = _read("shared/frontend/operations/ai-mode/index.html")

    assert feature_page.count("data-product-home") >= 2
    assert "Property data" in feature_page
    assert "Property search" in feature_page
    assert "Published data" in feature_page
    assert "Property research</span>" in feature_page
    assert "Property records available" not in feature_page

    assert "PropertyScope | Activity history" in operations_page
    assert "Shared view · AI activity" in operations_page
    assert "Research areas" in operations_page
    assert 'meta name="color-scheme" content="light"' in operations_page
    assert "http://localhost:5100" not in operations_page


def test_design_foundation_gallery_renders_public_tokens_and_layouts() -> None:
    tokens = _read("shared/frontend/design-system/tokens.css")
    components = _read("shared/frontend/design-system/components.css")
    gallery = _read("shared/frontend/design-system/gallery.html")
    feature_app = _read("student-1/frontend/app.js")

    for token in (
        "--ps-color-background",
        "--ps-color-surface-elevated",
        "--ps-color-text-muted",
        "--ps-color-focus",
        "--ps-color-focus-inverse",
        "--ps-color-success",
        "--ps-color-warning",
        "--ps-color-danger",
        "--ps-color-disabled-surface",
        "--ps-control-height-compact",
        "--ps-control-height-comfortable",
        "--ps-page-gutter",
        "--ps-radius-lg",
        "--ps-border-width-strong",
        "--ps-shadow-md",
        "--ps-content-readable",
        "--ps-motion-normal",
        "--ps-z-drawer",
        "--ps-z-toast",
    ):
        assert token in tokens

    for primitive in (".ps-container", ".ps-cluster", ".ps-stack", ".ps-grid"):
        assert primitive in components
    for deferred in (
        ".ps-page-container",
        ".ps-inline",
        ".ps-responsive-grid",
        ".ps-section",
        ".ps-toolbar",
    ):
        assert deferred not in components

    assert "ps-density--comfortable" in gallery
    assert "ps-density--compact" in gallery
    for category in (
        "Spacing",
        "Radii, borders and elevation",
        "Widths and gutter",
        "Motion and reduced motion",
        "Layer order",
    ):
        assert category in gallery
    assert (
        'view.dataset.density = route === "properties" ? "comfortable" : "compact"' in feature_app
    )


def test_dark_headers_use_a_contrasting_inverse_focus_ring() -> None:
    tokens = _read("shared/frontend/design-system/tokens.css")
    shared_styles = _read("shared/frontend/styles.css")
    feature_styles = _read("student-1/frontend/styles.css")
    activity_styles = _read("shared/frontend/operations/ai-mode/styles.css")

    assert "--ps-color-focus-inverse: var(--ps-ocean-200)" in tokens
    assert "--ps-focus-outline-inverse: 3px solid var(--ps-color-focus-inverse)" in tokens
    assert _contrast(_token_rgb(tokens, "--ps-ocean-200"), _token_rgb(tokens, "--ps-ink-950")) >= 3
    for stylesheet in (shared_styles, feature_styles, activity_styles):
        assert ".topbar" in stylesheet
        assert "outline: var(--ps-focus-outline-inverse)" in stylesheet


def test_production_styles_do_not_use_transition_all() -> None:
    for path in (
        "shared/frontend/design-system/base.css",
        "shared/frontend/design-system/components.css",
        "shared/frontend/styles.css",
        "shared/frontend/operations/ai-mode/styles.css",
        "student-1/frontend/styles.css",
    ):
        assert "transition: all" not in _read(path).lower()


def test_every_feature_loads_the_shared_shell_without_inline_scripts() -> None:
    for number in range(1, 6):
        html = _read(f"student-{number}/frontend/index.html")
        entry = _read(f"student-{number}/frontend/shell.js")
        assert 'src="./shell.js"' in html
        assert '"./browser/index.js"' in entry
        assert "mountFeatureShell();" in entry
        assert not re.search(r"<script(?![^>]+src=)", html)


def test_shared_multi_agent_panel_is_mounted_and_copied_for_feature_1() -> None:
    import yaml

    services = yaml.safe_load(_read("docker-compose.dev.yml"))["services"]
    mount = "./shared/frontend/multi-agent:/usr/share/nginx/html/multi-agent:ro"
    assert mount in services["f1-frontend"]["volumes"]
    assert "COPY shared/frontend/multi-agent /usr/share/nginx/html/multi-agent" in _read(
        "student-1/Dockerfile"
    )
    mount_point = REPOSITORY_ROOT / "student-1/frontend/multi-agent"
    assert sorted(path.name for path in mount_point.iterdir()) == ["README.md"]


def test_shared_browser_assets_survive_development_directory_mounts() -> None:
    import yaml

    services = yaml.safe_load(_read("docker-compose.dev.yml"))["services"]
    browser_mount = "./shared/frontend/browser:/usr/share/nginx/html/browser:ro"
    for number in range(1, 6):
        assert browser_mount in services[f"f{number}-frontend"]["volumes"]
    for number in (2, 4):
        assert (REPOSITORY_ROOT / f"student-{number}/frontend/browser").is_dir()
    for service in ("f3-database", "f3-backend"):
        assert (
            "./shared/contracts/python:/app/shared/contracts/python:ro"
            in services[service]["volumes"]
        )
