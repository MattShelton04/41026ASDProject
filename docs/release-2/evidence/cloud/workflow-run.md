# Cloud Deployment workflow run (AI-off baseline)

| Item | Value |
|---|---|
| Workflow | `.github/workflows/cloud-deployment.yml` (*Cloud Deployment*) |
| Run | [39112162750](https://github.com/MattShelton04/41026ASDProject/actions/runs/39112162750), attempt 1 |
| Trigger | `workflow_dispatch` on `main`, input `provision=false`, by MattShelton04 |
| Commit / image tag | `3c25c083e09e5f170767e63655593c0e5b9f1e27` |
| Started / finished | 2026-10-18 08:37:28 UTC / 08:52:07 UTC |
| `verify-ci` | success (08:37:31–08:37:46 UTC) |
| `build-validate` | success (08:37:49–08:38:31 UTC) |
| `deploy` | success (08:41:27–08:52:06 UTC) |
| `production` approval | Approved by MattShelton04 before the `deploy` job started at 08:41:27 UTC |
| AI tier | Off (`PROPERTYSCOPE_CLOUD_AI=false`; the workflow always deploys with AI off) |

## Artifacts downloaded

| Artifact | Copied here |
|---|---|
| `cloud-deployment-3c25c083e09e5f170767e63655593c0e5b9f1e27` | `cloud-deployment-report.{md,json}`, `cloud-smoke.{json,md}`, `release-gate.{json,md}`, `logs/{deploy,push,smoke}.log`, `vm-deploy.log`, `vm-status.log`, `endpoint-security.txt` |
| `image-build-3c25c083e09e5f170767e63655593c0e5b9f1e27` | `image-build.{json,md}`, `logs/build.log` |
| `release-gate-3c25c083e09e5f170767e63655593c0e5b9f1e27` | Not copied: the deploy-time re-check in `release-gate.*` supersedes it |

`provision` was skipped (`provision=false`), so there is no `logs/provision.log`. `outputs.txt`,
`image-tag.txt` and `public-url.txt` are not copied; the report records their values. No
run-command payload, `.env.azure` or secret value is in any copied file.

## Earlier run the same day

[39109808841](https://github.com/MattShelton04/41026ASDProject/actions/runs/39109808841)
(08:00–08:14 UTC, same commit) also succeeded, with smoke 29 passed and 2 skipped: the Feature 2
and 4 CRUD cases could not find a published property because Feature 1's property search answered
`503 read_budget_exceeded` right after `f1-db-api` restarted. It was re-run to capture complete
CRUD evidence; its artifacts are not copied.
