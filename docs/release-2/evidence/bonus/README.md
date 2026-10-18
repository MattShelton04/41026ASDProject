# Release 2 bonus evidence (B1–B6)

Validation output for the Release 2 bonus tiers on the Azure deployment
(<https://propertyscope-nsw-g20.newzealandnorth.cloudapp.azure.com>). The AI-off baseline and the
release decision are in [`../cloud/`](../cloud/README.md). The cloud review's required
`cloud.ai-disabled` check reads that folder, so AI-tier output belongs here and never there.

| Tier | Result | Evidence |
|---|---|---|
| B1 AI-mode interaction through the app | **PASS** | [`cloud-ai-probe.md`](cloud-ai-probe.md), run `387591f0-be44-4e88-8808-404f32cde8b9` |
| B2 MCP tool call | **PASS** | Same run: `data.releases.v1` called over MCP |
| B3 Grounded RAG answer | **PASS** | Run `56c85266-6cc9-4421-9f49-61794f55e7b3`: 2 citations from the `operator-guidance` corpus, grounding ready |
| B4 Planner → Worker → Reviewer workflow | **PASS** | Run `2058658b-8c85-44ee-bebc-cfc0cd8ab8b8`: Feature 1 release review of the accepted `nsw-suburb-boundaries` release, all three roles completed with model providers, now `awaiting_human` |
| B5 Endpoint security | **PASS** (52 PASS, 0 FAIL) | [`endpoint-security.txt`](endpoint-security.txt) |
| B6 Data security | **PASS** (43 PASS, 0 FAIL) | [`data-security.txt`](data-security.txt) |

## B1–B4: Cloud AI Tier workflow run

| Item | Value |
|---|---|
| Workflow | `.github/workflows/cloud-ai.yml` (*Cloud AI Tier*) |
| Run | [39119158736](https://github.com/MattShelton04/41026ASDProject/actions/runs/39119158736), attempt 1 |
| Trigger | `workflow_dispatch` on `main`, input `action=on`, by MattShelton04 |
| `production` approval | Approved by MattShelton04 |
| Deployed commit / image tag | `817ef779771637629bbfe928c975d640b35aa797`, deployed by *Cloud Deployment* run [39118150364](https://github.com/MattShelton04/41026ASDProject/actions/runs/39118150364) |
| Probe window | 2026-10-18 10:53:59–10:54:46 UTC |
| VM after the run | 21/21 containers running; host units `ai-mode`, `mcp`, `rag` and `multi-agent` active |
| Artifact | `cloud-ai-on-817ef779771637629bbfe928c975d640b35aa797`, copied here unchanged |

The workflow turns the host AI tier on from the deployed commit (`deploy.sh ai on`), then
`deploy.sh ai-probe` runs `scripts/cloud_ai_probe.py` through the public edge with the operator
login. It makes one real interaction per tier, with no fixtures and no deterministic providers:

- **B1, B2:** an assistant turn on Feature 1 (`POST /api/data-platform/v1/assistant/turns`). It
  passes when the run succeeds with OpenAI models, the Shared run record matches, and AI-mode
  calls `data.releases.v1` over the MCP transport.
- **B3:** a grounded question against the Feature 1 `operator-guidance` RAG corpus. It passes
  when the answer cites at least one retrieved chunk and grounding is ready.
- **B4:** a release review (`POST /api/data-platform/v1/release-reviews`) on the Multi-Agent
  Server. It passes when the planner, worker and reviewer stages complete with model providers,
  the plan and review are present, and the run reaches `awaiting_human`. The probe never makes the
  human decision.

The first attempt, run 39117318186 on commit `3c25c083`, passed B1–B3. B4 failed there with
`503 multi_agent_unavailable`, because the Multi-Agent Server was bound to `127.0.0.1` and the
Feature 1 backend container could not reach it. #158 bound it to `0.0.0.0`, as AI-mode already
is. The NSG still admits only ports 443 and 80 from the internet and denies everything else, so
port 5013 stays private. This run is the evidence on the fixed commit.

| File | Content |
|---|---|
| `cloud-ai-probe.md`, `cloud-ai-probe.json` | Per-tier result, preflight (AI-tier marker, service health) and the allowlisted evidence fields of each run |
| `vm-ai-on.log` | `deploy.sh ai on` on the VM: host units started, Compose recreated with AI on |
| `vm-status.log` | VM status after the run, including the `PROPERTYSCOPE_RESULT` summary |
| `logs/ai-on.log`, `logs/ai-probe.log`, `logs/status-{before,after}.log` | Workflow step output |

## B5 and B6

These are copies of the AI-off baseline files in [`../cloud/`](../cloud/README.md):

- B5 came from *Cloud Deployment* run
  [39112162750](https://github.com/MattShelton04/41026ASDProject/actions/runs/39112162750)
  (commit `3c25c083`, `deploy.sh validate-endpoint`).
- B6 came from `deploy.sh validate-data`, run from a laptop against the same deployment on
  18 October.

Outside `docs/`, the B1–B4 deployment (`817ef779`) differs from that commit in three ways:

- the Cloud AI Tier tooling (#156): workflow, `deploy.sh ai-probe` and the probe script;
- the Multi-Agent unit's bind address (#158);
- their tests.

No application service code changed, so B5 and B6 still describe the running site.

## Turning the tier off

Every *Cloud Deployment* run deploys with the AI tier off. *Cloud AI Tier* with `action=off` turns
it off without a deployment. Re-run `action=on` to repeat the probe, and replace these files with
the new artifact.
