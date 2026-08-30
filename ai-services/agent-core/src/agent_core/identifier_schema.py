"""Schema-aware identifier provenance helpers shared by enforcement and prompts."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from uuid import UUID

from jsonschema import Draft202012Validator, FormatChecker

from agent_core.errors import ModelOutputValidationError

IDENTIFIER_KIND_SCHEMA_KEY = "x-identifier-kind"


@dataclass(frozen=True, slots=True)
class IdentifierCandidate:
    """One UUID-shaped value and its schema-resolved, domain-neutral provenance kind."""

    kind: str | None
    value: str
    path: str
    object_key: bool = False


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


def identifier_candidates(
    value: object,
    *,
    schema: Mapping[str, object] | None,
    root_path: str = "result",
    max_candidates: int | None = None,
    max_array_items: int | None = None,
    include_ambiguous: bool = True,
) -> tuple[IdentifierCandidate, ...]:
    """Find UUID-shaped values once using the same schema walk for policy and prompts.

    A candidate with ``kind=None`` is deliberately retained so enforcement can reject an
    ambiguous UUID rather than silently treating it as ordinary text. Callers projecting a
    discovery ledger should expose only typed candidates. Bare ``id`` fields therefore require
    a feature-owned ``x-identifier-kind`` annotation; conventional ``*_id`` and ``*_ref`` names
    remain domain-neutral fallbacks.
    """
    candidates: list[IdentifierCandidate] = []
    resolver = IdentifierSchemaResolver(schema) if schema is not None else None

    def at_limit() -> bool:
        return max_candidates is not None and len(candidates) >= max_candidates

    def kind_for(
        key: str,
        current_schema: Mapping[str, object] | None,
        candidate: object,
    ) -> str | None:
        if resolver is not None and current_schema is not None:
            return resolver.kind(key, current_schema, candidate)
        normalized = key.lower()
        return normalized if normalized.endswith(("_id", "_ref")) else None

    def add(candidate: IdentifierCandidate) -> None:
        if candidate.kind is not None or include_ambiguous:
            candidates.append(candidate)

    def visit(
        candidate: object,
        *,
        path: str,
        current_schema: Mapping[str, object] | None,
        key: str = "",
    ) -> None:
        if at_limit():
            return
        if isinstance(candidate, dict):
            for child_key, nested in candidate.items():
                if at_limit():
                    return
                child_name = str(child_key)
                child_path = f"{path}.{child_name}"
                normalized_name = normalize_uuid_identifier(child_name)
                if normalized_name is not None:
                    name_schema = (
                        resolver.property_name(current_schema, candidate)
                        if resolver is not None and current_schema is not None
                        else None
                    )
                    add(
                        IdentifierCandidate(
                            kind=kind_for(child_name, name_schema, child_name),
                            value=normalized_name,
                            path=child_path,
                            object_key=True,
                        )
                    )
                    if at_limit():
                        return
                child_schema = (
                    resolver.child(current_schema, child_name, candidate)
                    if resolver is not None and current_schema is not None
                    else None
                )
                visit(
                    nested,
                    path=child_path,
                    current_schema=child_schema,
                    key=child_name,
                )
            return
        if isinstance(candidate, list):
            retained = candidate if max_array_items is None else candidate[:max_array_items]
            for index, nested in enumerate(retained):
                if at_limit():
                    return
                item_schema = (
                    resolver.item(current_schema, index, candidate)
                    if resolver is not None and current_schema is not None
                    else None
                )
                visit(
                    nested,
                    path=f"{path}[{index}]",
                    current_schema=item_schema,
                    key=key,
                )
            return
        if key == "idempotency_key":
            return
        normalized_value = normalize_uuid_identifier(candidate)
        if normalized_value is None:
            return
        add(
            IdentifierCandidate(
                kind=kind_for(key, current_schema, candidate),
                value=normalized_value,
                path=path,
            )
        )

    visit(value, path=root_path, current_schema=schema)
    return tuple(candidates)
