# Recover publication and downstream delivery separately

Inspect the current release state, local activation status and retained failure evidence before selecting recovery. Retry publication retries failed local activation with a fresh attempt key and retains earlier receipts. It is not the same as retrying a consumer import.

For an already published release, Retry downstream import resumes failed delivery separately. A delivery failure does not unpublish the release or replace the producer's accepted generation. Producer verification receipts and consumer receipts attest different operations. Do not infer success from a queued request or a historical accepted receipt without checking the current operation.

Accepted artifacts cannot be edited in place. Corrections require a new release; recovery preserves immutable evidence. AI review and read-only assistant explanations do not authorize publication.

Basis: student-1 README, operator workflow; ADR-040 as amended by ADR-041; ADR-042.
