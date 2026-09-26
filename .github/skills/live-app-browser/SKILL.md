---
name: live-app-browser
description: Start the PropertyScope stack and drive, screenshot and inspect the running application in a real browser (playwright-cli or Playwright for Python). Use when checking a UI or AI-assistant change end to end for any feature, capturing screenshots or evidence, or debugging what a page, API or grounded answer actually does at runtime.
---

# Inspect the live application

Fixture-based checks (`uv run scripts/dev.py ui audit`, `ui smoke`) never touch real services. Use this
skill when you need the real stack: real databases, AI-mode, MCP, RAG and provider answers.

## 1. Start or reuse the stack

```text
uv run scripts/dev.py stack status          # what is already running
uv run scripts/dev.py stack up              # add --offline to run without a model key
uv run scripts/dev.py ai status             # AI-mode, MCP and RAG state
```

- Shared shell: <http://localhost:5100>. Feature frontends use `frontend.host_port_default` in
  `deployment/enabled-features.v1.json` (Feature 1 is 5200). Pages are also reachable through the
  shared edge at the feature's `routes[].path`, e.g. `http://localhost:5100/features/data-platform/`.
- Frontend and container Python code reload on save. Host AI services (`ai-runtime.json` placement
  `host`) do not: after changing `ai-services/` or `shared/contracts`, run
  `uv run scripts/dev.py ai stop` then `uv run scripts/dev.py ai start --mode combined`.
- AI pages: Activity history `http://localhost:5100/operations/ai-mode/`, Knowledge sources
  `http://localhost:5100/operations/ai-mode/knowledge/` (corpora, passages, and a question-ranking test).

## 2. Drive pages with playwright-cli

Install once with `npm install -g @playwright/cli` (or prefix commands with `npx @playwright/cli`).
The browser session persists between commands.

```text
cd <scratch dir>                         # snapshots and screenshots are written relative to where you open
playwright-cli open http://localhost:5200/#assistant
playwright-cli resize 1440 1000
playwright-cli snapshot                  # writes .playwright-cli/page-*.yml with element refs (e12, e121…)
playwright-cli fill e121 "Which datasets does Property data have?"
playwright-cli click e124
playwright-cli screenshot --filename=answer.png           # add --full-page for long pages
playwright-cli console                   # console errors
playwright-cli network                   # requests, including failed API calls
```

- Read the snapshot file and grep for the role and name, e.g. `grep 'button "Send message"'`,
  to get refs. Refs change after navigation or re-render; take a new snapshot before reusing them.
- Hash routes (`#properties`, `#assistant`) do not reload the document; use `playwright-cli reload`
  when you need fresh JavaScript or state.
- Assistant answers take 10-60 s. Wait, then screenshot, or poll the run (step 4).
- Pages with a fixed-height scrolling panel (Activity history, Knowledge sources) only capture the
  viewport with `--full-page`; scroll the element with `playwright-cli eval "document.querySelector('#id').scrollIntoView()"`.

## 3. Batch screenshots with issues

For before/after comparisons, capture many routes in one run. The script logs console errors,
failed requests and HTTP 4xx/5xx per page:

```text
uv run python .github/skills/live-app-browser/capture.py tmp/live-screens \
  home=http://localhost:5100/ assistant=http://localhost:5200/#assistant
```

`failed (net::ERR_ABORTED)` usually means the page cancelled a superseded request, not a fault.
Look at every screenshot you take (open the PNG) rather than trusting the page title. Keep
screenshots under `tmp/` or a scratch directory; they are not committed unless a doc needs one.

## 4. Check what happened behind a page

The shared edge adds the AI-mode service token, so these read-only calls work from the host:

```text
curl -s http://localhost:5100/api/ai-mode/capabilities                     # MCP/RAG readiness
curl -s "http://localhost:5100/api/v1/agent-runs?limit=5"                   # recent runs
curl -s http://localhost:5100/api/v1/operations/agent-runs/<run-id>         # steps, tool calls, final_result
curl -s http://localhost:5100/api/v1/operations/knowledge                   # registered corpora
curl -s "http://localhost:5100/api/v1/operations/knowledge/<feature>/<corpus>/search?q=..."
```

In a run's evidence, check the `context.retrieve.v1` step's query and status, the tool calls, and
`final_result.confidence`, `confidence_reason` and `citations`. A `no_match` retrieval should give
an insufficient-context answer. Feature APIs sit under each feature's backend route, for example
`http://localhost:5200/api/data-platform/v1/...`.

## 5. Report

State which URLs you checked, at which viewport, what you saw, and any console or network
errors. Say which observations came from real provider answers and which from deterministic
validation modes (`uv run scripts/dev.py ai validate mcp|rag`).
