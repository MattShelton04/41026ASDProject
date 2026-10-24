# Cloud deployment report

Generated 2026-10-24T00:09:38+00:00 by `scripts/cloud_deployment_report.py` from the deployment's own logs.

## Summary

| Item | Value |
|---|---|
| Result | **SUCCEEDED** |
| Public URL | https://propertyscope-nsw-g20.newzealandnorth.cloudapp.azure.com |
| Commit / image tag | `7b3fb43728582d21bb8c9722405c040e3c18cbf2` / `7b3fb43728582d21bb8c9722405c040e3c18cbf2` |
| Trigger | workflow_dispatch by MattShelton04 |
| Workflow run | https://github.com/MattShelton04/41026ASDProject/actions/runs/40041985429 |
| Gating CI run | n/a (manual dispatch or local run) |
| Release gate | PASSED for `7b3fb4372858` |
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

**PASSED** for `7b3fb43728582d21bb8c9722405c040e3c18cbf2` on `main` (checked 2026-10-24T00:00:43+00:00; `gate/release-gate.json`).

| Workflow | Result | Run | Commit | Relation |
|---|---|---|---|---|
| Integration CI | success | [#480](https://github.com/MattShelton04/41026ASDProject/actions/runs/40041938611) | `7b3fb4372858` | identical |
| Student 1 CI | success | [#415](https://github.com/MattShelton04/41026ASDProject/actions/runs/40041938540) | `7b3fb4372858` | identical |
| Student 2 CI | success | [#198](https://github.com/MattShelton04/41026ASDProject/actions/runs/40041938639) | `7b3fb4372858` | identical |
| Student 3 CI | success | [#192](https://github.com/MattShelton04/41026ASDProject/actions/runs/40041938393) | `7b3fb4372858` | identical |
| Student 4 CI | success | [#186](https://github.com/MattShelton04/41026ASDProject/actions/runs/40041938431) | `7b3fb4372858` | identical |
| Student 5 CI | success | [#195](https://github.com/MattShelton04/41026ASDProject/actions/runs/40041938534) | `7b3fb4372858` | identical |

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
- Image tag on the VM: `7b3fb43728582d21bb8c9722405c040e3c18cbf2`
- Cloud AI flag: false
- Host AI units: ai-mode inactive, mcp inactive, rag inactive, multi-agent inactive

Images the running containers use, as the VM reported them (registry digest where the image was pulled):

| Service | Image |
|---|---|
| f1-backend | `propertyscopeprodpsvfewj5c5m3k.azurecr.io/propertyscope/f1-backend@sha256:770634a1e970155e0858085e7bbd4056f4bd2d30c135270e5af03ef6a9b0271e` |
| f1-db-api | `propertyscopeprodpsvfewj5c5m3k.azurecr.io/propertyscope/f1-db-api@sha256:a2748329ce1c2b9a13ddbb950af89d9af72fb51df33dea24412ce51fb90bb5ea` |
| f1-db-loader | `propertyscopeprodpsvfewj5c5m3k.azurecr.io/propertyscope/f1-db-loader@sha256:a9e5919ea2b0bec730046b60524f30ac1cfd404fdb52d473127c72d3d166cfe9` |
| f1-frontend | `propertyscopeprodpsvfewj5c5m3k.azurecr.io/propertyscope/f1-frontend@sha256:352cabc4c6832d8ad4c285a0dc9238f13e57f1ed8cf2a881dcffde5fbe7a1970` |
| f1-postgres | `propertyscopeprodpsvfewj5c5m3k.azurecr.io/propertyscope/mirror/postgis@sha256:44126d872ac91993766c341e369c539e8196614321765d36a6f1bab0419a5fa5` |
| f1-runner | `propertyscopeprodpsvfewj5c5m3k.azurecr.io/propertyscope/f1-runner@sha256:695138c90053fefa0f004c9d3dcf041dcd6d4add6df888c1b3862f7e76765c15` |
| f2-backend | `propertyscopeprodpsvfewj5c5m3k.azurecr.io/propertyscope/f2-backend@sha256:d96da8c21f1ec3add2e14d52283bda211b8cf2402427ef7c686127d458d35ccd` |
| f2-db-api | `propertyscopeprodpsvfewj5c5m3k.azurecr.io/propertyscope/f2-db-api@sha256:dc5361b6ad89ddcf9cba2c32b9cf260cb0941fe7d71275a3ed8113cf992db000` |
| f2-frontend | `propertyscopeprodpsvfewj5c5m3k.azurecr.io/propertyscope/f2-frontend@sha256:6e1aac861f2cc2219e6273538166e87af7e226d0d22fc014334a1aad45290aa7` |
| f3-backend | `propertyscopeprodpsvfewj5c5m3k.azurecr.io/propertyscope/f3-backend@sha256:8e39261ac91f0107e092d8c510cd55e84fb674e39c4bb64a3fca5bca859eb923` |
| f3-database | `propertyscopeprodpsvfewj5c5m3k.azurecr.io/propertyscope/f3-database@sha256:4ffe0d2c87f6e59e84b156882d7b199ab57fe78f56ffe345d45b8f662281907f` |
| f3-frontend | `propertyscopeprodpsvfewj5c5m3k.azurecr.io/propertyscope/f3-frontend@sha256:ff931d3aaa065455680ba1076e818cd721840354773baf3f58af0ffff589c73a` |
| f4-backend | `propertyscopeprodpsvfewj5c5m3k.azurecr.io/propertyscope/f4-backend@sha256:a57c75e73e8a0234802494d96bdacc521642ba22807eed048ac7759505c099fb` |
| f4-db-api | `propertyscopeprodpsvfewj5c5m3k.azurecr.io/propertyscope/f4-db-api@sha256:3bf7b5ad961bcdefe54833594ec2703173aaad18db5f311b842c49ff2b5e3bca` |
| f4-frontend | `propertyscopeprodpsvfewj5c5m3k.azurecr.io/propertyscope/f4-frontend@sha256:f268258f5b2ed9621814d7c1ba8b4137380adeb92bc39eac075610e6b3603b78` |
| f4-postgres | `propertyscopeprodpsvfewj5c5m3k.azurecr.io/propertyscope/mirror/postgis@sha256:44126d872ac91993766c341e369c539e8196614321765d36a6f1bab0419a5fa5` |
| f5-backend | `propertyscopeprodpsvfewj5c5m3k.azurecr.io/propertyscope/f5-backend@sha256:2407b556fc3b9f4128bcedff4089e36fd54d0cb11ed123e78e73e9ececfaa8bf` |
| f5-db-api | `propertyscopeprodpsvfewj5c5m3k.azurecr.io/propertyscope/f5-db-api@sha256:dd697cbed4fd2e52310f056065b5dcbce2b54279eb7839c0a0711bbfd6cff3e1` |
| f5-frontend | `propertyscopeprodpsvfewj5c5m3k.azurecr.io/propertyscope/f5-frontend@sha256:252af45da603b7d0ca5db39b52618589276c8ffd48bff8db1653b1602fb3390e` |
| shared-edge-proxy | `propertyscopeprodpsvfewj5c5m3k.azurecr.io/propertyscope/mirror/caddy@sha256:4c6e91c6ed0e2fa03efd5b44747b625fec79bc9cd06ac5235a779726618e530d` |
| shared-frontend | `propertyscopeprodpsvfewj5c5m3k.azurecr.io/propertyscope/shared-frontend@sha256:4de19bd04efe62735c30f1f98ecc67576c6191913cd7c051b8826db4705c0ede` |

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
| PASS | student-1 | CRUD source definition: create | HTTP 201, id 17487cef-c584-4736-ad27-74f3805752b9 |
| PASS | student-1 | CRUD source definition: read | HTTP 200, name matches |
| PASS | student-1 | CRUD source definition: update | HTTP 200, notes changed |
| PASS | student-1 | CRUD source definition: confirm update | HTTP 200, notes persisted |
| PASS | student-1 | CRUD source definition: delete | HTTP 204 |
| PASS | student-1 | CRUD source definition: confirm deleted | HTTP 404 after delete |
| PASS | student-2 | CRUD market case: create | HTTP 201, id 6aa369a7-2230-4bb9-990a-ed3c2f32657a |
| PASS | student-2 | CRUD market case: read | HTTP 200, name matches |
| PASS | student-2 | CRUD market case: delete | HTTP 200 |
| PASS | student-2 | CRUD market case: confirm deleted | HTTP 404 after delete |
| PASS | student-3 | CRUD saved suburb comparison: create | HTTP 201, id 270674d4-6b58-434c-a2bc-b3abacf27187 |
| PASS | student-3 | CRUD saved suburb comparison: read | HTTP 200, name matches |
| PASS | student-3 | CRUD saved suburb comparison: delete | HTTP 200 |
| PASS | student-3 | CRUD saved suburb comparison: confirm deleted | HTTP 404 after delete |
| PASS | student-4 | CRUD site review: create | HTTP 201, id f0b860cd-79e6-4fd2-9d04-9012ba7a341b |
| PASS | student-4 | CRUD site review: read | HTTP 200, title matches |
| PASS | student-4 | CRUD site review: delete | HTTP 200 |
| PASS | student-4 | CRUD site review: confirm deleted | HTTP 404 after delete |
| PASS | student-5 | CRUD buyer case: create | HTTP 201, id 849905fd-53cc-4c7a-a751-ee8cf96bed1f |
| PASS | student-5 | CRUD buyer case: read | HTTP 200, name matches |
| PASS | student-5 | CRUD buyer case: delete | HTTP 200 |
| PASS | student-5 | CRUD buyer case: confirm deleted | HTTP 404 after delete |
| PASS | shared | AI tier disabled by default | disabled: HTTP 503, code ai_disabled |

## Endpoint security validation (bonus B5)

60 of 60 lines without failure.

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
| PASS | anonymous /api/market-intelligence/v1/market-briefs requires operator credentials (401) |
| PASS | the viewer login does not open /api/market-intelligence/v1/market-briefs (401) |
| PASS | anonymous /api/due-diligence/v1/evidence-reviews requires operator credentials (401) |
| PASS | the viewer login does not open /api/due-diligence/v1/evidence-reviews (401) |
| PASS | anonymous /api/market-intelligence/v1/assistant/turns requires operator credentials (401) |
| PASS | the viewer login does not open /api/market-intelligence/v1/assistant/turns (401) |
| PASS | 401 carries a Basic challenge (www-authenticate: Basic realm="PropertyScope operations") |
| PASS | wrong operator credentials are rejected (401) |
| PASS | AI health stays readable without operator credentials (503 ai_disabled, or 200 when the bonus tier is on) (503) |
| PASS | ordinary feature API needs no operator credentials (200) |
| PASS | the Multi-Agent capabilities probe /api/market-intelligence/v1/market-briefs/capabilities needs no operator credentials (200) |
| PASS | the Multi-Agent capabilities probe /api/due-diligence/v1/evidence-reviews/capabilities needs no operator credentials (200) |
| PASS | edge rate limit (/api/ and /fragments/ zone) answers a burst on /fragments/rate-limit-probe with 429 (     51 404      99 429 ) |
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
