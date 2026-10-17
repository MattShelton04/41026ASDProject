# Cloud smoke test

- Target: `https://localhost`
- Commit: `927801df23afd9deb11a806b13ecf7789f40bfd9`; image tag `927801df23afd9deb11a806b13ecf7789f40bfd9-dirty`; 21 image reference(s) from the VM (docker compose ps, PROPERTYSCOPE_IMAGES in vm-deploy.log)
- Started: 2026-10-17T03:04:25+00:00 (finished 2026-10-17T03:04:27+00:00)
- AI expectation: disabled; observed: disabled
- Result: **PASSED**, 35 of 35 checks passed

| Owner | Passed | Failed |
|---|---|---|
| shared | 3 | 0 |
| student-1 | 8 | 0 |
| student-2 | 6 | 0 |
| student-3 | 6 | 0 |
| student-4 | 6 | 0 |
| student-5 | 6 | 0 |

| Result | Owner | Category | Check | Request | Detail | ms |
|---|---|---|---|---|---|---|
| PASS | shared | frontend | Shared home page | `GET /` | HTTP 200 text/html | 2063 |
| PASS | shared | health | Shared edge liveness | `GET /healthz` | HTTP 200, status ok | 0 |
| PASS | student-1 | frontend | data-platform frontend | `GET /features/data-platform/` | HTTP 200 text/html | 14 |
| PASS | student-1 | health | data-platform health | `GET /api/shared-health/data-platform` | HTTP 200, status healthy | 0 |
| PASS | student-2 | frontend | market-intelligence frontend | `GET /features/market-intelligence/` | HTTP 200 text/html | 16 |
| PASS | student-2 | health | market-intelligence health | `GET /api/shared-health/market-intelligence` | HTTP 200, status healthy | 0 |
| PASS | student-3 | frontend | suburb-analytics frontend | `GET /features/suburb-analytics/` | HTTP 200 text/html | 0 |
| PASS | student-3 | health | suburb-analytics health | `GET /api/shared-health/suburb-analytics` | HTTP 200, status ready | 16 |
| PASS | student-4 | frontend | due-diligence frontend | `GET /features/due-diligence/` | HTTP 200 text/html | 0 |
| PASS | student-4 | health | due-diligence health | `GET /api/shared-health/due-diligence` | HTTP 200, status healthy | 0 |
| PASS | student-5 | frontend | buyer-workspaces frontend | `GET /features/buyer-workspaces/` | HTTP 200 text/html | 15 |
| PASS | student-5 | health | buyer-workspaces health | `GET /api/shared-health/buyer-workspaces` | HTTP 200, status healthy | 0 |
| PASS | student-1 | crud | CRUD source definition: create | `POST /api/data-platform/v1/sources` | HTTP 201, id 28671bbe-0737-46b6-893f-7950ca5e4ff6 | 16 |
| PASS | student-1 | crud | CRUD source definition: read | `GET /api/data-platform/v1/sources/28671bbe-0737-46b6-893f-7950ca5e4ff6` | HTTP 200, name matches | 0 |
| PASS | student-1 | crud | CRUD source definition: update | `PUT /api/data-platform/v1/sources/28671bbe-0737-46b6-893f-7950ca5e4ff6` | HTTP 200, notes changed | 16 |
| PASS | student-1 | crud | CRUD source definition: confirm update | `GET /api/data-platform/v1/sources/28671bbe-0737-46b6-893f-7950ca5e4ff6` | HTTP 200, notes persisted | 0 |
| PASS | student-1 | crud | CRUD source definition: delete | `DELETE /api/data-platform/v1/sources/28671bbe-0737-46b6-893f-7950ca5e4ff6` | HTTP 204 | 15 |
| PASS | student-1 | crud | CRUD source definition: confirm deleted | `GET /api/data-platform/v1/sources/28671bbe-0737-46b6-893f-7950ca5e4ff6` | HTTP 404 after delete | 0 |
| PASS | student-2 | crud | CRUD market case: create | `POST /api/market-intelligence/v1/market-cases` | HTTP 201, id da5f8e2e-928f-4c38-bdd7-e8c047813d48 | 16 |
| PASS | student-2 | crud | CRUD market case: read | `GET /api/market-intelligence/v1/market-cases/da5f8e2e-928f-4c38-bdd7-e8c047813d48` | HTTP 200, name matches | 15 |
| PASS | student-2 | crud | CRUD market case: delete | `DELETE /api/market-intelligence/v1/market-cases/da5f8e2e-928f-4c38-bdd7-e8c047813d48` | HTTP 200 | 16 |
| PASS | student-2 | crud | CRUD market case: confirm deleted | `GET /api/market-intelligence/v1/market-cases/da5f8e2e-928f-4c38-bdd7-e8c047813d48` | HTTP 404 after delete | 0 |
| PASS | student-3 | crud | CRUD saved suburb comparison: create | `POST /api/suburb-analytics/v1/suburb-comparisons` | HTTP 201, id b232bc7a-0f5a-4b7a-8117-9b4a8dc387f8 | 16 |
| PASS | student-3 | crud | CRUD saved suburb comparison: read | `GET /api/suburb-analytics/v1/suburb-comparisons/b232bc7a-0f5a-4b7a-8117-9b4a8dc387f8` | HTTP 200, name matches | 0 |
| PASS | student-3 | crud | CRUD saved suburb comparison: delete | `DELETE /api/suburb-analytics/v1/suburb-comparisons/b232bc7a-0f5a-4b7a-8117-9b4a8dc387f8` | HTTP 200 | 15 |
| PASS | student-3 | crud | CRUD saved suburb comparison: confirm deleted | `GET /api/suburb-analytics/v1/suburb-comparisons/b232bc7a-0f5a-4b7a-8117-9b4a8dc387f8` | HTTP 404 after delete | 16 |
| PASS | student-4 | crud | CRUD site review: create | `POST /api/due-diligence/v1/site-reviews` | HTTP 201, id 985d9632-a3b0-4896-8cf6-fcd8007cac12 | 14 |
| PASS | student-4 | crud | CRUD site review: read | `GET /api/due-diligence/v1/site-reviews/985d9632-a3b0-4896-8cf6-fcd8007cac12` | HTTP 200, title matches | 16 |
| PASS | student-4 | crud | CRUD site review: delete | `DELETE /api/due-diligence/v1/site-reviews/985d9632-a3b0-4896-8cf6-fcd8007cac12` | HTTP 200 | 0 |
| PASS | student-4 | crud | CRUD site review: confirm deleted | `GET /api/due-diligence/v1/site-reviews/985d9632-a3b0-4896-8cf6-fcd8007cac12` | HTTP 404 after delete | 0 |
| PASS | student-5 | crud | CRUD buyer case: create | `POST /api/buyer-workspaces/v1/buyer-cases` | HTTP 201, id b2b7f47e-3baf-4122-8a92-8384e80c770e | 31 |
| PASS | student-5 | crud | CRUD buyer case: read | `GET /api/buyer-workspaces/v1/buyer-cases/b2b7f47e-3baf-4122-8a92-8384e80c770e` | HTTP 200, name matches | 0 |
| PASS | student-5 | crud | CRUD buyer case: delete | `DELETE /api/buyer-workspaces/v1/buyer-cases/b2b7f47e-3baf-4122-8a92-8384e80c770e` | HTTP 200 | 16 |
| PASS | student-5 | crud | CRUD buyer case: confirm deleted | `GET /api/buyer-workspaces/v1/buyer-cases/b2b7f47e-3baf-4122-8a92-8384e80c770e` | HTTP 404 after delete | 16 |
| PASS | shared | ai | AI tier disabled by default | `GET /api/shared-health/ai-mode` | disabled: HTTP 503, code ai_disabled | 0 |

