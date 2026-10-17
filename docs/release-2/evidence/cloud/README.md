# Cloud deployment evidence (R2-43, R2-44, R2-45)

This folder holds the reviewed evidence of the Azure deployment, for criteria 5–7 and 9 and for
the Cloud Deployment Report Review (R2-22). Nothing here is produced by hand. Each file comes
from a deployment run and is copied in after a person has checked it.

**Current state (17 October 2026):** Azure is provisioned (*Azure for Students*,
`newzealandnorth`, `Standard_D4as_v4`; see
[deployment/azure/README.md](../../../../deployment/azure/README.md) and
[ADR-048](../../../architecture/decisions/ADR-048-azure-vm-hosting.md)). The first successful
deployment is [Cloud Deployment run 39018442663](https://github.com/MattShelton04/41026ASDProject/actions/runs/39018442663), attempt 2, on commit `ad2b443f`: the
gate passed, 21 of 21 containers ran, the smoke test passed 37 of 37 checks with the AI tier off,
and the B5 validation passed 52 checks. Automatic deployments are paused
(`AZURE_AUTO_DEPLOY=false`), and manual runs still deploy. **Nothing is copied here yet.** The
reviewed files are captured at the 20 October evidence freeze, from that run's artifacts or a
later run's. The B6 validation (`deploy.sh validate-data`) runs from a laptop, not the workflow,
and is re-run then.

## The pipeline

The brief's flow is pre-commit → GitHub Actions → post-commit endpoint tests → Docker
build/validation → `cloud-deployment.yml` → Azure. `cloud-deployment.yml` starts when
**Integration CI** completes for a push to `main` (Integration CI runs on every push), or when
someone runs it by hand. It then runs three jobs in order:

| Job | What it does | Fails when |
|---|---|---|
| `verify-ci` (*Verify CI gate*) | `scripts/verify_release_gate.py` reads the run history through `gh api` with the workflow token (`actions: read`). It does not trigger or re-run anything | Integration CI did not succeed on the deploy commit itself. Or, for any Student N CI, the latest push or manual run on `main` at the deploy commit or one of its ancestors did not succeed. A cancelled run counts as not succeeded. Runs still in progress are waited for (up to 60 minutes) |
| `build-validate` (*Docker build and validation*) | Builds every release image (the set `deploy.sh push` builds). `scripts/validate_release_images.py` then validates the Azure Compose models (`docker-compose.azure.yml` with and without the AI overlay), checks that every `${IMAGE_TAG}` image the VM pulls is built here, and records each image's ID, size and user | A Compose model is invalid, an Azure image is not built here, a built image is missing, or an image runs as root |
| `deploy` (*Deploy to Azure*) | Re-checks the gate. Then: OIDC sign-in, provision, build and push to ACR, deploy through `az vm run-command`, public smoke test, B5 validation, VM status and the deployment report. Waits for approval of the `production` environment | Any required stage or the smoke test fails |

The student workflows are path-filtered, so most commits have no run of their own for some
students. That is why the gate accepts a run at an ancestor commit: such a run tested the same
feature inputs, because no later commit up to the deploy commit changed them. The gate records
which run, commit and relation (`identical` or `ancestor`) satisfied each workflow. The workflow
is triggered once per push instead of once per student workflow, so a commit is deployed at most
once. One deployment runs at a time (job concurrency group `cloud-deployment-production`, never
cancelled).

## Workflow artifacts

| Artifact | Job | Contents |
|---|---|---|
| `release-gate-<sha>` | `verify-ci` | `release-gate.json`, `release-gate.md` (also the job's step summary) |
| `image-build-<sha>` | `build-validate` | `image-build.json`, `image-build.md` (also the step summary), `build.log` |
| `cloud-deployment-<sha>` | `deploy` | `report/cloud-deployment-report.{md,json}`, `smoke/cloud-smoke.{json,md}`, `gate/release-gate.{json,md}` (the deploy-time re-check), `logs/{provision,push,deploy,smoke}.log`, `vm-deploy.log`, `vm-status.log`, `outputs.txt`, `image-tag.txt`, `public-url.txt`, and the B5 output when present. Run-command payloads are excluded |

## Files in this folder

| File | Copied from | Contents |
|---|---|---|
| `cloud-deployment-report.md` / `.json` | `cloud-deployment-<sha>`: `report/` | The verdict, public URL, commit and image tag, workflow run and gating Integration CI run, stage outcomes, Azure outputs, VM container state, AI flag, per-owner smoke results, B5/B6 results when present, and the list of evidence files |
| `cloud-smoke.json` / `.md` | `cloud-deployment-<sha>`: `smoke/` | The smoke contract below |
| `release-gate.json` / `.md` | `cloud-deployment-<sha>`: `gate/` (or `release-gate-<sha>`) | For each of Integration CI and Student 1–5 CI: state, run number and URL, head commit, relation and detail |
| `image-build.json` / `.md` | `image-build-<sha>` | Compose models validated, the images built (ID, size, user), and any missing, unbuilt or root image |
| `logs/*.log` | `cloud-deployment-<sha>`: `logs/`, plus `build.log` from `image-build-<sha>` | Step output of provision, push, deploy, smoke and the image build |
| `vm-deploy.log` | `cloud-deployment-<sha>` | Pull, `compose up --wait`, seeded-baseline check, the `PROPERTYSCOPE_IMAGES` line (running images, pinned by digest where known) and the `PROPERTYSCOPE_RESULT` summary |
| `workflow-run.md` | person | Link to the successful *Cloud Deployment* run, its approval, and the downloaded artifact names |
| `release-decision.md` | person, after `dev.py ai review cloud` | The human release decision: approve, approve with conditions, or reject, with reasons |
| `../bonus/endpoint-security.txt`, `../bonus/data-security.txt` | `deploy.sh validate-endpoint` / `validate-data` | Bonus B5 and B6 validation output |

The review also finds `smoke/cloud-smoke.json`, `gate/release-gate.json` and
`build/image-build.json` one folder down, so you can copy the artifact folders unchanged.

### Smoke contract (`cloud-smoke.json`, schema version 2)

`scripts/cloud_smoke.py` writes this file, and `ai review cloud` reads it. The fields are listed in
full in [review-modes.md](../../review-modes.md#cloud).

- `base_url`, `started_at`, `finished_at`, `passed`, `summary` (totals and per-owner counts).
- `commit_sha`, `image_tag` and `registry` record what was deployed. The workflow passes them as
  `PROPERTYSCOPE_DEPLOY_SHA`, `IMAGE_TAG` and `ACR_LOGIN_SERVER` (CLI: `--commit-sha`,
  `--image-tag`, `--registry`).
- `images` maps each service to its image reference. With `--vm-log vm-deploy.log` (which
  `deploy.sh smoke` passes) these are the images the VM reported running, pinned by digest;
  otherwise they are derived from `IMAGE_TAG` for each `${IMAGE_TAG}` service in
  `docker-compose.azure.yml`. `images_source` says which. run-command returns only the last
  4 KiB of output; a cut-off `PROPERTYSCOPE_IMAGES` line is ignored and the derived references are
  used, so check `images_source` after the first real deploy.
- `ai_enabled` and `ai_state` record what the AI check observed. `ai_enabled` is `false` only
  for an explicit `503 ai_disabled`, and `null` when the tier was unreachable or not checked.
- `checks[]` has one entry per observation: `name`, `owner` (`shared` or `student-N`),
  `category` (`frontend`, `health`, `crud`, `cleanup`, `ai`), `operation` (for CRUD: `create`,
  `read`, `update`, `confirm-update`, `delete`, `confirm-deleted`, `cleanup-retry`, `request`),
  `passed`, `detail`, `method`, `path`, `status_code` and `duration_ms`.

Each feature's CRUD case creates a uniquely named record through that feature's public API,
reads it back, deletes it and confirms it is gone. Feature 1 also updates its source definition
(`PUT /api/data-platform/v1/sources/{id}`) and reads it again to confirm the change.

## How to capture

1. Run *Cloud Deployment* (Actions → Cloud Deployment → Run workflow), or let it follow a green
   Integration CI run on `main`. Approve the `production` environment when asked.
2. Download the `cloud-deployment-<sha>` and `image-build-<sha>` artifacts. Copy the files as the
   table above shows: `report/cloud-deployment-report.*`, `smoke/cloud-smoke.*`,
   `gate/release-gate.*`, `logs/` and `vm-deploy.log` from the first, and `image-build.*` (and
   `build.log` into `logs/`) from the second.
3. Open the public URL and take screenshots of the home page and each feature for the report
   and the video.
4. Run `uv run scripts/dev.py ai review cloud`. It writes `../reviews/cloud-review.md` and
   `cloud-validation-log.jsonl`. Then record the human decision in `release-decision.md`.

## Labelling rules

- State whether data is the **seeded demonstration baseline** (about 10 synthetic records per
  dataset) or a published real release. The report records what the VM saw.
- The AI tier is off in the required baseline. Evidence for the bonus AI tiers goes in
  `../bonus/`, never here.
- Never copy secrets, run-command payloads or `.env.azure` into this folder. The workflow artifact
  already excludes payloads, and the logs contain no secret values.
