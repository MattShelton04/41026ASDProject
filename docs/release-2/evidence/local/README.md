# Local deployment evidence (R2-41)

This folder is the local deployment report for Release 2. It shows the integrated application
running locally: the feature services in Docker Compose, and AI-mode, MCP, RAG and the Release 2
Multi-Agent Server as separate host processes outside any container. It includes the logs of a
multi-server system test, one log per terminal. The plan item is G1 in
[`parts/shared.md`](../../parts/shared.md).

Every file except this README is written by
[`scripts/capture_local_deployment.py`](../../../../scripts/capture_local_deployment.py) against
the running stack. Nothing is edited by hand. To refresh the evidence, run the capture again and
commit the result.

## Files

| File | Contents |
|---|---|
| [`local-deployment-report.md`](local-deployment-report.md) / `.json` | Verdict and failures, commit, branch and Compose project. Every container with its state and health. Every host service with its launcher and listener PIDs, readiness, interpreter and capability flags, and the facts that show it is not containerised. The edge home page and each feature's frontend and health through the edge. One create, read, delete and confirm-deleted round trip per feature. Feature 1 record counts and the data label. Direct MCP, RAG, AI-mode and Multi-Agent probes. The terminal Multi-Agent run. **Log observations**: tracebacks and error-level lines any server logged in the window. These are shown but are not checks |
| `terminal-1-compose.log` | Terminal 1, the Compose stack: the containers at capture start, then every container's output during the capture window (`docker logs --since`), merged by timestamp |
| `terminal-2-ai-mode.log` | Terminal 2: what AI-mode wrote to `.propertyscope-runtime/host/ai-mode.log` during the window, after a few lines of earlier context |
| `terminal-3-mcp.log` | Terminal 3: the same for MCP (the Multi-Agent Worker's tool calls arrive here as `POST /mcp`) |
| `terminal-4-rag.log` | Terminal 4: the same for RAG. RAG writes no request log, so the file says how many direct probes it answered in the window |
| `terminal-5-multi-agent.log` | Terminal 5: the same for the Multi-Agent Server (structured lines carry the run ID) |
| `terminal-6-system-test.log` | Terminal 6, the system test: the capture's own transcript. It holds every check, every terminal command with its output and exit code, and the live Planner → Worker → Reviewer → human trail of the run |
| [`multi-agent-run/`](multi-agent-run/summary.md) | `multi-agent-server export` of that run: `run.json`, `workflow_history.jsonl`, `coordination_audit.jsonl`, `template.json`, `summary.md` |

The **Lines with this capture's IDs** column in the report counts log lines that carry the
capture's `X-Request-ID` prefix (`local-deploy-`) or the Multi-Agent run ID. These lines show the
same requests passing through the edge, the feature containers and the host servers.

## Reproduce it

### One command

```text
uv run scripts/dev.py stack up                  # Compose + host AI services in combined mode
uv run scripts/dev.py stack status              # every container healthy, four host services ready
uv run python scripts/capture_local_deployment.py
```

The capture never starts, stops or reconfigures anything. It exits 1 when a check fails, and the
failure appears in the report's **Failures** section. Useful options:

- `--decision approve|reject` (default `reject`): the scripted decision it records.
- `--multi-agent-run-id ID`: capture a run that a person has already decided (see terminal 6
  below).
- `--no-crud`: skip the CRUD round trips.
- `--output-dir DIR`: write somewhere else. Use this for trial runs, so this folder is not
  overwritten.

### Several real terminals

Each host service can run in the foreground of its own terminal. The terminal then shows that
server's output live while the system test runs. Use one terminal per row, from the repository
root:

| Terminal | Command | What it shows |
|---|---|---|
| 1 | `uv run scripts/dev.py stack up`, then `uv run scripts/dev.py ai stop`, then `uv run scripts/dev.py stack logs` | Starts Compose (and the managed host services). Hands the host services to terminals 2–5. Follows every container's log |
| 3 | `uv run scripts/dev.py ai serve mcp` | MCP in the foreground |
| 4 | `uv run scripts/dev.py ai serve rag` | RAG in the foreground |
| 2 | `uv run scripts/dev.py ai serve ai-mode` | AI-mode in the foreground (start it after MCP and RAG) |
| 5 | `uv run scripts/dev.py ai serve multi-agent` | The Multi-Agent Server in the foreground |
| 6 | `uv run python scripts/capture_local_deployment.py` | The system test, which writes this folder |

`ai serve SERVICE` gives the process the same environment that `ai start --mode combined` would:
the existing service tokens, state directories, tool catalogues and capability flags. The
containers already hold the same tokens, so they reach the foreground processes unchanged. Output
goes to the terminal and is also appended to `.propertyscope-runtime/host/<service>.log`. The
capture reads that file, so terminals 2–5 produce the same logs either way. The report lists these
services as `foreground` instead of `managed`. Add `--offline` to `ai serve` when you have no
model key (direct mode only).

To have a person make the human decision instead of the script, run the review interactively in
terminal 6 before the capture:

```text
uv run multi-agent-server run --template f1-release-readiness-review \
  --input '{"release_id": "<candidate release ID>"}' --review --server
uv run python scripts/capture_local_deployment.py --multi-agent-run-id <run ID>
```

When you are done, stop terminals 2–5 with Ctrl+C. Then return to the managed processes with
`uv run scripts/dev.py ai start --mode combined`.

If you would rather keep the managed processes, follow their logs instead:
`Get-Content -Wait -Tail 20 .propertyscope-runtime/host/mcp.log` (PowerShell) or
`tail -f .propertyscope-runtime/host/mcp.log`. The capture is the same.

## Labelling rules

- **Data.** A fresh database holds a **seeded demonstration baseline**: about 10 synthetic
  records per dataset, with release IDs starting `60000000-0000-0000-0000-`. The capture reads the
  accepted releases and their record counts through the edge. It labels each dataset as seeded
  baseline, synthetic fixture, published official release or not loaded, and puts the overall
  label in the report's **Data** row. Describe the data exactly as that row does. Never call
  baseline data real.
- **Agents.** The report records whether the Multi-Agent run used a real model provider (with the
  model names from `run.json`) or the deterministic rule-based provider. It also records whether
  any stage fell back. The server's configuration decides which; the capture only records it.
- **Human decision.** By default the capture records a scripted `reject`, with actor
  `local-deployment-capture` and a note that says so, and the report states that it was scripted.
  The template's workflow never publishes anything, whatever the decision. Use
  `--multi-agent-run-id` to capture a decision that a person made in a terminal.
- **Observations.** Everything in the report comes from the live stack at the time shown. Nothing
  is deterministic or from fixtures, except the agents when the server runs the deterministic
  provider, and the report says when it does.

## Safety

- The CRUD cases are the `scripts/cloud_smoke.py` cases. Each creates a uniquely named record
  through the owning feature's public API, reads it back, deletes it and confirms it is gone, even
  when a later step fails. Feature 1's case also updates its source definition
  (`PUT /api/data-platform/v1/sources/{id}` with the version it read) and reads it again to
  confirm the change, before the delete.
- Logs are stripped of ANSI codes and capped in size (256 KB per host terminal, 512 KB for
  Compose). Redaction removes the host service tokens, any provider key in the environment,
  `Authorization`/token-shaped values, and any line that matches the repository's secret patterns.
  A final scan of the whole folder must find nothing, or the verdict fails.
- Paths inside the checkout are shown relative to it, and paths under your home directory as `~`.
