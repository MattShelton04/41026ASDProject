"""Workflow template discovery, loading and validation.

Templates are feature-owned manifests at ``student-N/config/multi-agent/workflow.yaml``. Like RAG
corpora, only features enabled in ``deployment/enabled-features.v1.json`` are registered, and a
manifest's ``feature_id`` must be the feature key of the slice that owns the file.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator, FormatChecker
from pydantic import ValidationError

from multi_agent_server.errors import (
    InvalidWorkflowInputError,
    TemplateNotFoundError,
    TemplateValidationError,
)
from multi_agent_server.tools import TemplateToolbox, ToolGateway
from shared_contracts import FieldIssue
from shared_contracts.multi_agent import JsonObject, WorkflowTemplate

MANIFEST_RELATIVE_PATH = Path("config") / "multi-agent" / "workflow.yaml"
PROJECTION_RELATIVE_PATH = Path("deployment") / "enabled-features.v1.json"
MAX_MANIFEST_BYTES = 262_144


@dataclass(frozen=True, slots=True)
class RegisteredTemplate:
    """A loaded template and the manifest it came from."""

    template: WorkflowTemplate
    source: str | None = None


def load_template(path: Path) -> WorkflowTemplate:
    """Parse and validate one manifest, reporting every contract issue."""
    try:
        if path.stat().st_size > MAX_MANIFEST_BYTES:
            raise TemplateValidationError(str(path), ["manifest exceeds 256 KiB"])
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise TemplateValidationError(str(path), [f"could not read manifest: {exc}"]) from exc
    if not isinstance(payload, dict):
        raise TemplateValidationError(str(path), ["manifest must be a YAML mapping"])
    try:
        return WorkflowTemplate.model_validate(payload)
    except ValidationError as exc:
        raise TemplateValidationError(
            str(path),
            [
                f"{'.'.join(str(part) for part in issue['loc']) or '<root>'}: {issue['msg']}"
                for issue in exc.errors(include_url=False)
            ],
        ) from exc


def _enabled_features(root: Path) -> list[tuple[str, str]]:
    """``(owner, feature_key)`` pairs from the generated enabled-feature projection."""
    try:
        projection = json.loads((root / PROJECTION_RELATIVE_PATH).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    pairs: list[tuple[str, str]] = []
    for feature in projection.get("features", []) if isinstance(projection, dict) else []:
        if not isinstance(feature, dict):
            continue
        owner, key = feature.get("owner"), feature.get("feature_key")
        if isinstance(owner, str) and isinstance(key, str):
            pairs.append((owner, key))
    return pairs


def discover_manifests(root: Path) -> list[tuple[Path, str]]:
    """Return ``(manifest, feature_key)`` for every enabled feature that ships a manifest."""
    return [
        (root / owner / MANIFEST_RELATIVE_PATH, key)
        for owner, key in _enabled_features(root)
        if (root / owner / MANIFEST_RELATIVE_PATH).is_file()
    ]


def owning_feature(path: Path, root: Path) -> str | None:
    """The enabled feature key whose slice contains ``path``, if any."""
    try:
        relative = path.resolve().relative_to(root.resolve())
    except ValueError:
        return None
    for owner, key in _enabled_features(root):
        if relative.parts[:1] == (owner,):
            return key
    return None


def validate_manifest(
    path: Path, *, gateway: ToolGateway | None, root: Path | None = None
) -> tuple[WorkflowTemplate | None, list[str]]:
    """Full validation used by the CLI and server start-up.

    Checks the contract, that the manifest belongs to the feature it names (when it lives in an
    enabled feature slice under ``root``), and, when tool definitions are available, that every
    allowlisted tool is registered, read-only, approval-free and owned by that feature.
    """
    try:
        template = load_template(path)
    except TemplateValidationError as exc:
        return None, exc.issues
    issues: list[str] = []
    if root is not None:
        owner = owning_feature(path, root)
        if owner is not None and owner != template.feature_id:
            issues.append(
                f"feature_id {template.feature_id} does not match the owning feature {owner}"
            )
    if gateway is not None:
        issues.extend(TemplateToolbox(template, gateway).template_issues())
    return template, issues


class TemplateRegistry:
    """Immutable set of registered templates, keyed by template ID."""

    def __init__(
        self, templates: Iterable[RegisteredTemplate], *, invalid: Iterable[str] = ()
    ) -> None:
        self._templates: dict[str, RegisteredTemplate] = {}
        for entry in templates:
            if entry.template.id in self._templates:
                raise ValueError(f"duplicate workflow template id: {entry.template.id}")
            self._templates[entry.template.id] = entry
        self.invalid = tuple(invalid)

    @classmethod
    def from_paths(
        cls,
        paths: Iterable[Path],
        *,
        root: Path | None = None,
        expected_features: Mapping[Path, str] | None = None,
    ) -> TemplateRegistry:
        """Load manifests; an invalid manifest is reported, never fatal for the others.

        Tool availability is not checked here: it depends on the running tool transport and is
        reported per template by the API instead (``tools[].available``).
        """
        loaded: list[RegisteredTemplate] = []
        invalid: list[str] = []
        seen: set[str] = set()
        for path in paths:
            template, issues = validate_manifest(path, gateway=None, root=root)
            expected = (expected_features or {}).get(path)
            if template is not None and expected is not None and template.feature_id != expected:
                issues.append(f"feature_id {template.feature_id} does not match {expected}")
            if template is not None and template.id in seen:
                issues.append(f"duplicate workflow template id {template.id}")
            if template is None or issues:
                invalid.append(f"{_display(path, root)}: {'; '.join(issues)}")
                continue
            seen.add(template.id)
            loaded.append(RegisteredTemplate(template, _display(path, root)))
        loaded.sort(key=lambda entry: (entry.template.feature_id, entry.template.id))
        return cls(loaded, invalid=invalid)

    def all(self) -> tuple[RegisteredTemplate, ...]:
        """Every registered template in stable feature/template order."""
        return tuple(self._templates.values())

    def get(self, template_id: str) -> RegisteredTemplate:
        """Return one template or raise a structured 404."""
        try:
            return self._templates[template_id]
        except KeyError as exc:
            raise TemplateNotFoundError(
                f"Workflow template {template_id} is not registered"
            ) from exc


def validate_input(template: WorkflowTemplate, values: JsonObject) -> JsonObject:
    """Validate run input against the template's closed schema and apply no defaults."""
    validator = Draft202012Validator(template.input_schema(), format_checker=FormatChecker())
    issues = tuple(
        FieldIssue(
            field=".".join(str(part) for part in error.absolute_path) or "input",
            message=error.message[:500],
            code=str(error.validator),
        )
        for error in sorted(validator.iter_errors(values), key=lambda item: list(item.path))
    )
    if issues:
        raise InvalidWorkflowInputError(
            "Workflow input does not satisfy the template's input schema", errors=issues[:20]
        )
    return values


def _display(path: Path, root: Path | None) -> str:
    if root is not None:
        try:
            return path.resolve().relative_to(root.resolve()).as_posix()
        except ValueError:
            pass
    return path.as_posix()
