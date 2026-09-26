# Publishing a version

Publishing makes a reviewed candidate the current version of its dataset.

## Before publishing

The candidate must have passed its required data checks. Review its record count, coverage and differences from the currently published version on the Published data page. An AI review can help but does not approve anything; an operator decides.

## What happens when you publish

1. PropertyScope checks that the release file and its manifest still match (record count and SHA-256 checksum).
2. The version is marked as publishing and a background worker prepares it: it re-checks the file and builds the search indexes.
3. The current version switches to the new one in a single step. The previous version stays in use until that moment and then becomes superseded.

If step 1 or 2 fails, nothing changes for users; Retry publication starts a fresh attempt.

## Other research areas

Publishing does not wait for other research areas. Where a dataset is delivered to another feature, that feature's import runs afterwards and is reported separately. A failed downstream import does not unpublish the version. Check publication status and downstream import status separately.
