# Release 0

The Shared platform and all five student feature slices are enabled in the generated Release 0
profile. The final report records each slice's implementation, tests, CI evidence and known
limitations without treating deterministic fixtures as current official data.

## Start here

- [`../reports/release-0-technical-report.md`](../reports/release-0-technical-report.md): final
  assignment-aligned report source, evidence map and rubric traceability
- [`../reports/submissions/release-0/41026Group20Release0Report.pdf`](../reports/submissions/release-0/41026Group20Release0Report.pdf):
  the PDF submitted on Canvas, frozen and never regenerated
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
- five enabled student feature slices with independently owned frontend, backend/API and database
  services
- Integration CI plus `student-1.yml` through `student-5.yml`, with retained successful runs

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

## Recorded limitations

The technical report is the current authority for submission limitations. The main evidence risks
are the remote-provider approval record, Feature 4's unapproved PostgreSQL/PostGIS deviation from
the published SQLite requirement, Feature 1's literal per-table count interpretation, and uneven
feature-specific live-provider records. These are not concealed by the successful deterministic and
container checks.
