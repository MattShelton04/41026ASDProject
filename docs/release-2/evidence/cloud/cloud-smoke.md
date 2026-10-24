# Cloud smoke test

- Target: `https://propertyscope-nsw-g20.newzealandnorth.cloudapp.azure.com`
- Commit: `7b3fb43728582d21bb8c9722405c040e3c18cbf2`; image tag `7b3fb43728582d21bb8c9722405c040e3c18cbf2`; 21 image reference(s) from the VM (docker compose ps, PROPERTYSCOPE_IMAGES in vm-deploy.log)
- Started: 2026-10-24T00:06:17+00:00 (finished 2026-10-24T00:06:54+00:00)
- AI expectation: disabled; observed: disabled
- Site-wide login: enforced
- Result: **PASSED**, 37 of 37 checks passed

| Owner | Passed | Failed | Skipped |
|---|---|---|---|
| shared | 5 | 0 | 0 |
| student-1 | 8 | 0 | 0 |
| student-2 | 6 | 0 | 0 |
| student-3 | 6 | 0 | 0 |
| student-4 | 6 | 0 | 0 |
| student-5 | 6 | 0 | 0 |

| Result | Owner | Category | Check | Request | Detail | ms |
|---|---|---|---|---|---|---|
| PASS | shared | access | Site login required | `GET /` | anonymous HTTP 401, challenge Basic | 546 |
| PASS | shared | access | Edge liveness stays public | `GET /healthz` | anonymous HTTP 200 | 0 |
| PASS | shared | frontend | Shared home page | `GET /` | HTTP 200 text/html | 1286 |
| PASS | shared | health | Shared edge liveness | `GET /healthz` | HTTP 200, status ok | 131 |
| PASS | student-1 | frontend | data-platform frontend | `GET /features/data-platform/` | HTTP 200 text/html | 132 |
| PASS | student-1 | health | data-platform health | `GET /api/shared-health/data-platform` | HTTP 200, status healthy | 134 |
| PASS | student-2 | frontend | market-intelligence frontend | `GET /features/market-intelligence/` | HTTP 200 text/html | 131 |
| PASS | student-2 | health | market-intelligence health | `GET /api/shared-health/market-intelligence` | HTTP 200, status healthy | 133 |
| PASS | student-3 | frontend | suburb-analytics frontend | `GET /features/suburb-analytics/` | HTTP 200 text/html | 131 |
| PASS | student-3 | health | suburb-analytics health | `GET /api/shared-health/suburb-analytics` | HTTP 200, status ready | 133 |
| PASS | student-4 | frontend | due-diligence frontend | `GET /features/due-diligence/` | HTTP 200 text/html | 131 |
| PASS | student-4 | health | due-diligence health | `GET /api/shared-health/due-diligence` | HTTP 200, status healthy | 134 |
| PASS | student-5 | frontend | buyer-workspaces frontend | `GET /features/buyer-workspaces/` | HTTP 200 text/html | 133 |
| PASS | student-5 | health | buyer-workspaces health | `GET /api/shared-health/buyer-workspaces` | HTTP 200, status healthy | 163 |
| PASS | student-1 | crud | CRUD source definition: create | `POST /api/data-platform/v1/sources` | HTTP 201, id 17487cef-c584-4736-ad27-74f3805752b9 | 144 |
| PASS | student-1 | crud | CRUD source definition: read | `GET /api/data-platform/v1/sources/17487cef-c584-4736-ad27-74f3805752b9` | HTTP 200, name matches | 135 |
| PASS | student-1 | crud | CRUD source definition: update | `PUT /api/data-platform/v1/sources/17487cef-c584-4736-ad27-74f3805752b9` | HTTP 200, notes changed | 138 |
| PASS | student-1 | crud | CRUD source definition: confirm update | `GET /api/data-platform/v1/sources/17487cef-c584-4736-ad27-74f3805752b9` | HTTP 200, notes persisted | 133 |
| PASS | student-1 | crud | CRUD source definition: delete | `DELETE /api/data-platform/v1/sources/17487cef-c584-4736-ad27-74f3805752b9` | HTTP 204 | 138 |
| PASS | student-1 | crud | CRUD source definition: confirm deleted | `GET /api/data-platform/v1/sources/17487cef-c584-4736-ad27-74f3805752b9` | HTTP 404 after delete | 134 |
| PASS | student-2 | crud | CRUD market case: create | `POST /api/market-intelligence/v1/market-cases` | HTTP 201, id 6aa369a7-2230-4bb9-990a-ed3c2f32657a | 162 |
| PASS | student-2 | crud | CRUD market case: read | `GET /api/market-intelligence/v1/market-cases/6aa369a7-2230-4bb9-990a-ed3c2f32657a` | HTTP 200, name matches | 135 |
| PASS | student-2 | crud | CRUD market case: delete | `DELETE /api/market-intelligence/v1/market-cases/6aa369a7-2230-4bb9-990a-ed3c2f32657a` | HTTP 200 | 144 |
| PASS | student-2 | crud | CRUD market case: confirm deleted | `GET /api/market-intelligence/v1/market-cases/6aa369a7-2230-4bb9-990a-ed3c2f32657a` | HTTP 404 after delete | 135 |
| PASS | student-3 | crud | CRUD saved suburb comparison: create | `POST /api/suburb-analytics/v1/suburb-comparisons` | HTTP 201, id 270674d4-6b58-434c-a2bc-b3abacf27187 | 145 |
| PASS | student-3 | crud | CRUD saved suburb comparison: read | `GET /api/suburb-analytics/v1/suburb-comparisons/270674d4-6b58-434c-a2bc-b3abacf27187` | HTTP 200, name matches | 134 |
| PASS | student-3 | crud | CRUD saved suburb comparison: delete | `DELETE /api/suburb-analytics/v1/suburb-comparisons/270674d4-6b58-434c-a2bc-b3abacf27187` | HTTP 200 | 150 |
| PASS | student-3 | crud | CRUD saved suburb comparison: confirm deleted | `GET /api/suburb-analytics/v1/suburb-comparisons/270674d4-6b58-434c-a2bc-b3abacf27187` | HTTP 404 after delete | 133 |
| PASS | student-4 | crud | CRUD site review: create | `POST /api/due-diligence/v1/site-reviews` | HTTP 201, id f0b860cd-79e6-4fd2-9d04-9012ba7a341b | 181 |
| PASS | student-4 | crud | CRUD site review: read | `GET /api/due-diligence/v1/site-reviews/f0b860cd-79e6-4fd2-9d04-9012ba7a341b` | HTTP 200, title matches | 154 |
| PASS | student-4 | crud | CRUD site review: delete | `DELETE /api/due-diligence/v1/site-reviews/f0b860cd-79e6-4fd2-9d04-9012ba7a341b` | HTTP 200 | 142 |
| PASS | student-4 | crud | CRUD site review: confirm deleted | `GET /api/due-diligence/v1/site-reviews/f0b860cd-79e6-4fd2-9d04-9012ba7a341b` | HTTP 404 after delete | 133 |
| PASS | student-5 | crud | CRUD buyer case: create | `POST /api/buyer-workspaces/v1/buyer-cases` | HTTP 201, id 849905fd-53cc-4c7a-a751-ee8cf96bed1f | 177 |
| PASS | student-5 | crud | CRUD buyer case: read | `GET /api/buyer-workspaces/v1/buyer-cases/849905fd-53cc-4c7a-a751-ee8cf96bed1f` | HTTP 200, name matches | 162 |
| PASS | student-5 | crud | CRUD buyer case: delete | `DELETE /api/buyer-workspaces/v1/buyer-cases/849905fd-53cc-4c7a-a751-ee8cf96bed1f` | HTTP 200 | 170 |
| PASS | student-5 | crud | CRUD buyer case: confirm deleted | `GET /api/buyer-workspaces/v1/buyer-cases/849905fd-53cc-4c7a-a751-ee8cf96bed1f` | HTTP 404 after delete | 163 |
| PASS | shared | ai | AI tier disabled by default | `GET /api/shared-health/ai-mode` | disabled: HTTP 503, code ai_disabled | 130 |

Every CRUD case creates a uniquely named record through the owning feature's public API, reads it back, updates it where the feature registers an update, deletes it and confirms the delete. Operator credentials are never sent; only the shared viewer login is, when the site-wide login is checked.

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
