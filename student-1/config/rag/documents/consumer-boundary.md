# Consumer contracts and database ownership

Other features obtain versioned Feature 1 artifacts and producer-owned record schemas over HTTP, then import them into their own stores. No consumer opens Feature 1's PostgreSQL database or imports Feature 1 implementation code. Each consumer validates compressed bytes, hash, gzip framing, schema and complete record count before its own atomic handoff.

Feature 1 producer publication and each consumer's accepted generation are independent. There is no distributed atomicity across feature databases. A published release may be available for download while a downstream import is pending or failed. Check the genuine consumer receipt and operation status to establish its progress.

Basis: student-1 README; data-product consumer guide, HTTP contracts; ADR-041. This guidance supplies no new Feature 4 data product or unagreed consumer behavior.
