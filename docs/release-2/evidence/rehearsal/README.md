# Local Azure deployment rehearsal (17 October 2026)

> **This is NOT the Azure deployment.** It is a rehearsal on one developer laptop (Windows 11,
> Docker Desktop). A `registry:2` container stood in for ACR, a Docker-in-Docker container stood in
> for the VM, and throwaway files stood in for Key Vault. Azure was not provisioned and no `az`
> command ran. Nothing here is cloud evidence for B4, B5 or B6. Real cloud evidence goes in
> [`../cloud/`](../cloud/README.md), and this directory sits outside the paths the cloud review
> reads.

| | |
|---|---|
| Command | `uv run scripts/dev.py cloud rehearse` ([`deployment/azure/README.md`, "Local rehearsal"](../../../../deployment/azure/README.md#local-rehearsal)) |
| Commit | `927801df23afd9deb11a806b13ecf7789f40bfd9` on `worktree-agent-a82230e0a4e8254ac`. The image tag carries `-dirty` because the ADR-048 amendment and one README row were still uncommitted (documentation only) |
| Run | 2026-10-17 03:02:21 to 03:06:09 UTC, about 4 minutes. The build reused Docker layer cache from earlier runs |
| Data | The seeded demonstration baseline and the `fixture-property` collection: the cloud data plan. No real dataset was downloaded |
| AI tier | Off (the default). `docker-compose.azure-ai.yml` was only rendered with `docker compose config` |
| Verdict | **PASSED**: every stage succeeded, and every failure was one of the expected local gaps listed below |

## Results

| Stage | What ran | Result |
|---|---|---|
| push | `deploy.sh push`: built `propertyscope/<service>:rehearsal` (the shared `:dev` images are untouched) and pushed `:<sha>-dirty` plus the Caddy and PostGIS mirrors to the local registry | success |
| deploy | `deploy.sh deploy`: the exact run-command payload ran as root in the rehearsal VM, where `propertyscope-vm.sh deploy` pulled every image into an empty engine | 21/21 containers running, AI off, 5 accepted releases, `fixture-property` succeeded, HTTPS check passed |
| smoke | `deploy.sh smoke --insecure` against `https://localhost`. The image identity is the one the VM observed (`PROPERTYSCOPE_IMAGES`) | **35/35**: every page and health route, the CRUD case of each feature (Feature 1 including update and confirm-update), and the AI-disabled check ([cloud-smoke.md](cloud-smoke.md)) |
| endpoint security (B5) | `deploy.sh validate-endpoint`, with `EDGE_CA_FILE` set to Caddy's internal root and intermediate certificates | 35 PASS, 2 expected FAIL, NSG check skipped ([endpoint-security.txt](endpoint-security.txt)) |
| data security (B6, on-host half) | `deploy.sh vm-validate-data` inside the VM | 26 PASS, 0 FAIL ([data-security.txt](data-security.txt)) |
| AI overlay wiring | `docker compose config` with the AI overlay inside the VM | 21/21: `multi_agent_service_token` and `ai_mode_service_token` are Compose secrets for exactly the backends that call those services, and no token value appears in an environment |
| report | `scripts/cloud_deployment_report.py --notice ...` over the rehearsal logs | SUCCEEDED |
| review | `ai review cloud --deterministic` over a scratch evidence tree under `.propertyscope-runtime/` | `fail`, as expected: 16/18 checks passed. The only failures were the two CI records listed below |
| teardown | `down --volumes` on `ps-azure-rehearsal` only, and removal of the registry container, the local tags and the stand-in secrets | success |

The endpoint-security checks that passed:

- HTTP gets a 308 redirect to HTTPS.
- TLS 1.1 is refused while TLS 1.2 is served.
- HSTS is set for one year, along with nosniff, frame denial, CSP and Referrer-Policy. No Server header is sent.
- Without operator credentials the edge returns a 401 with a Basic challenge. This covers all six
  protected routes, `/api/data-platform/v1/release-reviews` included. Wrong credentials also get
  401, and valid credentials reach the backend (200).
- Public AI health returns 503 `ai_disabled`.
- A burst on `/fragments/rate-limit-probe` drew 23 responses of 429.
- 15 of the 16 probed ports are closed. The exception is 5432, explained below.

### Expected local gaps

- **Publicly trusted certificate (B5).** The rehearsal edge uses Caddy's internal CA for
  `localhost`, so this check fails as designed. It never trusts `EDGE_CA_FILE`.
- **Port 5432 (B5).** The laptop runs its own PostgreSQL service on the host loopback. The rehearsal
  probed the VM from inside its network and found 5432 closed there (80 and 443 were open, and
  every other port was closed), so this failure belongs to the laptop, not to the deployment.
- **`cloud.release-gate` (required) and `cloud.build` (advisory) in the review.** Both records come
  from GitHub Actions (the `verify-ci` and `build-validate` jobs), and a local run has no such
  records.

## Bugs the rehearsal found (fixed in the same commit)

1. **Bundle file modes.** The VM extracted the deploy bundle as root and kept the file modes from the
   operator's checkout. From a 0600 checkout (Windows, or umask 077), nginx failed with `open()
   ... 00-propertyscope-production.conf (13: Permission denied)` and the edge never became
   healthy. The payload now makes the deployment files world-readable after extraction.
2. **False passes on a dead edge.** In `validate-endpoint-security.sh`, "valid operator credentials
   pass the edge" accepted `000` (no answer), and "TLS 1.1 refused" passed even when nothing
   answered at all. Both checks now need a real answer. An optional `EDGE_CA_FILE` setting lets the
   HTTP-level checks run against a private CA.
3. **Smoke identity from `deploy.sh`.** `deploy.sh smoke` now passes the registry, image tag, deploy
   SHA and VM log to `cloud_smoke.py`. When the outputs are already known, it no longer needs an
   Azure sign-in.
4. **Deployed images.** The VM now prints `PROPERTYSCOPE_IMAGES`, the image and registry digest of
   each running container. `cloud_smoke.py --vm-log` records these images, where it previously
   recorded the list derived from the Compose file.
5. Two smaller additions:
   - `push --reuse-images` pushes images that were already built, but only when they match the
     build manifest for the same clean tag.
   - The report gains a "Release gate" section.

## What this does not prove

Anything that needs Azure itself:

- ACR authentication and the managed-identity token exchange
- Key Vault, IMDS and their RBAC propagation
- the NSG and Azure networking
- the public DNS label and the Let's Encrypt certificate
- the OIDC sign-in and the `production` environment approval
- Bicep deployment and cloud-init
- `az vm run-command` itself, including its 4 KiB output limit
- systemd and the host AI tier
- the B6 control-plane checks
- the CI release gate and the build-validate record
- the VM's size and performance

## Re-run

```text
uv run scripts/dev.py cloud rehearse            # build, deploy, check, tear down
uv run scripts/dev.py cloud rehearse --keep     # leave https://localhost up afterwards
```

The run needs ports 80, 443 and 5000 to be free on the host. It works in Compose project
`ps-azure-rehearsal` and never touches other projects or the `:dev` images. Its full output goes to
`.propertyscope-runtime/cloud-rehearsal/`, which is Git-ignored. Only the three summaries above
were copied here. They contain no secret values.
