# Retrying publication and downstream imports

Two different things can fail after an operator publishes a version. Check which one before retrying.

## Retry publication

Use this when publishing itself failed, before the new version became current. The previous version is still in use. The retry starts a fresh attempt and keeps the records of earlier attempts.

## Retry downstream import

Use this when the version is already published but another research area failed to import it. It resumes delivery to that feature only. It does not unpublish the version or change what Property data serves.

## Before retrying

Read the current status of the version and of each downstream import. A queued request or an older successful receipt does not show that the latest attempt succeeded.

## Corrections

Published versions are never edited. To fix published data, run a new update and publish the new version; the old one is kept as superseded.
