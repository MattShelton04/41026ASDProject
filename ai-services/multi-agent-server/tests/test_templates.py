"""Template loading, validation, input checking and versioned prompts."""

from __future__ import annotations

from pathlib import Path

import pytest

from multi_agent_server.errors import (
    InvalidWorkflowInputError,
    TemplateNotFoundError,
    TemplateValidationError,
)
from multi_agent_server.prompts import CURRENT_PROMPT_VERSIONS, PromptError, PromptRegistry
from multi_agent_server.templates import (
    RegisteredTemplate,
    TemplateRegistry,
    load_template,
    owning_feature,
    validate_input,
    validate_manifest,
)

FIXTURES = Path(__file__).parent / "fixtures"
TEMPLATE = FIXTURES / "workflow.yaml"
RECORD_ID = "8c0d7e0e-4a3b-4c55-9a62-0d7c5f0f9a11"


@pytest.mark.parametrize(
    ("content", "issue"),
    [
        ("- a list", "manifest must be a YAML mapping"),
        ("key: [unclosed", "could not read manifest"),
        ("schema_version: 1\nid: Bad Id\n", "id:"),
    ],
)
def test_load_template_reports_issues(tmp_path: Path, content: str, issue: str) -> None:
    path = tmp_path / "workflow.yaml"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(TemplateValidationError) as error:
        load_template(path)
    assert any(issue in item for item in error.value.issues)


def test_missing_and_oversized_manifests(tmp_path: Path) -> None:
    with pytest.raises(TemplateValidationError, match="could not read"):
        load_template(tmp_path / "missing.yaml")
    huge = tmp_path / "huge.yaml"
    huge.write_text("x: " + "y" * 300_000, encoding="utf-8")
    with pytest.raises(TemplateValidationError) as error:
        load_template(huge)
    assert error.value.issues == ["manifest exceeds 256 KiB"]


def test_owning_feature_uses_the_enabled_projection(tmp_path: Path) -> None:
    assert owning_feature(TEMPLATE, tmp_path) is None
    projection = tmp_path / "deployment" / "enabled-features.v1.json"
    projection.parent.mkdir()
    projection.write_text("not json", encoding="utf-8")
    manifest = tmp_path / "student-9" / "workflow.yaml"
    assert owning_feature(manifest, tmp_path) is None
    projection.write_text(
        '{"features": [1, {"owner": "student-9", "feature_key": "other"}]}', encoding="utf-8"
    )
    manifest.parent.mkdir()
    manifest.write_text(TEMPLATE.read_text(encoding="utf-8"), encoding="utf-8")
    assert owning_feature(manifest, tmp_path) == "other"
    template, issues = validate_manifest(manifest, gateway=None, root=tmp_path)
    assert template is not None
    assert issues == ["feature_id example-feature does not match the owning feature other"]


def test_registry_rejects_duplicates_and_reports_invalid(tmp_path: Path) -> None:
    broken = tmp_path / "broken.yaml"
    broken.write_text("[]", encoding="utf-8")
    registry = TemplateRegistry.from_paths([TEMPLATE, TEMPLATE, broken])

    assert len(registry.all()) == 1
    assert registry.invalid[0].endswith("duplicate workflow template id example-readiness-review")
    assert "manifest must be a YAML mapping" in registry.invalid[1]
    with pytest.raises(TemplateNotFoundError):
        registry.get("unknown")
    template = registry.all()[0].template
    with pytest.raises(ValueError, match="duplicate"):
        TemplateRegistry([RegisteredTemplate(template), RegisteredTemplate(template)])


def test_expected_feature_mismatch_is_invalid() -> None:
    registry = TemplateRegistry.from_paths([TEMPLATE], expected_features={TEMPLATE: "other"})
    assert registry.all() == ()
    assert "does not match other" in registry.invalid[0]


def test_validate_input_is_closed_and_typed() -> None:
    template = load_template(TEMPLATE)
    assert validate_input(template, {"record_id": RECORD_ID}) == {"record_id": RECORD_ID}
    with pytest.raises(InvalidWorkflowInputError) as error:
        validate_input(template, {"record_id": "nope", "extra": 1})
    fields = {issue.field for issue in error.value.errors}
    assert fields == {"input", "record_id"}


def test_prompts_are_versioned_and_hashed() -> None:
    registry = PromptRegistry()
    for role, version in CURRENT_PROMPT_VERSIONS.items():
        prompt = registry.current(role)
        assert (prompt.prompt_id, prompt.version, prompt.role) == (role, version, role)
        assert len(prompt.content_hash) == 64
        assert "JSON" in prompt.content
    assert registry.current("planner") is registry.load("planner", "v1")
    with pytest.raises(PromptError, match="could not load prompt planner/v9"):
        registry.load("planner", "v9")


def write_prompt(root: Path, meta: str, template: str | None = "System text") -> PromptRegistry:
    directory = root / "planner"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "v1.meta.yaml").write_text(meta, encoding="utf-8")
    if template is not None:
        (directory / "v1.system.md").write_text(template, encoding="utf-8")
    return PromptRegistry(root)


META = "prompt_id: {id}\nversion: v1\nrole: planner\ntemplate: {template}\ndescription: d\n"


@pytest.mark.parametrize(
    ("meta", "template", "message"),
    [
        (META.format(id="worker", template="v1.system.md"), "x", "does not match"),
        (META.format(id="planner", template=".."), "x", "escapes its directory"),
        (
            META.format(id="planner", template="v1.system.md"),
            None,
            "could not load prompt template",
        ),
        (META.format(id="planner", template="v1.system.md"), "  ", "cannot be empty"),
    ],
)
def test_prompt_assets_are_validated(
    tmp_path: Path, meta: str, template: str | None, message: str
) -> None:
    with pytest.raises(PromptError, match=message):
        write_prompt(tmp_path, meta, template).load("planner", "v1")
