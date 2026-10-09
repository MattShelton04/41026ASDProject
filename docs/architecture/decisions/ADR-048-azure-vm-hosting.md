# ADR-048: Host the Release 2 cloud deployment on one Azure VM, with the AI tier behind a flag

- Status: Accepted (infrastructure prepared; not yet provisioned)
- Date: 9 October 2026
- Owner: Shared platform (Matthew Shelton)
- Reaffirms: [ADR-046](ADR-046-non-containerised-ai-tier.md) (AI services are host processes)
- Plan: [Release 2 implementation plan](../../release-2/implementation-plan.md), decisions D1, D2
  and D7; [Shared plan](../../release-2/parts/shared.md) sections E and F
- Runbook: [deployment/azure/README.md](../../../deployment/azure/README.md)

## Context

Release 2 must deploy the integrated application to Azure. The cloud baseline must keep the
frontend, backend/API, database and CRUD functions working with AI-mode, MCP, RAG and the
Multi-Agent Server **disabled by default** (R2-44). `cloud-deployment.yml` must deploy only after
the required CI validation succeeds (R2-43), from reusable scripts and Infrastructure as Code
(R2-42). Bonus marks are available for enabling each AI tier in the cloud (B1–B4) and for
endpoint and data security (B5, B6).

The application is about 20 Compose services: the shared nginx edge, five feature slices with
their own frontends, backends and database services, two PostGIS databases and three SQLite
volumes. ADR-046 requires AI-mode, MCP, RAG (and now the Multi-Agent Server) to run as host
processes, never as containers. That rules out every Azure target that only runs containers
(Container Apps, App Service for Containers, AKS) for the bonus tiers. The earlier sketch in
`shared-platform-design.md` (Container Apps with Azure Files for SQLite) also conflicts with
SQLite's single-writer guidance on network file systems.

## Decision

1. **One Ubuntu 24.04 VM** (default `Standard_D4s_v5`, 4 vCPU / 16 GiB, parameterised) runs the
   existing Compose model unchanged, plus `docker-compose.azure.yml`. Images are built once per
   commit, pushed to **Azure Container Registry** tagged with the Git SHA, and pulled by the VM
   with its **system-assigned managed identity** (`AcrPull`). Nothing is built on the VM.
2. **Bicep at resource-group scope** (`deployment/azure/main.bicep` and modules) defines ACR (admin
   user and anonymous pull disabled), a VNet/subnet and NSG that admit only 80/443, a Standard
   public IP with a DNS label, the VM (Trusted Launch, managed disks, optional encryption at
   host), an RBAC-mode Key Vault with soft delete, purge protection and a firewall, the
   least-privilege role assignments, a daily auto-shutdown and a consumption budget. Region
   `australiaeast` by default. `deploy.sh provision` creates the resource group when it is
   missing, then applies the template; re-running converges.
3. **No SSH.** The NSG has no SSH rule and cloud-init disables `sshd`. Every operation is an
   `az vm run-command invoke` script (`deployment/azure/vm/propertyscope-vm.sh`) that ships the
   commit's Compose and edge configuration as a small bundle. The serial console (boot
   diagnostics) is the break-glass path.
4. **Caddy terminates TLS** on the DNS label (Let's Encrypt), redirects HTTP to HTTPS, adds HSTS
   and security headers, and requires operator credentials on operations and AI routes. It is
   the only container that publishes ports. It proxies to the unchanged nginx edge, which gains a
   production-only `conf.d` include with rate limits (`limit_req`) but no change to local
   behaviour.
5. **Secrets live only in Key Vault.** The VM reads them with its managed identity (IMDS token,
   Key Vault REST) into root-only files under `/opt/propertyscope/secrets/`. Compose mounts them
   as secrets, and a small entrypoint shim exports each one into its application process only,
   so no value appears in `docker inspect`, `docker compose config` or image history. GitHub
   Actions signs in with **OIDC** (a federated credential for the `production` environment); the
   repository stores no cloud secret.
6. **Databases stay private.** Each feature's database tier joins an `internal: true` network
   shared only with its own backend; PostgreSQL leaves the shared network entirely and nothing
   publishes a database port.
7. **AI is a flag.** `PROPERTYSCOPE_CLOUD_AI=false` is the default and the only value the
   workflow deploys. In that mode no backend maps `host.docker.internal`, every AI URL points at a
   closed loopback port, and Caddy answers the shared AI routes with `503 ai_disabled`.
   `deploy.sh ai on` checks out the deployed commit on the VM, renders a host environment with
   the same `host_runtime.prepare_environment` the local launcher uses, starts systemd units for
   AI-mode, MCP, RAG and the Multi-Agent Server as the unprivileged `propertyscope-ai` user, and
   applies `docker-compose.azure-ai.yml`, which restores the host-gateway wiring. The AI tier
   still runs on the host, never in a container. From AI-mode's point of view this is its
   `local` environment: MCP and RAG stay on the VM loopback, and AI-mode's port 5005 is reachable
   only from the containers (the NSG never admits it).
8. **The workflow is gated.** `cloud-deployment.yml` runs on `workflow_run` after **Integration
   CI** succeeds for a push to `main`, or on manual dispatch. It skips cleanly until the
   repository variable `AZURE_SUBSCRIPTION_ID` is set, uses the protected `production`
   environment (a human approval point), and calls the same `deploy.sh` subcommands an operator
   runs: `provision`, `push`, `deploy`, `smoke`. It then builds the deployment report and uploads
   the logs.
9. **The demonstration data is labelled.** The cloud starts from the seeded demonstration
   baseline that Feature 1's migrations create, and runs the `fixture-property` collection once
   to prove the runner/loader pipeline. Real releases are collected and published in the cloud
   only through the usual human review.

## Consequences

- The cloud runs the same images, health checks and routing as local Compose. Feature owners
  change nothing for the baseline. Each owner's cloud CRUD case lives in `scripts/cloud_smoke.py`.
- A single VM is a single point of failure, with no zero-downtime deploys. This is acceptable
  for a course demonstration. `compose up --wait` with health checks bounds a failed rollout,
  and redeploying an earlier SHA is the rollback.
- Cost is one mid-size VM plus a Basic ACR and a Standard IP. Auto-shutdown, `az vm deallocate`
  and a budget alert keep it bounded. Deployments start a deallocated VM.
- Encryption at host needs the `Microsoft.Compute/EncryptionAtHost` feature registered once per
  subscription. The parameter can be turned off (managed disks are still encrypted at rest with
  platform keys), and `deploy.sh provision` refuses to continue until the feature is registered,
  rather than failing half-way.
- Purge protection means a deleted vault keeps its name for the retention period. Redeploying into
  a new resource group or with a new prefix avoids the collision.
- `scripts/validate_architecture.py` now parses Compose merge tags and enforces the Azure rules:
  only the edge publishes ports, there are no source bind mounts, the baseline has no host-gateway
  AI wiring, and the AI overlay uses only the host gateway and loopback ports.
- The `shared-platform-design.md` sketch based on Container Apps and Azure Files is superseded.
