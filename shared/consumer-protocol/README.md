# Shared consumer protocol

This package provides the domain-neutral consumer half of a publication protocol. It deliberately
contains no product records or feature rules. Producers continue to own their manifests and record
schemas; consumers supply validators for those extensions.

The helper enforces a small transport contract:

- immutable release identity is checked across the callback and manifest;
- the producer origin is configuration, while the artifact path must exactly match a configured
  release-bound template;
- redirects are rejected and compressed, expanded, line and record limits are mandatory;
- gzip-NDJSON is streamed using raw HTTP bytes, with duplicate keys, non-finite numbers and blank
  records rejected;
- the compressed byte count, SHA-256 digest and record count must match before commit;
- correlation and producer delivery-idempotency values are forwarded, never generated;
- the consumer supplies its own already-persisted operation ID, which remains distinct from the
  immutable release ID and producer delivery attempt; and
- receipts are closed models and can be replayed only when all immutable evidence matches.

## Atomic import contract

Implement `AtomicImportSink` with a consumer-owned transaction or disposable staging area.
`begin` reserves the supplied operation, `stage` must keep rows invisible, `commit` must atomically
persist the verified evidence and expose the complete candidate, and `rollback` removes all staged
state. The helper calls `commit` only after the entire artifact has passed transport, gzip, digest,
count, manifest and record-schema validation. Failures during `begin`, download, validation or
`stage` are known to precede commit, so the helper calls `rollback`. A rollback failure is reported
as `atomic_rollback_failed` while retaining both the original import error and cleanup exception.

Calling `commit` is the durable-outcome uncertainty boundary. Once that call begins, the helper
never calls `rollback`: the database may have committed immediately before returning an exception,
and cleanup could destroy or contradict accepted state. Any exception from `commit` is surfaced as
the retryable `atomic_commit_outcome_unknown` error, with the original exception retained. This
does not authorize blind re-import; retryable means that operation-status reconciliation may be
retried safely.

The caller must reconcile an uncertain database commit using its persisted consumer operation ID;
the helper does not fabricate an ID or infer success from a transport retry. Before re-downloading,
the consumer may use `ImportReceipt.reconciles(...)` to accept an existing receipt only when the
genuine consumer operation ID plus release, dataset, target, schema, checksum and record-count
evidence all match. `ImportReceipt.matches(...)` remains available for immutable release-only
comparisons, but is insufficient by itself to resolve an uncertain operation.

## Integration

Add `shared/consumer-protocol` to the uv workspace, add `shared-consumer-protocol` to the consuming
service dependency list, and register it as a workspace source. Update the root Ruff, mypy and
coverage source lists so this package and its tests run in the canonical gate. Make dependency and
lock changes with `uv add`; do not edit `uv.lock` manually.

The tests start an ephemeral loopback HTTP server and require no internet, credentials, database or
Docker stack.
