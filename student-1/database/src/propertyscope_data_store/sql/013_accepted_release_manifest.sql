-- Candidate-only wording must not survive reviewed publication.
UPDATE ops.dataset_release
SET manifest_json = jsonb_set(
        manifest_json,
        '{known_limitations}',
        to_jsonb(ARRAY[
            'Bounded accepted release; use only within the declared coverage'
        ]::text[]),
        true
    ),
    updated_at = CURRENT_TIMESTAMP,
    version = version + 1
WHERE status = 'accepted'
  AND manifest_json->'known_limitations' @> '["Candidate evidence; not accepted product data"]'::jsonb;
