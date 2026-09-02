"""Real AI-mode registry compatibility for Student 5-owned tools."""

from __future__ import annotations

import sys
from pathlib import Path

from ai_mode.tool_catalog import build_tool_runtime, load_tool_catalog
from shared_contracts import load_feature_manifest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts.validate_tool_catalogs import validate_catalog_ownership  # noqa: E402

CATALOG_PATH = ROOT / "student-5" / "tool-catalog.yaml"
MANIFEST_PATH = ROOT / "student-5" / "feature.yaml"
FEATURE_KEY = "student-5-buyer-journey"
EXPECTED_TOOLS = [
    "buyer.cases.inspect.v1",
    "buyer.notes.list.v1",
    "buyer.tasks.list.v1",
    "buyer.evidence.collect.v1",
]


def test_student_five_catalog_builds_real_owned_tool_runtime() -> None:
    catalog = load_tool_catalog(CATALOG_PATH)
    manifest = load_feature_manifest(MANIFEST_PATH)
    assert manifest.feature_key == FEATURE_KEY
    assert manifest.backend_base_path == "/api/buyer-workspaces/v1"
    assert manifest.onboarding is not None
    assert manifest.onboarding.backend is not None
    assert manifest.onboarding.backend.service == "f5-backend"
    assert manifest.onboarding.backend.internal_port == 5501
    assert all(item.definition.feature_key == FEATURE_KEY for item in catalog.tools)
    assert all(item.service == "f5-backend" for item in catalog.tools)
    assert all(item.path.startswith("/api/buyer-workspaces/v1/tools/") for item in catalog.tools)
    validate_catalog_ownership(catalog, manifest)
    registry, executor = build_tool_runtime(
        catalog,
        max_request_bytes=1_048_576,
        max_response_bytes=1_048_576,
    )
    try:
        visible = [definition.name for definition in registry.definitions_for(FEATURE_KEY)]
        assert visible == EXPECTED_TOOLS
        assert "property.inspect.v1" not in visible
        for name in EXPECTED_TOOLS:
            definition = registry.resolve(FEATURE_KEY, name)
            assert definition.feature_key == FEATURE_KEY
            assert definition.side_effect.value == "read_only"
            assert definition.requires_approval is False
            assert definition.input_schema["additionalProperties"] is False
            buyer_case_id = definition.input_schema["properties"]["buyer_case_id"]
            assert buyer_case_id["format"] == "uuid"
            assert buyer_case_id["x-identifier-kind"] == "buyer_case_id"
    finally:
        executor.close()
