# Cloud deployment report

Generated 2026-10-18T08:51:59+00:00 by `scripts/cloud_deployment_report.py` from the deployment's own logs.

## Summary

| Item | Value |
|---|---|
| Result | **SUCCEEDED** |
| Public URL | https://propertyscope-nsw-g20.newzealandnorth.cloudapp.azure.com |
| Commit / image tag | `3c25c083e09e5f170767e63655593c0e5b9f1e27` / `3c25c083e09e5f170767e63655593c0e5b9f1e27` |
| Trigger | workflow_dispatch by MattShelton04 |
| Workflow run | https://github.com/MattShelton04/41026ASDProject/actions/runs/39112162750 |
| Gating CI run | n/a (manual dispatch or local run) |
| Release gate | PASSED for `3c25c083e09e` |
| AI tier | flag off (PROPERTYSCOPE_CLOUD_AI), edge reports disabled |

## Pipeline stages

| Stage | Outcome |
|---|---|
| Provision (resource group + Bicep) | skipped |
| Build and push images to ACR | success |
| Deploy to the VM (az vm run-command) | success |
| Public smoke test | success |
| Endpoint security validation (B5) | success |
| Data security validation (B6) | not run |

## Release gate

**PASSED** for `3c25c083e09e5f170767e63655593c0e5b9f1e27` on `main` (checked 2026-10-18T08:41:45+00:00; `gate/release-gate.json`).

