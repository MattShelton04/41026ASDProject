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
| `vm-deploy.log` | `cloud-deployment-<sha>` | Pull, `compose up --wait`, accepted-release check, the `PROPERTYSCOPE_IMAGES` line (running images, pinned by digest where known) and the `PROPERTYSCOPE_RESULT` summary |
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
  `passed`, `skipped`, `detail`, `method`, `path`, `status_code` and `duration_ms`. `skipped`
  marks a case whose precondition lies outside the deployment: Features 2 and 4 accept a record
  only for a property Feature 1 has published, so before the first cloud G-NAF release their CRUD
  cases are skipped with that reason and the deployment still passes.

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
   and the video, then take the Azure portal screenshots below.
4. Run `uv run scripts/dev.py ai review cloud`. It writes `../reviews/cloud-review.md` and
   `cloud-validation-log.jsonl`. Then record the human decision in `release-decision.md`.

## Azure portal screenshots

These show the provisioned resources and their security settings as Azure itself reports them,
which the CLI logs cannot. Save them in `portal/` with these names. The report uses a 2×3 montage
of 01, 04, 08, 10, 12 and 13; the rest stay here as supporting evidence. Take them while the VM is
running and after a successful *Cloud Deployment*.

| File | Portal page | What must be visible | Criteria |
|---|---|---|---|
| `portal/01-resource-group.png` | Resource group `rg-propertyscope-prod` → Overview | Every resource with its type, region `newzealandnorth`, the tags | C5, C9 |
| `portal/02-deployments.png` | Resource group → Settings → Deployments | `propertyscope-main` and its module deployments, all *Succeeded* | C5 |
| `portal/03-activity-log.png` | Resource group → Activity log, filtered to *Run Command on Virtual Machine* and *Start Virtual Machine* | Operations by the GitHub deployer identity at the deployment time | C6 |
| `portal/04-vm-overview.png` | VM `propertyscope-prod-vm` → Overview | *Running*, `Standard_D4as_v4`, Ubuntu 24.04, public IP and DNS name | C7 |
| `portal/05-vm-security.png` | VM → Settings → Configuration (Security type) | Trusted Launch, secure boot, vTPM, encryption at host | B6 |
| `portal/06-vm-identity.png` | VM → Security → Identity → Azure role assignments | System-assigned identity on; AcrPull and Key Vault Secrets User | B6 |
| `portal/07-disk-networking.png` | Disk `propertyscope-prod-vm-osdisk` → Networking | Network access *Deny all* (no export) | B6 |
| `portal/08-nsg-inbound.png` | NSG `propertyscope-prod-nsg` → Inbound security rules | Only 443 and 80 allowed, everything else denied; no 22, 5432 or AI ports | B5 |
| `portal/09-subnet.png` | VNet `propertyscope-prod-vnet` → Subnets → `app` | NSG attached, `Microsoft.KeyVault` service endpoint | B5, B6 |
| `portal/10-acr-tags.png` | Container registry → Repositories → `propertyscope/f1-backend` | Tags are commit SHAs | C6 |
| `portal/11-acr-access.png` | Container registry → Settings → Access keys | Admin user disabled | B6 |
| `portal/12-key-vault.png` | Key Vault → Access configuration, Networking and Secrets | Azure RBAC, purge protection, selected networks with the VNet rule, secret **names** | B6 |
| `portal/13-federated-credentials.png` | Managed identities → deployer and `propertyscope-github-operations` → Federated credentials | GitHub issuer, environments `production` and `operations` | C6, B6 |
| `portal/14-rg-access.png` | Resource group → Access control (IAM) → Role assignments | Deployer: Contributor and the conditioned RBAC Administrator (open the condition) | B6 |
| `portal/15-vm-metrics.png` (optional) | VM → Monitoring → Metrics | CPU and network during a smoke run or data collection | C7 |

Rules for these screenshots:

- Never open a secret's value. Show the list of names only.
- The Key Vault firewall denies the portal unless the browser's public IP is allowed. Add it
  for the capture (`az keyvault network-rule add`), then remove it. The next `provision` also
  removes it.
- Crop or blur the subscription ID and tenant ID. Resource names and the public URL may stay.
- JIT, Defender plans, Log Analytics, Backup and Bastion are not part of this deployment.
  Do not imply they are. TLS, HSTS, the site login and rate limits live in Caddy and nginx on
  the VM, so `endpoint-security.txt` is their evidence, not the portal.

## Labelling rules

- The cloud holds no demonstration data (ADR-048, 18 October amendment): name the real releases
  that were published there, or say that none were. The report records what the VM saw.
- The AI tier is off in the required baseline. Evidence for the bonus AI tiers goes in
  `../bonus/`, never here.
- Never copy secrets, run-command payloads or `.env.azure` into this folder. The workflow artifact
  already excludes payloads, and the logs contain no secret values.
