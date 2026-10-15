# CI endpoint-test evidence

This directory holds one `student-N.md` per feature (checklist item F-8, requirement R2-33).
Each file records a successful `student-N.yml` run on `main` that executed the feature's
endpoint tests against the running Compose stack.

## How a file is produced

1. The feature's `student-N.yml` runs `student-N/tests/endpoints` with
   `PROPERTYSCOPE_ENDPOINT_BASE_URL` set, writes JUnit XML, appends a Markdown table to the run's
   step summary and uploads the `student-N-endpoint-tests` artifact. The shared helper and the
   workflow snippet are in [`shared/testkit/README.md`](../../../../shared/testkit/README.md).
2. After a green run on `main` that includes the feature's final change, run from the
   repository root (needs an authenticated `gh`):

   ```text
   uv run python scripts/collect_ci_evidence.py --student N
   ```

   The script finds the newest successful `student-N.yml` run on `main`, reads its metadata
   with `gh run view`, downloads the endpoint artifact with `gh run download`, and writes
   `student-N.md` with:

   - the run URL, number, attempt, head SHA, branch, event, status and conclusion;
   - created, started and updated timestamps;
   - every job and step with its conclusion;
   - one table per JUnit report: test, outcome, duration and failure message;
   - links to the retained raw reports and run log below.

   It also writes `student-N/`, replacing what a previous run left there:

   - the raw JUnit XML files from the artifact (the CI test reports);
   - `run.log`, the log of the job that ran the endpoint tests (`gh run view --job ID --log`),
     reduced to the steps whose names mention "endpoint" (the whole job log if `gh` cannot
     name the steps), without ANSI colour codes, with any line that matches a secret pattern
     redacted, and capped at the final 512 KiB.

   GitHub deletes artifacts after 30 days and run logs after 90, so these copies are the
   retained evidence. `.gitignore` ignores `*.log` and `logs/` elsewhere but not under
   `docs/release-*/evidence/`.

3. Commit the regenerated files. Do not edit them by hand; re-run the script instead.
4. Run `uv run scripts/dev.py ai review testing --deterministic`. Every `ci.student-N.*` check
   for the recorded students should pass, including the advisory `ci.student-N.log`.

Options:

| Option | Use |
|---|---|
| `--student N` (repeatable) or `--all` | Which workflows to record |
| `--run-id ID` | Record a specific run (with exactly one `--student`); the run must belong to that workflow |
| `--branch NAME` | Search a branch other than `main` |
| `--repo OWNER/REPO` | Query a repository other than the current checkout's |
| `--output-dir PATH` | Write somewhere other than this directory |
| `--allow-failed-endpoints` | Write the file even when the artifact is missing or a test failed. Without it the script refuses, so only fully green runs become evidence |

The script only reads from GitHub. It never triggers, re-runs or cancels a workflow.