| Workflow | Result | Run | Commit | Relation |
|---|---|---|---|---|
| Integration CI | success | [#424](https://github.com/MattShelton04/41026ASDProject/actions/runs/39106471900) | `3c25c083e09e` | identical |
| Student 1 CI | success | [#383](https://github.com/MattShelton04/41026ASDProject/actions/runs/39106472018) | `3c25c083e09e` | identical |
| Student 2 CI | success | [#165](https://github.com/MattShelton04/41026ASDProject/actions/runs/39106471994) | `3c25c083e09e` | identical |
| Student 3 CI | success | [#156](https://github.com/MattShelton04/41026ASDProject/actions/runs/39106472108) | `3c25c083e09e` | identical |
| Student 4 CI | success | [#152](https://github.com/MattShelton04/41026ASDProject/actions/runs/39106471969) | `3c25c083e09e` | identical |
| Student 5 CI | success | [#162](https://github.com/MattShelton04/41026ASDProject/actions/runs/39106471984) | `3c25c083e09e` | identical |

## Azure resources

| Output | Value |
|---|---|
| acr_login_server | `propertyscopeprodpsvfewj5c5m3k.azurecr.io` |
| acr_name | `propertyscopeprodpsvfewj5c5m3k` |
| fqdn | `propertyscope-nsw-g20.newzealandnorth.cloudapp.azure.com` |
| key_vault_name | `property-kv-psvfewj5c5m3` |
| public_url | `https://propertyscope-nsw-g20.newzealandnorth.cloudapp.azure.com` |
| resource_group | `rg-propertyscope-prod` |
| vm_name | `propertyscope-prod-vm` |

## VM deployment

- Containers running: 21 of 21
- Image tag on the VM: `3c25c083e09e5f170767e63655593c0e5b9f1e27`
- Cloud AI flag: false
- Host AI units: ai-mode inactive, mcp inactive, rag inactive, multi-agent inactive

Images the running containers use, as the VM reported them (registry digest where the image was pulled):

| Service | Image |
|---|---|
| f1-backend | `propertyscopeprodpsvfewj5c5m3k.azurecr.io/propertyscope/f1-backend@sha256:9f92086fe080cd26faff7ab2f55ba0e3c01e4a6e758bae641f939395187e437a` |
| f1-db-api | `propertyscopeprodpsvfewj5c5m3k.azurecr.io/propertyscope/f1-db-api@sha256:1172ff6b8b8de55c8e80779c72ad9103ab2acef7d2d788d45b479331117e8c21` |
| f1-db-loader | `propertyscopeprodpsvfewj5c5m3k.azurecr.io/propertyscope/f1-db-loader@sha256:2df5a4077e2777ae34d3aaea4b3c3a4c5613d3548dab8a4d8015d7a231ea18d9` |
| f1-frontend | `propertyscopeprodpsvfewj5c5m3k.azurecr.io/propertyscope/f1-frontend@sha256:94f12b3441602f3eaf6f87cdbb72074c05fd103e476cf67979d19c8fdcf56624` |
| f1-postgres | `propertyscopeprodpsvfewj5c5m3k.azurecr.io/propertyscope/mirror/postgis@sha256:44126d872ac91993766c341e369c539e8196614321765d36a6f1bab0419a5fa5` |
| f1-runner | `propertyscopeprodpsvfewj5c5m3k.azurecr.io/propertyscope/f1-runner@sha256:bd71a458271954bf637b20cfac621351aa6e01c7d253d3657813197b68b3d7a9` |
| f2-backend | `propertyscopeprodpsvfewj5c5m3k.azurecr.io/propertyscope/f2-backend@sha256:0a7fb51926d52d9b6bf9a19f210806fa7307ec4b716db4bf44772f00554d16ee` |
| f2-db-api | `propertyscopeprodpsvfewj5c5m3k.azurecr.io/propertyscope/f2-db-api@sha256:0496a76237bdd351b3c313d26bc3ee4232273503886f350077a06398fa6d7100` |
| f2-frontend | `propertyscopeprodpsvfewj5c5m3k.azurecr.io/propertyscope/f2-frontend@sha256:929e9488ab1c59bff14f4de2141be45c15c032e0e443f329c08ed2740749a6f4` |
| f3-backend | `propertyscopeprodpsvfewj5c5m3k.azurecr.io/propertyscope/f3-backend@sha256:35d3e82d7a31e61cc05cce45fa49eedbfcdc4fc1c18e602f508cd20a47dc87b9` |
| f3-database | `propertyscopeprodpsvfewj5c5m3k.azurecr.io/propertyscope/f3-database@sha256:46fe9f8e8dca5537597491449ab8b0ffe9e727d2f1bdf04ee41a084cf48f3511` |
| f3-frontend | `propertyscopeprodpsvfewj5c5m3k.azurecr.io/propertyscope/f3-frontend@sha256:7cffed40c2885a937a1ab74cd01fe5136302037c473657549db9fa774dc56262` |
| f4-backend | `propertyscopeprodpsvfewj5c5m3k.azurecr.io/propertyscope/f4-backend@sha256:bf7172aedcca5fc54d5e24231862827c7cafb2eb85d60b64fbfffaf9b9e9ee4a` |
| f4-db-api | `propertyscopeprodpsvfewj5c5m3k.azurecr.io/propertyscope/f4-db-api@sha256:151646408abd0f488e9c7f8304e422138a2ab0099c21d14086c84e044e22d924` |
| f4-frontend | `propertyscopeprodpsvfewj5c5m3k.azurecr.io/propertyscope/f4-frontend@sha256:dadbebf603974ad6f45678537703968bef9191fa034c0147bb8b8b441a6c9c62` |
| f4-postgres | `propertyscopeprodpsvfewj5c5m3k.azurecr.io/propertyscope/mirror/postgis@sha256:44126d872ac91993766c341e369c539e8196614321765d36a6f1bab0419a5fa5` |
| f5-backend | `propertyscopeprodpsvfewj5c5m3k.azurecr.io/propertyscope/f5-backend@sha256:bdccbb65596e3dada5c9954e5aec2e308f8853b1ec1908761a9fc8204ed8c0c3` |
| f5-db-api | `propertyscopeprodpsvfewj5c5m3k.azurecr.io/propertyscope/f5-db-api@sha256:48b58ef9c9e232236b50100ffcae17ae028fce5425a2ebd2c57b42e312fa77da` |
| f5-frontend | `propertyscopeprodpsvfewj5c5m3k.azurecr.io/propertyscope/f5-frontend@sha256:dad2134dd5d275367ec5d2bfb0b8b47b19adca7bc7fcc2914afff629531b8137` |
| shared-edge-proxy | `propertyscopeprodpsvfewj5c5m3k.azurecr.io/propertyscope/mirror/caddy@sha256:4c6e91c6ed0e2fa03efd5b44747b625fec79bc9cd06ac5235a779726618e530d` |
| shared-frontend | `propertyscopeprodpsvfewj5c5m3k.azurecr.io/propertyscope/shared-frontend@sha256:544b587d332ba5f7a8b409a4fc834a659226f479a2ac72b6b3107d61a2b0d32a` |

## Public smoke test

Target `https://propertyscope-nsw-g20.newzealandnorth.cloudapp.azure.com`: 37 of 37 checks passed.

| Owner | Passed | Failed | Skipped |
|---|---|---|---|
| shared | 5 | 0 | 0 |
| student-1 | 8 | 0 | 0 |
| student-2 | 6 | 0 | 0 |
| student-3 | 6 | 0 | 0 |
| student-4 | 6 | 0 | 0 |
| student-5 | 6 | 0 | 0 |

| Result | Owner | Check | Detail |
|---|---|---|---|
| PASS | shared | Site login required | anonymous HTTP 401, challenge Basic |
| PASS | shared | Edge liveness stays public | anonymous HTTP 200 |
| PASS | shared | Shared home page | HTTP 200 text/html |
| PASS | shared | Shared edge liveness | HTTP 200, status ok |
| PASS | student-1 | data-platform frontend | HTTP 200 text/html |
| PASS | student-1 | data-platform health | HTTP 200, status healthy |
| PASS | student-2 | market-intelligence frontend | HTTP 200 text/html |
| PASS | student-2 | market-intelligence health | HTTP 200, status healthy |
| PASS | student-3 | suburb-analytics frontend | HTTP 200 text/html |
| PASS | student-3 | suburb-analytics health | HTTP 200, status ready |
| PASS | student-4 | due-diligence frontend | HTTP 200 text/html |
| PASS | student-4 | due-diligence health | HTTP 200, status healthy |
| PASS | student-5 | buyer-workspaces frontend | HTTP 200 text/html |
| PASS | student-5 | buyer-workspaces health | HTTP 200, status healthy |
| PASS | student-1 | CRUD source definition: create | HTTP 201, id eaf86892-d331-4ef9-b0f9-3f43d0d23e23 |
| PASS | student-1 | CRUD source definition: read | HTTP 200, name matches |
| PASS | student-1 | CRUD source definition: update | HTTP 200, notes changed |
| PASS | student-1 | CRUD source definition: confirm update | HTTP 200, notes persisted |
| PASS | student-1 | CRUD source definition: delete | HTTP 204 |
| PASS | student-1 | CRUD source definition: confirm deleted | HTTP 404 after delete |
| PASS | student-2 | CRUD market case: create | HTTP 201, id 09b4f09c-9282-43ab-9a3f-9ca9eab28ff5 |
| PASS | student-2 | CRUD market case: read | HTTP 200, name matches |
| PASS | student-2 | CRUD market case: delete | HTTP 200 |
| PASS | student-2 | CRUD market case: confirm deleted | HTTP 404 after delete |
| PASS | student-3 | CRUD saved suburb comparison: create | HTTP 201, id a488b6cb-37f0-4332-bd3b-697eefcd8f6e |
| PASS | student-3 | CRUD saved suburb comparison: read | HTTP 200, name matches |
| PASS | student-3 | CRUD saved suburb comparison: delete | HTTP 200 |
| PASS | student-3 | CRUD saved suburb comparison: confirm deleted | HTTP 404 after delete |
| PASS | student-4 | CRUD site review: create | HTTP 201, id 267981dc-8529-409b-b099-55c001e80ea2 |
| PASS | student-4 | CRUD site review: read | HTTP 200, title matches |
| PASS | student-4 | CRUD site review: delete | HTTP 200 |
| PASS | student-4 | CRUD site review: confirm deleted | HTTP 404 after delete |
| PASS | student-5 | CRUD buyer case: create | HTTP 201, id e606d05f-ed78-4d87-b07f-3457e8144332 |
| PASS | student-5 | CRUD buyer case: read | HTTP 200, name matches |
| PASS | student-5 | CRUD buyer case: delete | HTTP 200 |
| PASS | student-5 | CRUD buyer case: confirm deleted | HTTP 404 after delete |
| PASS | shared | AI tier disabled by default | disabled: HTTP 503, code ai_disabled |

## Endpoint security validation (bonus B5)

54 of 54 lines without failure.

| Result | Check |
|---|---|
| PASS | HTTPS serves a publicly trusted certificate for propertyscope-nsw-g20.newzealandnorth.cloudapp.azure.com |
| INFO | certificate issuer: C=US; O=Let's Encrypt; CN=YE1 |
| PASS | TLS 1.1 and older are refused while TLS 1.2+ is served (tls<=1.1:000 tls>=1.2:200) |
| PASS | HTTP permanently redirects to HTTPS (308 https://propertyscope-nsw-g20.newzealandnorth.cloudapp.azure.com/features/data-platform/) |
| PASS | HSTS for at least one year (strict-transport-security: max-age=31536000; includesubdomains) |
| PASS | X-Content-Type-Options nosniff (x-content-type-options: nosniff) |
| PASS | Framing denied (content-security-policy: default-src 'self'; connect-src 'self' https://tiles.openfreemap.org; img-src 'self' data: blob:; style-src 'self'; script-src 'self'; worker-src blob:; object-src 'none'; base-uri 'self'; frame-ancestors 'none'; form-action 'self' x-frame-options: deny ) |
| PASS | Content-Security-Policy present (content-security-policy: default-src 'self'; connect-src 'self' https://tiles.openfreemap.org; img-src 'self' data: blob:; style-src 'self'; script-src 'self'; worker-src blob:; object-src 'none'; base-uri 'self'; frame-ancestors 'none'; form-action 'self') |
| PASS | Referrer-Policy present (referrer-policy: same-origin) |
| PASS | no server version disclosed (no Server header) |
| PASS | anonymous / requires the site login (401) |
| PASS | anonymous /features/data-platform/ requires the site login (401) |
| PASS | anonymous /api/data-platform/v1/sources?limit=1 requires the site login (401) |
| PASS | the site login answers with a Basic challenge (www-authenticate: basic realm="propertyscope nsw") |
| PASS | the login challenge itself carries HSTS (strict-transport-security: max-age=31536000; includesubdomains) |
| PASS | a wrong site password is rejected (401) |
| PASS | edge liveness (/healthz) stays public for uptime checks (200) |
| PASS | the viewer login opens the site (200) |
| PASS | anonymous /operations/ai-mode/ requires operator credentials (401) |
| PASS | the viewer login does not open /operations/ai-mode/ (401) |
| PASS | anonymous /api/ai-mode/runs requires operator credentials (401) |
| PASS | the viewer login does not open /api/ai-mode/runs (401) |
| PASS | anonymous /api/v1/runs requires operator credentials (401) |
| PASS | the viewer login does not open /api/v1/runs (401) |
| PASS | anonymous /api/data-platform/v1/artifact-retention requires operator credentials (401) |
| PASS | the viewer login does not open /api/data-platform/v1/artifact-retention (401) |
| PASS | anonymous /api/data-platform/v1/release-reviews requires operator credentials (401) |
| PASS | the viewer login does not open /api/data-platform/v1/release-reviews (401) |
| PASS | anonymous /api/market-intelligence/v1/assistant/turns requires operator credentials (401) |
| PASS | the viewer login does not open /api/market-intelligence/v1/assistant/turns (401) |
| PASS | 401 carries a Basic challenge (www-authenticate: Basic realm="PropertyScope operations") |
| PASS | wrong operator credentials are rejected (401) |
| PASS | AI health stays readable without operator credentials (503 ai_disabled, or 200 when the bonus tier is on) (503) |
| PASS | ordinary feature API needs no operator credentials (200) |
| PASS | edge rate limit (/api/ and /fragments/ zone) answers a burst on /fragments/rate-limit-probe with 429 (     56 404      94 429 ) |
| PASS | port 22 is closed to the internet |
| PASS | port 2375 is closed to the internet |
| PASS | port 3389 is closed to the internet |
| PASS | port 5005 is closed to the internet |
| PASS | port 5011 is closed to the internet |
| PASS | port 5012 is closed to the internet |
| PASS | port 5013 is closed to the internet |
| PASS | port 5100 is closed to the internet |
| PASS | port 5200 is closed to the internet |
| PASS | port 5202 is closed to the internet |
| PASS | port 5300 is closed to the internet |
| PASS | port 5400 is closed to the internet |
| PASS | port 5432 is closed to the internet |
| PASS | port 5500 is closed to the internet |
| PASS | port 5600 is closed to the internet |
| PASS | port 8080 is closed to the internet |
| PASS | NSG allows only 80 and 443 inbound (443 80) |
| PASS | NSG keeps port 80 open to the internet (certificate issuance and renewal) (Internet) |
| INFO | NSG HTTPS (443) sources: Internet |

## Evidence files

- `endpoint-security.txt`
- `gate/release-gate.json`
- `gate/release-gate.md`
- `image-tag.txt`
- `logs/deploy.log`
- `logs/push.log`
- `logs/smoke.log`
- `outputs.txt`
- `public-url.txt`
- `smoke/cloud-smoke.json`
- `smoke/cloud-smoke.md`
- `vm-deploy.log`
- `vm-status.log`

## Review and release decision

This report is input to the agentic-loop Cloud Deployment Report Review (`uv run scripts/dev.py ai review cloud`). The human release decision is recorded separately in `docs/release-2/evidence/cloud/release-decision.md`.
