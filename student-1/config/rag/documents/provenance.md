# Release provenance and artifact verification

Accepted manifests and artifacts are immutable. Corrections produce new releases with supersession references. Record the dataset and release identifiers, source scope, schema, checksum, record count and accepted generation when explaining provenance. Never present a candidate artifact as accepted data.

Current release exports are gzip-compressed UTF-8 NDJSON. SHA-256 and byte_count describe the exact compressed downloadable bytes; record_count counts decompressed nonempty records. Consumers discover producer-owned schemas through the product-contracts/v1 HTTP resource and its digest-bound ZIP, then validate the artifact before their own atomic import. A download alone is not evidence that a consumer accepted it.

Basis: student-1 README and data-product consumer guide, framing, hashes and contract discovery. Source dates, corpus ingestion time and operational release timestamps have distinct meanings.
