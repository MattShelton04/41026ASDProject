"""Product-facing shell and cross-surface navigation checks."""

from __future__ import annotations

from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def _read(relative_path: str) -> str:
    return (REPOSITORY_ROOT / relative_path).read_text(encoding="utf-8")


def test_shared_home_is_product_facing_and_keeps_planned_areas_honest() -> None:
    page = _read("shared/frontend/index.html")

    assert "Start with the property. Follow the evidence." in page
    assert 'id="property-search-form"' in page
    assert "One journey, independently owned evidence." in page
    assert page.count("Not available yet") == 4
    assert "planned areas do not redirect into the data operations workspace." in page
    assert "Shared navigation does not mean shared domain ownership." in page
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

    assert 'data-config-link="propertyDiscovery"' in page
    assert 'data-config-link="dataOperations"' in page
    assert 'data-config-link="agentRuns"' in page
    assert "docs/prototype" not in page
    assert "prototype:" not in script
    assert page.count("data-planned=") == 4


def test_shared_operational_dashboards_are_routed_without_owning_domain_data() -> None:
    page = _read("shared/frontend/index.html")
    script = _read("shared/frontend/app.js")
    status = _read("shared/frontend/routes/status.js")
    evidence = _read("shared/frontend/routes/evidence.js")
    roadmap = _read("shared/frontend/routes/roadmap.js")
    nginx = _read("shared/frontend/nginx.conf")

    for route in ("system-status", "evidence", "release-roadmap"):
        assert f'href="#{route}"' in page
        assert route in script

    assert "Shared operations" in status
    assert "Accepted data references" in evidence
    assert "Deployment capability manifest" in roadmap
    assert "resolver 127.0.0.11" in nginx
    assert "proxy_pass $data_platform_upstream" in nginx
    assert "proxy_pass $ai_mode_upstream" in nginx
    assert "database" not in evidence.lower()


def test_property_data_and_agent_operations_link_back_to_product_home() -> None:
    feature_page = _read("student-1/frontend/index.html")
    operations_page = _read("shared/frontend/operations/ai-mode/index.html")

    assert feature_page.count("data-product-home") >= 2
    assert "Property data" in feature_page
    assert "Explore properties" in feature_page
    assert "Market, suburb, site and buyer-workspace logic lives elsewhere." in feature_page

    assert "PropertyScope | Agent activity" in operations_page
    assert "Shared operational evidence" in operations_page
    assert "Property research begins" in operations_page
    assert 'meta name="color-scheme" content="light"' in operations_page