Every CRUD case creates a uniquely named record through the owning feature's public API, reads it back, updates it where the feature registers an update, deletes it and confirms the delete. No credentials are sent.

| Service | Image |
|---|---|
| f1-backend | `ps-rehearsal-registry:5000/propertyscope/f1-backend:927801df23afd9deb11a806b13ecf7789f40bfd9-dirty@sha256:394c36a73f3924969511e9fa87aac0751d04284a49036022e1b598048611da83` |
| f1-db-api | `ps-rehearsal-registry:5000/propertyscope/f1-db-api:927801df23afd9deb11a806b13ecf7789f40bfd9-dirty@sha256:28f9ad16daa0f125f6ce03673f7e8ce98d4e4ed73bc80312e63b1f945bb0b1f4` |
| f1-db-loader | `ps-rehearsal-registry:5000/propertyscope/f1-db-loader:927801df23afd9deb11a806b13ecf7789f40bfd9-dirty@sha256:02e7eb69aca8facf801b36f7842b3681dd77008ff93673e05f8efdbb521786c9` |
| f1-frontend | `ps-rehearsal-registry:5000/propertyscope/f1-frontend:927801df23afd9deb11a806b13ecf7789f40bfd9-dirty@sha256:26a07b7208d52c484fc54d23201bfe23c1865bd77df444c090ecc4857243066d` |
| f1-postgres | `ps-rehearsal-registry:5000/propertyscope/mirror/postgis:16-3.4@sha256:44126d872ac91993766c341e369c539e8196614321765d36a6f1bab0419a5fa5` |
| f1-runner | `ps-rehearsal-registry:5000/propertyscope/f1-runner:927801df23afd9deb11a806b13ecf7789f40bfd9-dirty@sha256:a393be7bd87be240d70ba4f466e922ba12e8b8cd966ff0a3f71c30e6f5368d0b` |
| f2-backend | `ps-rehearsal-registry:5000/propertyscope/f2-backend:927801df23afd9deb11a806b13ecf7789f40bfd9-dirty@sha256:ced463a137e5260516b4bb96a206dc1d6a171bfcccf9aa961c99fe8107335248` |
| f2-db-api | `ps-rehearsal-registry:5000/propertyscope/f2-db-api:927801df23afd9deb11a806b13ecf7789f40bfd9-dirty@sha256:202836e5a0d436708e5fb1252dfb141501ecbfd42271f08caaacfaa943ef6d4a` |
| f2-frontend | `ps-rehearsal-registry:5000/propertyscope/f2-frontend:927801df23afd9deb11a806b13ecf7789f40bfd9-dirty@sha256:eec6723a8ee43e1c63e8a435706ade67f27510ae37185776f1196332e6f79f72` |
| f3-backend | `ps-rehearsal-registry:5000/propertyscope/f3-backend:927801df23afd9deb11a806b13ecf7789f40bfd9-dirty@sha256:8530f57bb47b4b44aa4ff6f74f5875247adf6dd6516d0567bde2a1b1d56ff2eb` |
| f3-database | `ps-rehearsal-registry:5000/propertyscope/f3-database:927801df23afd9deb11a806b13ecf7789f40bfd9-dirty@sha256:ebd4efa9936a42f8176e1c38408a8737b4dcc47a7ab20e143d2c6ca6f44e0d31` |
| f3-frontend | `ps-rehearsal-registry:5000/propertyscope/f3-frontend:927801df23afd9deb11a806b13ecf7789f40bfd9-dirty@sha256:511728608d69c2c94cdf0a63c50e0e00db306475b45c4f51887ab4bd8199077b` |
| f4-backend | `ps-rehearsal-registry:5000/propertyscope/f4-backend:927801df23afd9deb11a806b13ecf7789f40bfd9-dirty@sha256:ad4945829ef8e09ea765e826a59dfa04204dea1df08b4bbf1b4c92c7ff5d8d3d` |
| f4-db-api | `ps-rehearsal-registry:5000/propertyscope/f4-db-api:927801df23afd9deb11a806b13ecf7789f40bfd9-dirty@sha256:1ae947b5704e1b25814359bb1b4c29edb5d095d63761c3e50cfe0144fc3b9f2d` |
| f4-frontend | `ps-rehearsal-registry:5000/propertyscope/f4-frontend:927801df23afd9deb11a806b13ecf7789f40bfd9-dirty@sha256:7c20662d19d5b7e37db5424bf1fb96bc78edadc65ac5a6381acf49aea2427004` |
| f4-postgres | `ps-rehearsal-registry:5000/propertyscope/mirror/postgis:16-3.4@sha256:44126d872ac91993766c341e369c539e8196614321765d36a6f1bab0419a5fa5` |
| f5-backend | `ps-rehearsal-registry:5000/propertyscope/f5-backend:927801df23afd9deb11a806b13ecf7789f40bfd9-dirty@sha256:255acfb0bb34db58b7051013bf88cdf130cd2564e1a01e417ddb07a3d75f0cc2` |
| f5-db-api | `ps-rehearsal-registry:5000/propertyscope/f5-db-api:927801df23afd9deb11a806b13ecf7789f40bfd9-dirty@sha256:bb282c95e8f5df1045a741dcdb5bd1f2a0550dff38da2d342318e4368ef86419` |
| f5-frontend | `ps-rehearsal-registry:5000/propertyscope/f5-frontend:927801df23afd9deb11a806b13ecf7789f40bfd9-dirty@sha256:fc20ad123f398c0def2a6b3639e6fd209a85be84ba50d37c3febb2666e423e53` |
| shared-edge-proxy | `ps-rehearsal-registry:5000/propertyscope/mirror/caddy:2.10.2-alpine@sha256:d8c17a862962def15cde69863a3a463f25a2664942eafd7bdbf050e9c3116b83` |
| shared-frontend | `ps-rehearsal-registry:5000/propertyscope/shared-frontend:927801df23afd9deb11a806b13ecf7789f40bfd9-dirty@sha256:5b4187dcbc92ca6c434d8617d35debacadc66e78afeec39c877970da4e467919` |
