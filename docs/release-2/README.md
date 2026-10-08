# Release 2

Release 2 keeps everything from Release 1 and adds:

- a shared, non-containerised Multi-Agent Server (Planner → Worker → Reviewer → Human Review)
- three new agentic-loop review modes
- pre-commit security scans
- CI tests for two endpoints per student
- deployment of the integrated application to **Azure**

In the baseline cloud deployment, AI-mode, MCP, RAG and Multi-Agent are disabled. Enabling them
is bonus work. The showcase is on 23 October 2026 and the report (`group-20.pdf`) is due on
25 October 2026.

- [Requirements](requirements.md): the brief and rubric restated as numbered requirements, report
  contents and showcase coverage.
- [Implementation plan](implementation-plan.md): key decisions, target architecture, workstreams,
  timeline, evidence layout and risks.
- [Responsibilities by part](parts/README.md): what Shared and each feature must deliver, with a
  plan for each part:
  [Shared](parts/shared.md) · [F1](parts/feature-1.md) · [F2](parts/feature-2.md) ·
  [F3](parts/feature-3.md) · [F4](parts/feature-4.md) · [F5](parts/feature-5.md)

Evidence collected for the report goes in `evidence/`, as described in the implementation plan.
