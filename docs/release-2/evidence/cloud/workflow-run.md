# Cloud Deployment workflow run (AI-off baseline)

| Item | Value |
|---|---|
| Workflow | `.github/workflows/cloud-deployment.yml` (*Cloud Deployment*) |
| Run | [40041985429](https://github.com/MattShelton04/41026ASDProject/actions/runs/40041985429), attempt 1 |
| Trigger | `workflow_dispatch` on `main`, input `provision=false`, by MattShelton04 |
| Commit / image tag | `7b3fb43728582d21bb8c9722405c040e3c18cbf2` |
| Started / finished | 2026-10-23 23:51:38 UTC / 2026-10-24 00:09:48 UTC |
| `verify-ci` | success (23:51:41–23:56:18 UTC; waited for Integration CI and Student 1–5 CI on this commit) |
| `build-validate` | success (23:56:20–23:57:05 UTC) |
| `deploy` | success (00:00:20–00:09:48 UTC) |
| `production` approval | Approved by MattShelton04 before the `deploy` job started at 00:00:20 UTC |
| AI tier | Off (`PROPERTYSCOPE_CLOUD_AI=false`; the workflow always deploys with AI off) |
| Result | 21/21 containers, smoke 37/37 with 0 skipped, AI-mode `503 ai_disabled`, B5 `ENDPOINT_SECURITY_FAILURES=0` |

## Artifacts downloaded

| Artifact | Copied here |
|---|---|
| `cloud-deployment-7b3fb43728582d21bb8c9722405c040e3c18cbf2` | `cloud-deployment-report.{md,json}`, `cloud-smoke.{json,md}`, `release-gate.{json,md}`, `logs/{deploy,push,smoke}.log`, `vm-deploy.log`, `vm-status.log`, `endpoint-security.txt` |
| `image-build-7b3fb43728582d21bb8c9722405c040e3c18cbf2` | `image-build.{json,md}`, `logs/build.log` |
| `release-gate-7b3fb43728582d21bb8c9722405c040e3c18cbf2` | Not copied: the deploy-time re-check in `release-gate.*` supersedes it |

`provision` was skipped (`provision=false`), so there is no `logs/provision.log`. `outputs.txt`,
`image-tag.txt` and `public-url.txt` are not copied; the report records their values. No
run-command payload, `.env.azure` or secret value is in any copied file.

`data-security.txt` (B6) was run from a laptop against this deployment at 2026-10-24 00:13 UTC
with `AZURE_CLIENT_ID` set, so the OIDC check is included: 43 PASS, 0 FAIL.

## Earlier runs

- [39846161362](https://github.com/MattShelton04/41026ASDProject/actions/runs/39846161362)
  (22 October, `0b7124f9`) succeeded with smoke 29 passed and 2 skipped: the Feature 2 and 4 CRUD
  cases ran while the just-restarted `f1-db-api` answered its first searches `503
  read_budget_exceeded`. #181 makes the smoke retry those searches; this run is the result.
- [39112162750](https://github.com/MattShelton04/41026ASDProject/actions/runs/39112162750)
  (18 October, `3c25c083`): the first complete AI-off evidence, smoke 37/37. Its release decision
  (RELEASE, 19 October) is superseded by the decision recorded on this run's review.
