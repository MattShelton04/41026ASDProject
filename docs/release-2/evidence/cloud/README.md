# Cloud deployment evidence (R2-43, R2-44, R2-45)

This folder holds the reviewed evidence of the Azure deployment, for criteria 5–7 and 9 and for
the Cloud Deployment Report Review (R2-22). Nothing here is produced by hand. Each file comes
from a deployment run and is copied in after a person has checked it.

**Current state:** no deployment has run yet. The infrastructure and workflow are prepared (see
[deployment/azure/README.md](../../../../deployment/azure/README.md) and
[ADR-048](../../../architecture/decisions/ADR-048-azure-vm-hosting.md)).

## Files

| File | Produced by | Contents |
|---|---|---|
| `cloud-deployment-report.md` / `.json` | `scripts/cloud_deployment_report.py`, run by `cloud-deployment.yml` | The verdict, public URL, commit and image tag, workflow run and gating Integration CI run, stage outcomes, Azure outputs, VM container state, AI flag, per-owner smoke results and B5/B6 results when present |
| `cloud-smoke.json` / `.md` | `scripts/cloud_smoke.py` (`deploy.sh smoke`) | Home page, every feature route and health check, one create→read→delete→confirm case per feature (each owned by its feature), and the AI-disabled check |
| `workflow-run.md` | person | Link to the successful *Cloud Deployment* run, its approval, and the downloaded artifact name |
| `vm-deploy.log` | `deploy.sh deploy` (run-command output) | Pull, `compose up --wait`, seeded-baseline check and `PROPERTYSCOPE_RESULT` summary |
| `release-decision.md` | person, after `dev.py ai review cloud` | The human release decision: approve, approve with conditions, or reject, with reasons |
| `../bonus/endpoint-security.txt`, `../bonus/data-security.txt` | `deploy.sh validate-endpoint` / `validate-data` | Bonus B5 and B6 validation output |

## How to capture

1. Run *Cloud Deployment* (Actions → Cloud Deployment → Run workflow), or let it follow a green
   Integration CI run on `main`. Approve the `production` environment when asked.
2. Download the `cloud-deployment-<sha>` artifact. Copy `report/cloud-deployment-report.md`,
   `report/cloud-deployment-report.json`, `smoke/cloud-smoke.*` and `vm-deploy.log` here.
3. Open the public URL and take screenshots of the home page and each feature for the report
   and the video.
4. Run `uv run scripts/dev.py ai review cloud` (workstream B). It writes
   `../reviews/cloud-review.md` and `cloud-validation-log.jsonl`. Then record the human decision in
   `release-decision.md`.

## Labelling rules

- State whether data is the **seeded demonstration baseline** (about 10 synthetic records per
  dataset) or a published real release. The report records what the VM saw.
- The AI tier is off in the required baseline. Evidence for the bonus AI tiers goes in
  `../bonus/`, never here.
- Never copy secrets, run-command payloads or `.env.azure` into this folder. The workflow artifact
  already excludes payloads, and the logs contain no secret values.
