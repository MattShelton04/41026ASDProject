# Cloud smoke test

- Target: `https://propertyscope-nsw-g20.newzealandnorth.cloudapp.azure.com`
- Commit: `3c25c083e09e5f170767e63655593c0e5b9f1e27`; image tag `3c25c083e09e5f170767e63655593c0e5b9f1e27`; 21 image reference(s) from the VM (docker compose ps, PROPERTYSCOPE_IMAGES in vm-deploy.log)
- Started: 2026-10-18T08:49:07+00:00 (finished 2026-10-18T08:49:16+00:00)
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
| PASS | shared | access | Site login required | `GET /` | anonymous HTTP 401, challenge Basic | 729 |
| PASS | shared | access | Edge liveness stays public | `GET /healthz` | anonymous HTTP 200 | 0 |
| PASS | shared | frontend | Shared home page | `GET /` | HTTP 200 text/html | 182 |
| PASS | shared | health | Shared edge liveness | `GET /healthz` | HTTP 200, status ok | 180 |
| PASS | student-1 | frontend | data-platform frontend | `GET /features/data-platform/` | HTTP 200 text/html | 181 |
| PASS | student-1 | health | data-platform health | `GET /api/shared-health/data-platform` | HTTP 200, status healthy | 184 |
| PASS | student-2 | frontend | market-intelligence frontend | `GET /features/market-intelligence/` | HTTP 200 text/html | 190 |
| PASS | student-2 | health | market-intelligence health | `GET /api/shared-health/market-intelligence` | HTTP 200, status healthy | 184 |
| PASS | student-3 | frontend | suburb-analytics frontend | `GET /features/suburb-analytics/` | HTTP 200 text/html | 181 |
| PASS | student-3 | health | suburb-analytics health | `GET /api/shared-health/suburb-analytics` | HTTP 200, status ready | 183 |
| PASS | student-4 | frontend | due-diligence frontend | `GET /features/due-diligence/` | HTTP 200 text/html | 181 |
| PASS | student-4 | health | due-diligence health | `GET /api/shared-health/due-diligence` | HTTP 200, status healthy | 183 |
| PASS | student-5 | frontend | buyer-workspaces frontend | `GET /features/buyer-workspaces/` | HTTP 200 text/html | 181 |
| PASS | student-5 | health | buyer-workspaces health | `GET /api/shared-health/buyer-workspaces` | HTTP 200, status healthy | 184 |
| PASS | student-1 | crud | CRUD source definition: create | `POST /api/data-platform/v1/sources` | HTTP 201, id eaf86892-d331-4ef9-b0f9-3f43d0d23e23 | 188 |
| PASS | student-1 | crud | CRUD source definition: read | `GET /api/data-platform/v1/sources/eaf86892-d331-4ef9-b0f9-3f43d0d23e23` | HTTP 200, name matches | 184 |
| PASS | student-1 | crud | CRUD source definition: update | `PUT /api/data-platform/v1/sources/eaf86892-d331-4ef9-b0f9-3f43d0d23e23` | HTTP 200, notes changed | 187 |
| PASS | student-1 | crud | CRUD source definition: confirm update | `GET /api/data-platform/v1/sources/eaf86892-d331-4ef9-b0f9-3f43d0d23e23` | HTTP 200, notes persisted | 183 |
| PASS | student-1 | crud | CRUD source definition: delete | `DELETE /api/data-platform/v1/sources/eaf86892-d331-4ef9-b0f9-3f43d0d23e23` | HTTP 204 | 187 |
| PASS | student-1 | crud | CRUD source definition: confirm deleted | `GET /api/data-platform/v1/sources/eaf86892-d331-4ef9-b0f9-3f43d0d23e23` | HTTP 404 after delete | 184 |
| PASS | student-2 | crud | CRUD market case: create | `POST /api/market-intelligence/v1/market-cases` | HTTP 201, id 09b4f09c-9282-43ab-9a3f-9ca9eab28ff5 | 209 |
| PASS | student-2 | crud | CRUD market case: read | `GET /api/market-intelligence/v1/market-cases/09b4f09c-9282-43ab-9a3f-9ca9eab28ff5` | HTTP 200, name matches | 183 |
| PASS | student-2 | crud | CRUD market case: delete | `DELETE /api/market-intelligence/v1/market-cases/09b4f09c-9282-43ab-9a3f-9ca9eab28ff5` | HTTP 200 | 188 |
| PASS | student-2 | crud | CRUD market case: confirm deleted | `GET /api/market-intelligence/v1/market-cases/09b4f09c-9282-43ab-9a3f-9ca9eab28ff5` | HTTP 404 after delete | 183 |
| PASS | student-3 | crud | CRUD saved suburb comparison: create | `POST /api/suburb-analytics/v1/suburb-comparisons` | HTTP 201, id a488b6cb-37f0-4332-bd3b-697eefcd8f6e | 194 |
| PASS | student-3 | crud | CRUD saved suburb comparison: read | `GET /api/suburb-analytics/v1/suburb-comparisons/a488b6cb-37f0-4332-bd3b-697eefcd8f6e` | HTTP 200, name matches | 183 |
| PASS | student-3 | crud | CRUD saved suburb comparison: delete | `DELETE /api/suburb-analytics/v1/suburb-comparisons/a488b6cb-37f0-4332-bd3b-697eefcd8f6e` | HTTP 200 | 193 |
| PASS | student-3 | crud | CRUD saved suburb comparison: confirm deleted | `GET /api/suburb-analytics/v1/suburb-comparisons/a488b6cb-37f0-4332-bd3b-697eefcd8f6e` | HTTP 404 after delete | 183 |
| PASS | student-4 | crud | CRUD site review: create | `POST /api/due-diligence/v1/site-reviews` | HTTP 201, id 267981dc-8529-409b-b099-55c001e80ea2 | 239 |
| PASS | student-4 | crud | CRUD site review: read | `GET /api/due-diligence/v1/site-reviews/267981dc-8529-409b-b099-55c001e80ea2` | HTTP 200, title matches | 206 |
| PASS | student-4 | crud | CRUD site review: delete | `DELETE /api/due-diligence/v1/site-reviews/267981dc-8529-409b-b099-55c001e80ea2` | HTTP 200 | 191 |
| PASS | student-4 | crud | CRUD site review: confirm deleted | `GET /api/due-diligence/v1/site-reviews/267981dc-8529-409b-b099-55c001e80ea2` | HTTP 404 after delete | 184 |
| PASS | student-5 | crud | CRUD buyer case: create | `POST /api/buyer-workspaces/v1/buyer-cases` | HTTP 201, id e606d05f-ed78-4d87-b07f-3457e8144332 | 196 |
| PASS | student-5 | crud | CRUD buyer case: read | `GET /api/buyer-workspaces/v1/buyer-cases/e606d05f-ed78-4d87-b07f-3457e8144332` | HTTP 200, name matches | 184 |
| PASS | student-5 | crud | CRUD buyer case: delete | `DELETE /api/buyer-workspaces/v1/buyer-cases/e606d05f-ed78-4d87-b07f-3457e8144332` | HTTP 200 | 196 |
| PASS | student-5 | crud | CRUD buyer case: confirm deleted | `GET /api/buyer-workspaces/v1/buyer-cases/e606d05f-ed78-4d87-b07f-3457e8144332` | HTTP 404 after delete | 184 |
| PASS | shared | ai | AI tier disabled by default | `GET /api/shared-health/ai-mode` | disabled: HTTP 503, code ai_disabled | 179 |

Every CRUD case creates a uniquely named record through the owning feature's public API, reads it back, updates it where the feature registers an update, deletes it and confirms the delete. Operator credentials are never sent; only the shared viewer login is, when the site-wide login is checked.

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
