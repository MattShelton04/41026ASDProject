-- Keep canonical and alias search documents punctuation-neutral so the same NSW address
-- is found whether a user includes commas, slashes or other display punctuation.
UPDATE registry.property
SET address_search = trim(regexp_replace(lower(address_display), '[^a-z0-9]+', ' ', 'g'))
WHERE address_search IS DISTINCT FROM
      trim(regexp_replace(lower(address_display), '[^a-z0-9]+', ' ', 'g'));

UPDATE registry.address_alias
SET alias_search = trim(regexp_replace(lower(alias_display), '[^a-z0-9]+', ' ', 'g'))
WHERE alias_search IS DISTINCT FROM
      trim(regexp_replace(lower(alias_display), '[^a-z0-9]+', ' ', 'g'));
