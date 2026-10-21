# ADR-048: Host the Release 2 cloud deployment on one Azure VM, with the AI tier behind a flag

- Status: Accepted (provisioned and deployed 17 October 2026 in `newzealandnorth`, see
  [Amendments](#amendments))
- Date: 9 October 2026 (amended 17 and 18 October 2026, see [Amendments](#amendments))
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
   missing, recovers a soft-deleted vault of the same name, then applies the template;
   re-running converges. Resource names are deterministic per resource group
   (`uniqueString(resourceGroup().id)`), and the parameter files treat an empty environment
   value as "use the default", so an unset GitHub variable never yields an empty DNS label.
3. **No SSH.** The NSG has no SSH rule and cloud-init disables `sshd`. Every operation is an
   `az vm run-command invoke` script (`deployment/azure/vm/propertyscope-vm.sh`) that ships the
   commit's Compose and edge configuration as a small bundle. The serial console (boot
   diagnostics) is the break-glass path.
4. **Caddy terminates TLS** on the DNS label (Let's Encrypt), redirects HTTP to HTTPS, adds HSTS
   and security headers, and requires operator credentials on operations, AI, data-pipeline and
   Multi-Agent proxy routes (any feature's `assistant/turns`, `agent-runs`,
   `case-summary-runs`, `multi-agent`, `release-reviews`, `market-briefs` or `evidence-reviews`
   collection, except a proxy's read-only `capabilities` probe). It is the only
   container that publishes ports. It proxies to the unchanged nginx edge, which gains a
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
   applies `docker-compose.azure-ai.yml`, which restores the host-gateway wiring and hands the
   AI-mode and Multi-Agent entry tokens to the edge and to the backends that call them as
   Compose secrets (never environment values). The AI tier
   still runs on the host, never in a container. From AI-mode's point of view this is its
   `local` environment: MCP and RAG stay on the VM loopback, and AI-mode's port 5005 is reachable
   only from the containers (the NSG never admits it).
8. **The workflow is gated.** `cloud-deployment.yml` is triggered when **Integration CI
   completes** for a push to `main` (`workflow_run`, `types: [completed]`, whatever its
   conclusion; a cancelled or skipped run starts nothing), or by manual dispatch. The trigger is
   not the gate. Three jobs run in order:
   - `verify-ci` (`scripts/verify_release_gate.py`, read-only `gh api`) requires Integration CI
     to have succeeded on the deploy SHA itself, and the latest push or manual run on `main` of
     each path-filtered Student 1–5 CI workflow whose head is the deploy SHA or an ancestor of it
     to have succeeded. Runs still in progress are waited for (up to 60 minutes); any other
     conclusion fails the gate and records which run blocked it in `release-gate.json`.
   - `build-validate` builds every release image and validates the Azure Compose models
     (`scripts/validate_release_images.py`), with no Azure access.
   - `deploy` (timeout 120 minutes) is skipped until the repository variable
     `AZURE_SUBSCRIPTION_ID` is set. It uses the protected `production` environment (a human
     approval point), re-checks the gate before touching Azure, and calls the same `deploy.sh`
     subcommands an operator runs: `provision`, `push`, `deploy`, `smoke`. It then builds the
     deployment report (which includes the gate record) and uploads the logs.

   One deployment runs at a time and is never cancelled. `dev.py cloud rehearse` exercises the
   same `deploy.sh` path locally, against a registry container and a Docker-in-Docker VM, without
   Azure (deployment/azure/README.md, "Local rehearsal").
9. **The cloud holds no demonstration data** (amended 18 October 2026, below). Real releases
   are collected and published in the cloud only through the usual human review.

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
- Purge protection means a deleted vault keeps its name for the retention period, and the name is
  derived from the resource group ID. `deploy.sh provision` recovers the soft-deleted vault
  (keeping its secrets), which needs subscription-level read, so the first `provision` after a
  teardown runs from an Owner's laptop. `AZURE_KEY_VAULT_NAME_SEED` selects a fresh, empty vault
  instead. Purge protection stays on: it is part of the B6 data-security evidence, and the
  recovery path removes the redeploy collision it used to cause.
- `scripts/validate_architecture.py` now parses Compose merge tags and enforces the Azure rules:
  only the edge publishes ports, there are no source bind mounts, the baseline has no host-gateway
  AI wiring, and the AI overlay uses only the host gateway and loopback ports.
- The `shared-platform-design.md` sketch based on Container Apps and Azure Files is superseded.

## Amendments

**17 October 2026, deployment-readiness review (still not provisioned).**

- **Bicep compiles and lints cleanly**, with Bicep CLI v0.48.1 (`deployment/azure/validate-iac.sh`,
  Integration CI job `iac-lint`). The conditional VM module output uses a non-null assertion, and
  ACR moved to API `2025-04-01`, the first GA version that accepts `anonymousPullEnabled`.
- **Empty settings fall back to defaults.** `readEnvironmentVariable()` uses its default only for an
  unset variable, and GitHub passes an unset repository variable as `''`. Both parameter files and
  `main.bicep` (`publicDnsLabel`) now treat empty as the default. Without this, the public IP would
  have received an empty DNS label.
- **Key Vault after a teardown.** The vault name stays deterministic per resource group, and purge
  protection stays on. `provision` recovers a soft-deleted vault from the same group, and
  `AZURE_KEY_VAULT_NAME_SEED` gives an operator a fresh vault when that is wanted instead.
- **First deployment tolerates propagation delays.** On the VM, the IMDS token, Key Vault reads,
  the ACR token exchange and `compose pull` retry with bounded backoff (5 s doubling to 60 s,
  `PROPERTYSCOPE_AUTH_RETRY_ATTEMPTS`, default 12, about 8 minutes). This covers the minutes that a
  new managed identity, role assignment or vault firewall rule takes to apply. `compose up --wait`
  allows `PROPERTYSCOPE_STARTUP_WAIT_SECONDS` (default 900 instead of 300).
- **Health checks.** Caddy answers `/healthz` on a loopback-only site (`127.0.0.1:8079`, never
  published). The Feature 1 runner and loader have no HTTP surface, so their checks prove that each
  reaches the dependency it polls (`f1-backend /health/live`, `f1-postgres:5432`).
- **AI units** use `ReadWritePaths=-…/.propertyscope-runtime`, and the VM creates that Git-ignored
  directory after each checkout. A missing directory can no longer fail a unit with `226/NAMESPACE`.
- **Multi-Agent token.** The cloud AI overlay gives `multi_agent_service_token` to the Feature 1, 2,
  4 and 5 backends, the ones that call the Multi-Agent Server in `docker-compose.yml`. It uses the
  same secret-file shim as the AI-mode token. The baseline points their Multi-Agent URL at the
  closed loopback port.
- **Edge protection and B5 evidence.** `release-reviews` (Feature 1's Multi-Agent proxy, which
  starts paid runs and records human decisions) joined the generic protected collections in
  Caddy and in the nginx sensitive rate limit. The B5 burst moved from `/api/rate-limit-probe` to
  `/fragments/rate-limit-probe`. The catch-all `location /api/` answers with `return`, which runs
  in nginx's rewrite phase, before `limit_req`, so it could never produce a 429. A throwaway
  nginx container with the production include now proves the 429.
- **Feature 2 and 4 proxies (21 October).** `market-briefs` (Feature 2) and `evidence-reviews`
  (Feature 4) shipped under new collection names that the edge did not list, so with the AI tier
  on a viewer could start paid runs and record decisions. Both joined the protected collections
  in Caddy and nginx; their `capabilities` probe stays public because each page calls it on load.
  A deployment test now discovers every feature's Multi-Agent proxy from its source and fails
  until the edge covers it, and `validate-endpoint-security.sh` probes both.

**17 October 2026, local rehearsal (still not provisioned).** `uv run scripts/dev.py cloud
rehearse` runs the real `deploy.sh` push, deploy, smoke and validate commands against a
Docker-in-Docker "VM" and a `registry:2` stand-in for ACR, with the Key Vault secrets in throwaway
files and every `az` call refused (`deployment/azure/README.md`, "Local rehearsal"). The
production VM script only gains a hook that sources `/etc/propertyscope/rehearsal.sh` when the
file exists, and only the rehearsal image installs that file. Evidence:
`docs/release-2/evidence/rehearsal/` (not the Azure deployment). The run found these bugs, now
fixed:

- **Bundle file modes.** The VM extracted the bundle as root with the modes from the operator's
  checkout. From a 0600 checkout (Windows, or umask 077), nginx could not read its production
  include and the edge never became healthy. The payload now makes the deployment files
  world-readable after extraction.
- **False passes on a dead edge.** `validate-endpoint-security.sh` accepted `000` (no answer) for
  "valid operator credentials pass the edge", and "TLS 1.1 refused" passed while nothing answered
  at all. The credentials check now needs a real answer from behind the edge, and the legacy TLS
  check needs TLS 1.2 to answer `200` on the same URL. `EDGE_CA_FILE` lets the HTTP-level checks
  trust a private CA; the publicly-trusted-certificate check never does.
- **Deployed image identity.** The VM now prints `PROPERTYSCOPE_IMAGES` (each running container's
  image and registry digest) before `PROPERTYSCOPE_RESULT`. `cloud_smoke.py --vm-log` records them
  as the observed identity. `deploy.sh smoke` passes the registry, image tag, deploy SHA and VM log
  through, and needs no Azure sign-in when the outputs are known. `push --reuse-images` pushes
  images built earlier only when a build manifest for the same clean tag matches the local image
  IDs.

**17 October 2026, access control (still not provisioned).** A public demonstration URL exposed
every page and the per-feature CRUD to anyone who found it. Two controls were added:

- **Site-wide login, on by default.** Caddy asks every caller for a shared viewer login
  (`PROPERTYSCOPE_SITE_USER`, default `propertyscope`; Key Vault `edge-site-password`) on every
  route except `/healthz`, which stays anonymous for uptime checks and the B5 certificate check.
  The operator login also opens the site, and operator routes still need the operator login,
  in its own realm, on top. `PROPERTYSCOPE_SITE_AUTH=off` restores a public demonstration. The VM
  renders the viewer and operator bcrypt hashes into `edge-site-auth`, and the toggle selects
  which snippet (`caddy/site-auth-on.caddy` or `site-auth-off.caddy`) Compose mounts. Basic
  authentication was chosen over Microsoft Entra sign-in: markers may have no account in our
  tenant, and Caddy already holds the operator login, so no new service or identity provider is
  needed.
- **HTTPS source allowlist, optional.** `AZURE_ALLOWED_HTTPS_SOURCES` limits the NSG's 443 rule
  to listed IPv4/CIDR sources. Port 80 always stays open to the internet: Let's Encrypt validates
  and renews over HTTP-01 from unpublished addresses, and Caddy answers nothing else there but a
  redirect. While 443 is limited, `deploy.sh smoke` and `validate-endpoint` add a temporary NSG
  rule for their own address and remove it on exit, so GitHub-hosted runners can still check the
  edge.

`cloud_smoke.py --site-login` proves that anonymous callers get 401 and `/healthz` stays public,
then signs in as the viewer, and records `site_login` in `cloud-smoke.json` (schema 2,
additive). The B5 validator adds the site-login checks, confirms that the viewer login does not
open any operator route, and checks that the NSG keeps port 80 open. The viewer password reaches
both tools only through the environment: in GitHub Actions it is the `production` environment
secret `PROPERTYSCOPE_SITE_PASSWORD`, given only to those two steps. `deploy.sh` still never reads
a secret value out of Key Vault.

The local rehearsal found one gap: Caddy's own error answers, including every 401 login
challenge (the operator routes' too, before this change), skipped the deferred site headers, so
the first response a browser saw carried no HSTS. The security headers are now a Caddyfile
snippet imported by the site and by `handle_errors`, and the validator checks the challenge's
HSTS.

**17 October 2026, first switch-on.** The *Azure for Students* subscription allows only five
regions by policy (`newzealandnorth`, `malaysiawest`, `japaneast`, `indonesiacentral`,
`koreacentral`), so the deployment targets `newzealandnorth` with `Standard_D4as_v4`. A read-only
`az deployment group what-if` found the first two problems below, and the first `provision` the
third:

- **NSG service tag.** Azure rejects a service tag such as `Internet` in the plural
  `sourceAddressPrefixes` (`SecurityRuleParameterContainsUnsupportedValue`), and the HTTPS rule
  put its `['Internet']` default there. This affected every region. A single source, the default
  included, now goes into `sourceAddressPrefix`, and only a list of two or more uses the plural
  form. `deploy.sh` and the B5 validator already read both properties.
- **Auto-shutdown is optional, with a nightly backstop.** `Microsoft.DevTestLab/schedules` is not
  offered in `newzealandnorth`, and the workflow never passed `AZURE_AUTO_SHUTDOWN_TIME`, so CI
  always tried to create the schedule. The deploy job now passes the variable (default `2330`), and
  `off` (GitHub cannot pass an explicit empty value) skips the schedule. The new
  `cloud-auto-deallocate.yml` workflow deallocates the VM at 12:30 UTC in every region. It runs in
  its own `operations` environment without reviewers, so an unattended run never waits for an
  approval, signs in with OIDC (a second federated credential on the same deployer identity), and
  shares the deployment's concurrency group, so it never stops the VM mid-deployment.
- **Reading the Bicep outputs.** Azure CLI 2.89 prints a flat list query in `tsv` one value per
  line, where earlier releases used tabs. `deploy.sh` read only the first line, so `provision`
  stopped with "the Bicep outputs are incomplete". `load_outputs` now joins the lines first and
  accepts either form; `deploy.sh outputs` against the subscription printed all five values.
- **Immutable OIDC subjects.** The first GitHub Actions deployment failed its Azure sign-in with
  `AADSTS700213`: this repository uses GitHub's immutable subject claims, so the token subject is
  `repo:<owner>@<owner id>/<repo>@<repo id>:environment:<name>`, not the classic
  `repo:<owner>/<repo>:environment:<name>`. The README now has operators read the format from
  `actions/oidc/customization/sub` before creating the `production` and `operations` credentials.
- **Git Bash and the smoke AI check.** Git Bash rewrote `/subscriptions/...` arguments into Windows
  paths, which gave the B6 validator a false failure on the OS disk and broke manual
  `az role assignment create --scope` calls; `deploy.sh` and both validators now call az with
  `MSYS_NO_PATHCONV=1`. The smoke check "AI tier disabled by default" passed when nothing answered
  (a DNS failure); it now passes only on the edge's explicit `503 ai_disabled`.

Where the tenant blocks app registrations, a user-assigned managed identity in the resource group
can be the GitHub deployer instead: the same federated credentials and roles, `AZURE_CLIENT_ID` set
to its `clientId` and `AZURE_DEPLOYER_PRINCIPAL_ID` to its `principalId`. Deleting the resource
group at teardown removes it.

**17 October 2026, security audit.** A read-only audit of the live deployment and the repository
found no secret in the public logs or artifacts. It found that the risk lies in who can get the
deployer identity, and what that identity can then do. These changes followed:

- **Separate operations identity.** The `operations` environment has no reviewers, so that the
  nightly deallocation never waits, and it signed in as the deployer: Contributor plus RBAC
  Administrator on the resource group, reachable by any workflow merged into `main`.
  `cloud-auto-deallocate.yml` now signs in as its own user-assigned identity
  (`AZURE_OPERATIONS_CLIENT_ID`). It holds only *Desktop Virtualization Power On Off
  Contributor*, scoped to the VM. The deployer keeps only the `production` credential. The stale
  classic-subject credentials are deleted.
- **Conditioned RBAC Administrator.** The deployer's assignment carries an ABAC condition
  (version 2.0). It may write or delete assignments of AcrPull, AcrPush, Key Vault Secrets User
  and Key Vault Secrets Officer only, the four roles the Bicep creates, so it cannot make anyone
  Owner.
- **IMDS guard.** `propertyscope-vm.sh deploy` installs `propertyscope-imds-guard.service`, which
  drops container traffic to `169.254.169.254` in `DOCKER-USER`. A compromised container can no
  longer mint the VM identity's Key Vault token. Host scripts and the host AI tier keep IMDS. B6
  checks it from inside a feature backend. The local rehearsal has no systemd or IMDS, so it skips
  the guard and reports the check as SKIP.
- **Smaller exposure.** The OS disk denies export (`networkAccessPolicy: DenyAll`), and B6
  checks it. The ACME email is a `production` environment secret, so the logs mask it. The B6
  validator reads the federated credentials of a managed-identity deployer, where it used
  `az ad app` before.
- **Repository.** `.github/CODEOWNERS` covers only the cloud setup: `deployment/azure/`, the two
  cloud workflows, the Azure Compose files and itself. The rest of the repository has no code
  owner and keeps zero required approvals. Secret scanning, push protection and Dependabot
  alerts are on, Actions must be pinned to full commit SHAs, and fork pull requests from any
  external contributor need approval before workflows run.

**17 October 2026, provisioned and deployed.** The decisions above still describe the template's
defaults (`australiaeast`, `Standard_D4s_v5`). The live deployment differs only in its settings:
*Azure for Students*, `newzealandnorth` (the region policy blocks `australiaeast`),
`Standard_D4as_v4` (no DSv5 quota, about US$0.23 per running hour), `AZURE_AUTO_SHUTDOWN_TIME=off`
with the nightly *Cloud Auto-Deallocate* workflow, and a user-assigned managed identity with
immutable OIDC subjects as the GitHub deployer. The first successful *Cloud Deployment*, run
39018442663 (attempt 2, commit `ad2b443f`), passed the gate, ran 21 of 21 containers, passed the
smoke test 37 of 37 with the AI tier off, and passed the B5 validation with 52 checks.
`AZURE_AUTO_DEPLOY=false` now pauses automatic deployments for a quiet period, and a manual run
still deploys after the same gate. The cloud AI tier (B1–B4) has not run on Azure yet.

**18 October 2026, production starts empty.** The cloud no longer serves the seeded
demonstration baseline or runs the `fixture-property` collection on its first deployment: the
team collects real data there. `f1-db-api` runs with `PROPERTYSCOPE_DEMONSTRATION_DATA=false`, which
purges the showcase rows the migrations seed (runs, releases, records, properties and any
`fixture-property` collection) after every migration pass and keeps the source and job catalogue.
The migrations stay unchanged, so local stacks, CI and the deterministic tests keep their
baseline. Features 2 and 4 accept a record only for a property Feature 1 has published, so until a
G-NAF release is published in the cloud the smoke test reports their CRUD cases as skipped, with
that reason, and the deployment still passes. The Cloud Deployment Review lists them as unproven.

**18 October 2026, the AI tier gets its own workflow.** Decision 7 stands: Cloud Deployment
still deploys only with AI off. A separate, manually dispatched *Cloud AI Tier* workflow
(`.github/workflows/cloud-ai.yml`, `on`/`probe`/`off`) shares the `production` environment and the
deployment's concurrency group. It reads the commit the VM runs and turns the tier on from that
commit, so the host AI services, Compose files and images match without another deployment, while
the workflow and its tooling come from `main`. It then runs `deploy.sh ai-probe`
(`scripts/cloud_ai_probe.py`), which signs in as the operator with the production environment
secret `PROPERTYSCOPE_OPERATOR_PASSWORD` and makes one real interaction per bonus tier through the
public edge: a Feature 1 assistant turn answered through MCP (B1, B2), a cited RAG answer (B3) and
a Feature 1 release readiness review through Planner, Worker and Reviewer to `awaiting_human`
(B4). Its report is bonus evidence (`docs/release-2/evidence/bonus/`) and never replaces the
AI-off cloud evidence.
