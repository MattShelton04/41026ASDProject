# Producer publication and downstream import

Feature 1 publishes a reviewed, verified release independently of downstream imports. Producer verification checks the immutable artifact and manifest binding and queues local activation. The activation worker verifies bytes and prepares required indexes before atomically switching the accepted generation. While Publishing, the previous accepted generation remains live.

For an external target, that same transaction creates a durable delivery outbox. The runner separately delivers the release and records the consumer's genuine receipt. Consumer rejection, unavailability or exhausted delivery retries cannot roll back producer publication. A producer verification receipt is labelled feature-1-local; it does not prove a downstream import succeeded. Inspect publication state and downstream import status separately.

Basis: ADR-041, Producer-owned publication; student-1 README, operator workflow. This project guidance describes behavior, not the current state of any release.
