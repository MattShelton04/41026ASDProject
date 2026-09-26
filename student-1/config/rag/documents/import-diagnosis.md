# Diagnosing a failed data update

Open the update in Update history. Before naming a cause, read which stage failed, the recorded error code and message, the progress reached and the update's scope.

## Stages fail for different reasons

- Acquisition: the publisher site could not be reached, returned an error or changed its files.
- Verification: the downloaded file did not match its expected size, format or checksum.
- Database import: records could not be loaded, for example because of an unexpected column or value.
- Data checks: the data loaded but a required check failed.
- Release build: the release file could not be written or verified.

A failure label alone does not prove a network fault, a corrupt download or a full disk. If the recorded error does not say, report that the cause is not recorded rather than guessing.

## Recovering

- Retry update or Resume update continues with the same scope.
- Use downloaded file rebuilds from the file already downloaded and verified. It skips the download, runs the import, checks and export again, and produces a new candidate.
- A failed or cancelled update never changes published data.

Do not run database commands by hand to repair an update; use these recovery actions so the history stays complete.
