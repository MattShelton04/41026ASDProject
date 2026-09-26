# Running a data update

A data update downloads a dataset from its publisher, checks it and builds a new version for review. Starting the application never starts an update; an operator starts each one.

## Steps

1. Open Data updates and choose the dataset.
2. Choose the update method. The complete source is the default. NSW sales can instead load selected archive years, which gives a partial version that cannot be published.
3. Select Preview update. PropertyScope checks the source and shows the proposed work before anything is downloaded.
4. Start the update and follow it in Update history. Updates run one at a time on a shared worker, so an update can wait behind another.
5. When it finishes, the new version appears in Published data as a candidate with its data checks.
6. Review the candidate. Required checks must pass; failed required checks cannot be bypassed. You can ask the AI to review it, then publish or reject it with a recorded reason.

## Stages in Update history

An update passes through acquisition (download), verification of the downloaded file, database import, data checks and building the release file. Each stage records its progress and any failure separately.

## While an update runs

The current published version stays in use. A candidate never appears in property search until it is published. If the page says the worker heartbeat is stale, processing may have stopped; recovery becomes available once its lease expires.

## Cancelling and retrying

Cancel update stops an update without changing published data. Retry update and Resume update continue with the same scope. Use downloaded file rebuilds from the file already downloaded and verified, skipping the download.
