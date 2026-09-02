# Release 0

The Shared platform and Feature 1 form an operational Release 0 candidate slice. Features 2–5 are
approved but not implemented or integrated, so the repository is not yet a complete group
submission.

## Start here

- [`../reports/release-0-technical-report.md`](../reports/release-0-technical-report.md): current
  assignment-aligned report scaffold, evidence map, rubric traceability, and remaining gates
- [`feature-onboarding.md`](feature-onboarding.md): requirements and executable onboarding checks for
  an approved student vertical slice
- [`feature-client-adoption.md`](feature-client-adoption.md): independent data-client and Shared
  assistant integration recipe for Features 2–5
- [`openai-api-operations.md`](openai-api-operations.md): provider configuration, file-secret
  handling, live diagnostic, and troubleshooting
- [`propertyscope-feature-1-implementation-plan.md`](propertyscope-feature-1-implementation-plan.md):
  Feature 1 service, data, API, AI, testing, and evidence design
- [`bocsar-parquet-adoption.md`](bocsar-parquet-adoption.md): reusable implementation prompt,
  rollout plan and rollback constraints for the sparse BOCSAR canonical artifact
- [`psi-parquet-adoption.md`](psi-parquet-adoption.md): implementation prompt, rollout and
  measurement plan for the partition-aware PSI canonical artifact
- [`ai-mode-operations-interface-plan.md`](ai-mode-operations-interface-plan.md): implemented local
  read-only operations view and remaining remote-access decisions

The [27 August readiness assessment](readiness-assessment-2026-08-27.md) is a dated baseline. Use the
technical report and current executable checks for later implementation/test status.

## Implemented baseline

- Shared HTMX product shell, feature registry, status/evidence/roadmap views, mapping, and AI chat
- durable AI-mode Plan -> Act -> Observe -> Adapt runs with versioned prompts, allowlisted tools,
  recovery, and human-review gates
- manifest-driven deployment projections that expose only enabled services and routes
- Feature 1 frontend, backend, runner, database API, loader, and PostgreSQL/PostGIS services
- complete registered-source acquisition, candidate review, publication/activation evidence, and
  accepted property/address/sale-history projections
- Integration CI plus Student 1 browser and integrated-container checks

All shared views consume public HTTP projections. No service imports another student's production
code or accesses another feature's database.

## Evidence commands

```text
uv run python scripts/check.py
uv run scripts/dev.py stack up --offline
uv run scripts/dev.py stack status
uv run scripts/dev.py operator report
```

The offline stack validates deterministic service/data paths without a model credential. Live AI
evidence requires the approved provider configuration; official-source acquisition starts only when
an operator explicitly launches a job.

## Remaining group gates

- implement and integrate Features 2–5, including CRUD, owned persistence, AI paths, tests, and CI
- retain durable OpenAI/model and Feature 1 PostgreSQL/PostGIS approval evidence
- prove at least ten deterministic records in every assessed table
- capture final five-feature health, endpoint/NFR, Compose, workflow, screenshot, and AI-run evidence
- complete contribution/commit/attendance records, publish the maximum ten-minute group video, and
  export the final report PDF
