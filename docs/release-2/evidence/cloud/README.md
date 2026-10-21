# Cloud deployment evidence (R2-43, R2-44, R2-45)

This folder holds the reviewed evidence of the Azure deployment, for criteria 5–7 and 9 and for
the Cloud Deployment Report Review (R2-22). Nothing here is produced by hand. Each file comes
from a deployment run and is copied in after a person has checked it.

**Current state (18 October 2026): AI-off baseline captured.** Azure is provisioned (*Azure for
Students*, `newzealandnorth`, `Standard_D4as_v4`; see
[deployment/azure/README.md](../../../../deployment/azure/README.md) and
[ADR-048](../../../architecture/decisions/ADR-048-azure-vm-hosting.md)). The files in this folder
come from [Cloud Deployment run 39112162750](https://github.com/MattShelton04/41026ASDProject/actions/runs/39112162750)
on `main` at `3c25c083`, dispatched by hand and approved for `production` on 18 October
(deploy 08:47 UTC, smoke 08:49 UTC):

| Check | Result |
|---|---|
| Release gate | Passed: Integration CI #424 and Student 1–5 CI all `success` at the deployed commit (`identical`) |
| Image build | 18 images built and validated, none running as root |
| VM | 21 of 21 containers running, every image pinned by digest, cloud AI flag `false`, host AI units inactive |
| Public smoke test | **37 of 37 passed, 0 skipped, 0 failed**; full CRUD for all five features; AI-mode answered `503 ai_disabled` |
| B5 endpoint security | 54 of 54 lines without failure (52 PASS, 2 INFO) |
| B6 data security | 43 PASS, 0 FAIL (16 control-plane, 27 on-host), run from a laptop at 08:55 UTC |
| Cloud review | `pass`, 18 of 18 checks (deterministic engine), [`../reviews/cloud-review.md`](../reviews/cloud-review.md) |
| Human release decision | **RELEASE** by Matthew Shelton (06:44 UTC on 19 October), recorded with `ai review decide` on review `44929d5d`: [`release-decision.md`](release-decision.md) |

Feature 1 held five accepted real releases when the smoke test ran: G-NAF 5,224,340 addresses,
NSW property sales 7,423,881, BOCSAR 318,804, ABS SEIFA 4,320 and NSW government schools 2,210.
NSW suburb boundaries (4,607 suburbs) was published at 08:58 UTC, after the smoke test and before
the screenshots, so `app/03-published-data.png` shows six. No demonstration data is loaded.

An earlier run the same day, [39109808841](https://github.com/MattShelton04/41026ASDProject/actions/runs/39109808841),
also succeeded but skipped the Feature 2 and 4 CRUD cases (29 passed, 2 skipped), because its
smoke test ran a minute after `f1-db-api` restarted. Run 39112162750 replaced that evidence.
Automatic deployments stay paused (`AZURE_AUTO_DEPLOY=false`); manual runs still deploy.

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
| `endpoint-security.txt` | `cloud-deployment-<sha>` (`deploy.sh validate-endpoint`, B5) | Bonus B5 output of the AI-off deployment run, as the report cites it |
| `data-security.txt` | `deploy.sh validate-data` from a laptop (B6) | Bonus B6 output against the same deployment |
| `app/*.png` | person | The public site, Shared shell and Feature 1 (see "Application screenshots") |
| `portal/*.png` | person | The Azure portal screenshots below |

The bonus folder [`../bonus/`](../bonus/README.md) holds the AI-tier (B1–B4) evidence and copies of
B5 and B6; the files here are the AI-off baseline's own copies.

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

## Application screenshots

Taken on 18 October (about 09:00 UTC) through the site login, after run 39112162750. Every image
is 1456×819 (16:9). Only the Shared shell and Feature 1 are captured here; each feature owner
captures their own pages.

| File | Page | What it shows |
|---|---|---|
| `app/01-home.png` | `/` | The Shared shell and research areas |
| `app/02-property-search.png` | `/features/data-platform/#properties?q=1+George+Street` | A search over the published G-NAF release: at least 500 real NSW addresses |
| `app/03-published-data.png` | `/features/data-platform/#releases` | Six accepted releases with their record counts and publication times |
| `app/04-data-overview.png` | `/features/data-platform/#overview` | No update running or failing, six published sources, the latest collections |
| `app/05-data-status.png` | `/#system-status` | Live service status: 7 ready; the 2 needing attention are the AI review history and AI provider, unavailable because the AI tier is off |

### Observations made while capturing

These came from the live deployment and are recorded for their owners; none affects the smoke
test or the review.

- Shared: Data status counts the deliberately disabled AI tier as "Unavailable" (needs attention)
  rather than "Disabled". Fixed in #160; it shows on Azure after the next deployment.
- Feature 3: Suburb context showed "Service unavailable": `/api/suburb-analytics/v1/published/suburbs`
  answered 503 after 4–8 s (Student 3).
- Feature 2: Sales & market lists saved cases on fixture addresses (`11 Example Street`,
  "Property: Fixture Verified"), Feature 2's own stored records rather than Feature 1 data
  (Student 2).

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

All 15 were taken on 18 October (09:05–09:16 UTC) after run 39112162750, at 1456×819 (16:9),
with the subscription and tenant IDs blacked out. Where one blade does not show everything, the
image stacks crops of several blades on the same 16:9 canvas:

- `03`: filtered to `propertyscope-github-deployer`; it shows this run's and the earlier run's
  *Run Command on Virtual Machine* operations and the provision operations. There is no *Start
  Virtual Machine* entry because the VM was already running.
- `05`: Trusted launch, secure boot and vTPM. Encryption at host is on the VM overview (`04`,
  Disk: *Encryption at host Enabled*).
- `06`: identity status and its two role assignments. `09`: the subnet list (NSG attached) and the
  *Service endpoints* blade (`Microsoft.KeyVault` on `app`).
- `11`: the registry's *Properties* blade (Admin user unchecked); the *Access keys* page was not
  opened.
- `12`: overview (soft delete, purge protection), access configuration (Azure RBAC) and networking
  (selected networks, the VNet rule, no IP rule). **Secret names are not shown**: listing them
  needs the browser's IP in the vault firewall, which was not changed for this capture.
- `14`: filtered to the `propertyscope-github` identities, so inherited university assignments
  (other people's names) are left out, plus the opened condition: the deployer may assign only
  AcrPull, AcrPush, Key Vault Secrets User and Key Vault Secrets Officer.
- `15`: the VM overview's platform metrics for the day (availability, CPU, disk bytes during the
  data loads and deployments).

Rules for these screenshots:

- Never open a secret's value. Show the list of names only.
- The Key Vault firewall denies the portal unless the browser's public IP is allowed. Add it
  for the capture (`az keyvault network-rule add`), then remove it. The next `provision` also
  removes it.
- Crop or blur the subscription ID and tenant ID. Resource names and the public URL may stay.
- JIT, Defender plans, Log Analytics, Backup and Bastion are not part of this deployment.
  Do not imply they are. TLS, HSTS, the site login and rate limits live in Caddy and nginx on
  the VM, so `endpoint-security.txt` is their evidence, not the portal.

## Report figures

The technical report uses three crops of this evidence, in
[`docs/reports/assets/release-2/screenshots/`](../../../reports/assets/release-2/screenshots/):
`azure-resources.png` (Figure 5: `portal/01` and `portal/08`), `azure-workflow.png` (Figure 6: the
summary and *Deploy to Azure* step list of run 39112162750, captured on 18 October with the page
in GitHub's light theme) and `azure-app.png` (Figure 7: `app/01` and `app/03`). They are crops
only; nothing is redrawn except the URL label on Figure 7.

## Labelling rules

- The cloud holds no demonstration data (ADR-048, 18 October amendment): name the real releases
  that were published there, or say that none were. The report records what the VM saw.
- The AI tier is off in the required baseline. Evidence for the bonus AI tiers goes in
  `../bonus/`, never here.
- Never copy secrets, run-command payloads or `.env.azure` into this folder. The workflow artifact
  already excludes payloads, and the logs contain no secret values.
