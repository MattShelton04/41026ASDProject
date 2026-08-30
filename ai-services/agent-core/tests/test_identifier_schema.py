"""Domain-neutral tests for schema-aware identifier provenance traversal."""

from agent_core import IdentifierCandidate, identifier_candidates


def test_identifier_candidates_keep_ambiguous_values_for_fail_closed_policy() -> None:
    typed = "a0000000-0000-0000-0000-000000000001"
    ambiguous = "a0000000-0000-0000-0000-000000000002"

    assert identifier_candidates(
        {"entity": {"id": typed}, "opaque": ambiguous},
        schema={
            "type": "object",
            "properties": {
                "entity": {
                    "type": "object",
                    "properties": {
                        "id": {
                            "type": "string",
                            "format": "uuid",
                            "x-identifier-kind": "entity_ref",
                        }
                    },
                },
                "opaque": {"type": "string", "format": "uuid"},
            },
        },
    ) == (
        IdentifierCandidate(
            kind="entity_ref",
            value=typed,
            path="result.entity.id",
        ),
        IdentifierCandidate(
            kind=None,
            value=ambiguous,
            path="result.opaque",
        ),
    )


def test_identifier_candidates_apply_neutral_fallbacks_and_normalize_values() -> None:
    canonical = "a0000000-0000-0000-0000-000000000003"

    assert identifier_candidates(
        {
            "subject_ref": canonical.replace("-", ""),
            "id": canonical,
            "idempotency_key": canonical,
        },
        schema=None,
        include_ambiguous=False,
    ) == (
        IdentifierCandidate(
            kind="subject_ref",
            value=canonical,
            path="result.subject_ref",
        ),
    )


def test_identifier_candidates_type_uuid_object_keys_from_property_names() -> None:
    entity_ref = "a0000000-0000-0000-0000-000000000004"

    assert identifier_candidates(
        {"entities": {entity_ref: True}},
        schema={
            "type": "object",
            "properties": {
                "entities": {
                    "type": "object",
                    "propertyNames": {"x-identifier-kind": "entity_ref"},
                }
            },
        },
    ) == (
        IdentifierCandidate(
            kind="entity_ref",
            value=entity_ref,
            path=f"result.entities.{entity_ref}",
            object_key=True,
        ),
    )
