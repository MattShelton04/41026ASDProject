# Azure overview

What runs in Azure, what each resource does, and how it fits together. This is a summary. The
operating manual (setup, every `deploy.sh` command, costs, teardown) is
[deployment/azure/README.md](../../deployment/azure/README.md); the decision record is
[ADR-048](decisions/ADR-048-azure-vm-hosting.md).

## The short version

- **One VM runs everything.** It runs the same Docker Compose model as a laptop, plus a production
  override. A VM was chosen because the AI tier must run as host processes (ADR-046), and
  container-only platforms such as Container Apps, App Service and AKS can't do that.
- **Everything is defined in Bicep**, except two GitHub identities created once by hand.
- **GitHub Actions deploys it.** It signs in with OIDC, so no Azure credential is stored anywhere.
- **No SSH.** Every operation on the VM goes through `az vm run-command`.
- **Key Vault holds every secret.** The VM reads them with its managed identity.
- **The AI tier is off by default.** Turning it on is a separate manual workflow (bonus B1–B4).

| | |
|---|---|
| Subscription | Azure for Students |
| Region | `newzealandnorth` (the Students policy blocks `australiaeast`) |
| Resource group | `rg-propertyscope-prod` |
| URL | <https://propertyscope-nsw-g20.newzealandnorth.cloudapp.azure.com> (site-wide login) |
| Template | `deployment/azure/main.bicep` + `modules/*.bicep`, parameters in `main.bicepparam` |

## Every resource

The resource group holds exactly ten resources:

| Resource | Type | Defined in | What it is for |
|---|---|---|---|
| `propertyscope-prod-vm` | Virtual machine | `modules/vm.bicep` | The whole application. Ubuntu 24.04, `Standard_D4as_v4` (4 vCPU, 16 GiB). Trusted Launch (secure boot, vTPM), encryption at host, password login disabled, cloud-init from `cloud-init.yaml`. Has a **system-assigned managed identity** |
| `propertyscope-prod-vm-osdisk` | Managed disk | created with the VM | 256 GiB Premium SSD. Holds Docker, images and **all databases** (Docker volumes). Export is disabled after provisioning (`--network-access-policy DenyAll`) |
| `propertyscope-prod-vm-nic` | Network interface | `modules/vm.bicep` | Connects the VM to the subnet and public IP |
| `propertyscope-prod-vnet` | Virtual network | `modules/network.bicep` | `10.42.0.0/16`, one subnet `app` (`10.42.1.0/24`) with a Key Vault service endpoint |
| `propertyscope-prod-nsg` | Network security group | `modules/network.bicep` | On the subnet. Allows 443 (100), allows 80 (110), and denies everything else from the internet (4000). No SSH, no database ports |
| `propertyscope-prod-pip` | Public IP | `modules/network.bicep` | Standard SKU, static, with DNS label `propertyscope-nsw-g20`. Survives deallocation |
| `propertyscopeprod<hash>` | Container registry (ACR) | `modules/registry.bicep` | Basic SKU. Holds every image tagged with the Git SHA, plus mirrored Caddy and PostGIS. Admin user and anonymous pull are off, so access is RBAC only |
| `property-kv-<hash>` | Key Vault | `modules/keyvault.bicep` | Every runtime secret. RBAC mode, soft delete (7 days), purge protection. Firewall denies by default and admits the VM subnet plus listed operator IPs |
| `propertyscope-github-deployer` | User-assigned managed identity | by hand (README step 3) | GitHub's identity for **Cloud Deployment** and **Cloud AI Tier**. Federated credential for the `production` environment |
| `propertyscope-github-operations` | User-assigned managed identity | by hand (README step 4) | GitHub's identity for **Cloud Auto-Deallocate**. Can only read, start and stop the VM. Federated credential for the `operations` environment |

Template features not used here:

- **Auto-shutdown schedule** (`modules/shutdown.bicep`). `newzealandnorth` doesn't offer
  DevTestLab schedules, so it's `off`, and the nightly workflow does this job instead.
- **Budget** (`modules/budget.bicep`). It's created only when `AZURE_BUDGET_EMAILS` is set, and it
  isn't a listed resource.

The names are deterministic, derived from `uniqueString(resourceGroup().id)`. Re-running
`provision` converges the same resources.

## Who can do what (RBAC)

| Identity | Role | Scope | Why |
|---|---|---|---|
| VM (system-assigned) | AcrPull | ACR | Pull images |
| VM (system-assigned) | Key Vault Secrets User | Key Vault | Read secrets at deploy time |
| `github-deployer` | Contributor | Resource group | Provision and run commands |
| `github-deployer` | RBAC Administrator (conditional) | Resource group | Lets Bicep create **only** the roles above |
| `github-deployer` | AcrPush | ACR | Push images |
| `github-operations` | Desktop Virtualization Power On Off Contributor | VM | Nightly deallocation, and nothing else |
| Named operators | Key Vault Secrets Officer | Key Vault | Create secrets (`deploy.sh secrets`) |

The VM identity can't push images, write secrets or change any resource. Role assignments are in
`modules/access.bicep`.

## Inside the VM

