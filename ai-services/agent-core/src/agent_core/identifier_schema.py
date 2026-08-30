"""Schema-aware identifier provenance helpers shared by enforcement and prompts."""

from __future__ import annotations

import re
from collections.abc import Mapping
from uuid import UUID

from jsonschema import Draft202012Validator, FormatChecker

from agent_core.errors import ModelOutputValidationError

IDENTIFIER_KIND_SCHEMA_KEY = "x-identifier-kind"


def normalize_uuid_identifier(value: object) -> str | None:
    """Return canonical UUID text for every representation accepted by UUID parsers."""
    if not isinstance(value, str):
        return None
    try:
        return str(UUID(value))
    except ValueError:
        return None


class IdentifierSchemaResolver:
    """Resolve the effective identifier schema for one concrete JSON value path."""

    def __init__(self, root: Mapping[str, object]) -> None:
        self._root = root
        self._validator = Draft202012Validator(root, format_checker=FormatChecker())

    def kind(self, key: str, schema: Mapping[str, object], value: object) -> str | None:
        """Return one unambiguous declared or conventional identifier kind."""
        declared_kinds = {
            declared
            for node in self._nodes(schema, value)
            if isinstance((declared := node.get(IDENTIFIER_KIND_SCHEMA_KEY)), str) and declared
        }
        if len(declared_kinds) > 1:
            raise ModelOutputValidationError(
                f"tool identifier schema declares conflicting kinds for {key or '<value>'}"
            )
        if declared_kinds:
            return next(iter(declared_kinds))
        normalized = key.lower()
        if normalized.endswith(("_id", "_ref")):
            return normalized
        return None

    def child(
        self, schema: Mapping[str, object], key: str, instance: object
    ) -> Mapping[str, object]:
        """Select only property schemas applicable to this key and parent instance."""
        selected: list[Mapping[str, object]] = []
        for node in self._nodes(schema, instance):
            evaluated = False
            properties = node.get("properties")
            if isinstance(properties, Mapping) and key in properties:
                evaluated = True
                child = properties[key]
                if isinstance(child, Mapping):
                    selected.append(child)
            patterns = node.get("patternProperties")
            if isinstance(patterns, Mapping):
                for pattern, child in patterns.items():
                    if not isinstance(pattern, str):
                        continue
                    try:
                        matches = re.search(pattern, key) is not None
                    except re.error as exc:
                        raise ModelOutputValidationError(
                            "tool identifier schema contains an invalid property pattern"
                        ) from exc
                    if matches:
                        evaluated = True
                        if isinstance(child, Mapping):
                            selected.append(child)
            additional = node.get("additionalProperties")
            if not evaluated and isinstance(additional, Mapping):
                selected.append(additional)
        return self._combine(selected)

    def item(
        self, schema: Mapping[str, object], index: int, instance: object
    ) -> Mapping[str, object]:
        """Select the prefix or trailing item schema applicable at this index."""
        selected: list[Mapping[str, object]] = []
        for node in self._nodes(schema, instance):
            prefix_items = node.get("prefixItems")
            if isinstance(prefix_items, list) and index < len(prefix_items):
                item = prefix_items[index]
                if isinstance(item, Mapping):
                    selected.append(item)
            else:
                item = node.get("items")
                if isinstance(item, Mapping):
                    selected.append(item)
        return self._combine(selected)

    def property_name(self, schema: Mapping[str, object], instance: object) -> Mapping[str, object]:
        """Select schemas that constrain object member names."""
        selected = [
            property_names
            for node in self._nodes(schema, instance)
            if isinstance((property_names := node.get("propertyNames")), Mapping)
        ]
        return self._combine(selected)

    @staticmethod
    def _combine(selected: list[Mapping[str, object]]) -> Mapping[str, object]:
        if not selected:
            return {}
        if len(selected) == 1:
            return selected[0]
        return {"allOf": selected}

    def _resolve(
        self, schema: Mapping[str, object], *, seen: frozenset[str] = frozenset()
    ) -> Mapping[str, object]:
        reference = schema.get("$ref")
        if not isinstance(reference, str) or not reference.startswith("#/"):
            return schema
        if reference in seen or len(seen) >= 20:
            raise ModelOutputValidationError("tool identifier schema contains a cyclic $ref")
        target: object = self._root
        for raw_part in reference[2:].split("/"):
            part = raw_part.replace("~1", "/").replace("~0", "~")
            if not isinstance(target, Mapping) or part not in target:
                raise ModelOutputValidationError(
                    f"tool identifier schema has an unresolved local $ref: {reference}"
                )
            target = target[part]
        if not isinstance(target, Mapping):
            raise ModelOutputValidationError(
                f"tool identifier schema $ref is not an object: {reference}"
            )
        resolved = self._resolve(target, seen=seen | {reference})
        siblings = {key: value for key, value in schema.items() if key != "$ref"}
        return {"allOf": [resolved, siblings]} if siblings else resolved

    def _nodes(
        self, schema: Mapping[str, object], instance: object
    ) -> tuple[Mapping[str, object], ...]:
        resolved = self._resolve(schema)
        nodes: list[Mapping[str, object]] = [resolved]
        for keyword in ("allOf", "anyOf", "oneOf"):
            branches = resolved.get(keyword)
            if not isinstance(branches, list):
                continue
            for branch in branches:
                if not isinstance(branch, Mapping):
                    continue
                if keyword != "allOf" and not self._validator.evolve(schema=branch).is_valid(
                    instance
                ):
                    continue
                nodes.extend(self._nodes(branch, instance))
        condition = resolved.get("if")
        if isinstance(condition, Mapping):
            condition_matches = self._validator.evolve(schema=condition).is_valid(instance)
            selected = resolved.get("then" if condition_matches else "else")
            if isinstance(selected, Mapping):
                nodes.extend(self._nodes(selected, instance))
        return tuple(nodes)
