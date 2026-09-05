# ADR-040: Keep publication recovery independent and show its current state

- Status: Accepted
- Date: 5 September 2026
- Owners: Feature 1, with explicitly coordinated Feature 3 importer changes
- Extends: ADR-028, ADR-030, ADR-033

## Context

Live publication of the 318,122-record BOCSAR product exposed several independent failures.
The stored release remains `awaiting_review` until activation succeeds, but the UI presented that
storage state even after approval had queued delivery. Old browser modules, slow record previews,
and a finite polling window further obscured current actions. The runner advanced publication only
after a source acquisition iteration, allowing lengthy acquisition/export work to starve delivery.

A producer reload interrupted a large consumer download. Feature 3 retained a permanent failed
receipt and coalesced every subsequent request back to it. Feature 1 also interpreted ordinary
HTTP 5xx control errors as terminal contract violations. A local activation retry reused the
receipt's identity as its activation key and therefore rediscovered the failed activation.

Feature 3's Python JSON Schema validation dominated measured record validation time. Its recovery
claim also deleted all staging rows in one transaction, blocking status reads and delaying lease
acquisition. These are separate from Feature 1's release state and runner failures.

## Decision

1. Keep the existing durable workflow and short publish request. External publication persists a
   producer operation, connects to a consumer operation, polls, retains its final receipt, and
   queues activation. Local publication verifies existing immutable artifact evidence and queues
   activation. Source-scale data transfer, validation and index preparation remain outside the
   browser request. Only the final accepted-pointer transaction exposes the prepared generation.
2. Run publication reconciliation in a dedicated runner thread, independent of acquisition and
   export. Both loops recover from HTTP errors. Database leases fence all phase transitions and
   permit a replacement runner to resume the same operation after restart.
   The database loader also runs a lightweight activation worker: its claim excludes datasets
   requiring search-index materialisation. Full imports and GNAF index builds stay on the serial
   bulk worker. Artifact verification and dataset-scoped atomic pointer locks remain mandatory in
   both workers. This prevents a completed consumer import waiting behind unrelated bulk work.
3. Treat HTTP 408, 429 and 5xx control responses as temporary unavailability, including non-JSON
   proxy errors. Preserve strict identity, response-size and receipt checks. Producer retries retain
   the existing five-attempt bound; an operator can resume uncertain work under a fresh request key.
4. Preserve closed receipt history. A fresh Feature 3 delivery key may create a new operation after
   a definitively failed receipt. The original key still returns its original result; active or
   accepted matching imports coalesce. An uncertain remote outcome is reconciled before a new
   download is permitted. Other consumers retain their existing replay semantics.
5. Feature 3 retries transport and pre-commit database unavailability with bounded backoff, up to
   five attempts. It retains staging for retries and expired leases. Identical ordinal/key/record
   replay succeeds; differing evidence fails. WAL allows status readers during staging writes.
   Terminal failures clear invisible staging; accepted receipt/current-pointer updates stay atomic.
6. Compile the producer-provided Draft 2020-12 schemas with `jsonschema-rs`, including format
   validation. Continue rejecting external references and enforcing provenance, semantic coverage,
   digest, gzip, byte-count, record-count and unique-key checks. No validation is sampled or skipped.
7. Use the browser's publication attempt key for local activation retries. A replay of the same
   request coalesces; a fresh retry can create a new activation after failure. Return an explicit
   failed response for terminal activation failure instead of reporting queued success.
8. Derive visible release state from release and durable publication evidence. Show `Publishing`
   during delivery/activation and `Publication failed` when it needs attention, while preserving
   the stored review lifecycle for version-checked commands. Active retries take precedence over
   historical failures. Apply the state to detail headings, lifecycle notices, previews and lists.
   Expose the persisted activation phase and last progress update so index preparation is visible.
9. Render status/actions without waiting for record previews. Reuse immutable preview evidence
   across status refreshes. Continue visible-tab polling at a slower rate after the initial window
   and refresh when the tab becomes visible. Recheck stale submit-review actions before opening a
   dialog; accept only an exact one-version review replay at the server. Revalidate frontend assets
   and version changed entry modules so an already-open installation can load the fix.
   Refresh release-list results independently of unsubmitted filter inputs. Its database API
   allowlist must admit the supported lifecycle and bounded search parameters used by that UI.

## Consequences

Queue acceptance can be immediate without implying that a 500 MB delivery or five million address
index entries are already published. The previous accepted version remains queryable during work.
Failures have explicit recovery actions and durable evidence rather than an apparently reusable
review button. A failed operation with an uncertain remote outcome may first reconcile to a closed
failure; a subsequent fresh retry then starts a new delivery. This avoids overlapping imports.

Feature 3 needs a dependency rebuild and a transactional SQLite migration from release-wide
uniqueness to uniqueness among nonfailed imports. Existing operation IDs, aliases and receipts are
preserved. Staging reuse avoids claim-time deletion but does not resume compressed downloads by
byte offset: a reclaimed stream is validated again from its beginning. WAL does not remove SQLite's
single-writer limit, and GNAF index preparation remains a source-scale PostgreSQL operation.

## Validation

Offline tests cover transient control errors, strict schema types/formats, retained failed
receipts, fresh delivery versus idempotent replay, fenced staging recovery, local activation
retry keys, independent runner progress and exact review replay. Browser tests hold a preview
request open while publication advances to accepted, and exercise a stale submit-review button.
Disposable PostgreSQL tests cover durable delivery, activation recovery and terminal receipt retry.
See [the live investigation](../../operations/publication-investigation-2026-09-05.md) for measured
behavior and release IDs.