```text
Internet ──443/80──▶ NSG ──▶ VM
  Docker (Compose project ps-azure, ~21 containers)
    shared-edge-proxy   Caddy: only container publishing ports. TLS (Let's Encrypt), HSTS,
                        security headers, site-wide login, operator login on AI/ops/pipeline routes
      └▶ shared-frontend nginx edge + home page, with production rate limits
          └▶ f1..f5 frontends ─▶ f1..f5 backends ─▶ DB services
                                                    f1/f4: PostGIS   f2/f3/f5: SQLite
                                                    each on its own internal network (no internet)
  systemd (host processes, OFF unless PROPERTYSCOPE_CLOUD_AI=true)
    propertyscope-ai.target → ai-mode :5005, mcp :5011, rag :5012, multi-agent :5013
    run as user propertyscope-ai; backends reach them via host.docker.internal
  propertyscope-imds-guard.service   blocks containers from 169.254.169.254, so a compromised
                                     container can't steal the VM identity's token
```

| VM path | Contents |
|---|---|
| `/opt/propertyscope/app` | The commit's Compose and edge bundle shipped by each deploy |
| `/opt/propertyscope/secrets` | Root-only secret files rendered from Key Vault. Compose mounts them as secrets, and an entrypoint shim exports each into its process only |
| `/opt/propertyscope/src` | Checkout of the deployed commit, used only by the AI tier. Its `.propertyscope-runtime/` holds the tier's tokens, RAG index and Multi-Agent state |
| `/var/lib/propertyscope-ai` | Home of the `propertyscope-ai` user (uv cache) |

The Feature 1 database runs with `PROPERTYSCOPE_DEMONSTRATION_DATA=false`. The cloud holds only
real, reviewed releases, never the seeded demo data.

## Secrets (Key Vault)

| Secret | Used by |
|---|---|
| `internal-token` | Backend → DB-API service token (all features) |
| `runner-token` | Feature 1 runner → backend |
| `f1-postgres-password`, `f4-postgres-password` | PostGIS passwords |
| `edge-site-password` | Site-wide viewer login (user `propertyscope`) |
| `edge-basic-auth-password` | Operator login (user `propertyscope-operator`) for ops, AI, pipeline and multi-agent routes |
| `ai-mode-service-token`, `multi-agent-service-token`, `mcp-service-token`, `rag-service-token` | AI tier only |
| `openai-api-key` | AI tier provider key |

`deploy.sh secrets` creates any missing secret with a random value and never overwrites one.

GitHub holds no Azure credential. It has three `production` environment secrets:

- `PROPERTYSCOPE_ACME_EMAIL`
- `PROPERTYSCOPE_SITE_PASSWORD`, for the smoke and B5 checks
- `PROPERTYSCOPE_OPERATOR_PASSWORD`, for the AI probe

## How a deployment happens

```text
GitHub Actions (cloud-deployment.yml)
  verify-ci        Integration CI + Student 1–5 CI green for the SHA
  build-validate   build every image, validate the Azure Compose model
  deploy           approval on `production` → OIDC login as github-deployer
    deploy.sh provision  az group create + Bicep (idempotent; recovers a soft-deleted vault)
    deploy.sh push       images → ACR as propertyscope/<service>:<git-sha>
    deploy.sh deploy     start VM if deallocated → az vm run-command → propertyscope-vm.sh:
                         ship bundle, read Key Vault via IMDS, pull from ACR, compose up --wait
    deploy.sh smoke      public URL: login enforced, every feature, CRUD per feature, AI = 503
    report + logs artifact
```

Every Cloud Deployment run turns the AI tier **off**.

**Cloud AI Tier** (`cloud-ai.yml`, manual, approval on `production`) runs `deploy.sh ai on` on the
VM's current commit. That command:

1. checks out the commit to `/opt/propertyscope/src` and runs `uv sync`
2. prepares the RAG model and corpora
3. starts the systemd units
4. applies `docker-compose.azure-ai.yml`, which wires the backends to the host services

Then `deploy.sh ai-probe` does one real interaction per tier (B1–B4).

## Workflows that touch Azure

| Workflow | Trigger | Identity | Does |
|---|---|---|---|
| Cloud Deployment | After Integration CI on `main` (paused by `AZURE_AUTO_DEPLOY=false`), or by hand | deployer | Gate, build, provision, deploy, smoke |
| Cloud AI Tier | By hand: `on` / `probe` / `off` | deployer | Bonus AI tier on the running VM |
| Cloud Auto-Deallocate | Nightly 12:30 UTC (23:30 Sydney time) | operations | Deallocates the VM. No approval needed |

All three share one concurrency group, so they never overlap.

## Security controls (bonus B5, B6)

| Control | Where | Checked by |
|---|---|---|
| Only 80/443 reachable, no SSH | NSG, cloud-init | `validate-endpoint-security.sh` (B5) |
| TLS, HTTP→HTTPS redirect, HSTS, security headers | Caddy | B5 |
| Site login on everything except `/healthz`, operator login on sensitive routes | Caddy | B5 |
| Rate limits (20 r/s API, 30 r/min sensitive) | nginx production include | B5 |
| Secrets only in Key Vault, read by managed identity, never in env/inspect/images | Key Vault, secret shims | `validate-data-security.sh` (B6) |
| No stored cloud credential (OIDC) | GitHub federated credentials | B6 |
| Encryption at host, disk export disabled | VM, OS disk | B6 |
| Databases on internal networks only | `docker-compose.azure.yml` | B6 |
| Containers blocked from IMDS | `propertyscope-imds-guard.service` | B6 |
| ACR admin/anonymous off, Key Vault firewall + purge protection | Bicep | B6 |

## Cost

The VM costs about US$0.23 per running hour, and it's deallocated nightly. The disk (about US$38 a
month), ACR (about US$5) and the IP (about US$4) bill even while the VM is deallocated. Deleting the
resource group removes everything, including both identities. Key Vault's purge protection holds the
vault name for 7 days, and `provision` recovers it.
