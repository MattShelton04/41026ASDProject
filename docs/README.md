# Project documentation

Store maintained project documentation here throughout all three releases.

- [Feature 1 reference-data integration](release-1/reference-data-integration-plan.md): approved datasets,
  producer/consumer boundaries, implementation sequence and validation approach.
- [Reference-data operations](release-1/reference-data-operations.md): reproducible job setup,
  concurrent acquisition, complete-source scope, capacity and recovery.
- [Complete local reference validation](reviews/feature-1-reference-live-e2e-2026-09-13.md):
  actual candidate counts, geometry flags, artifact hashes and measured stage durations.
- [Dataset audit](reviews/feature-1-dataset-audit-2026-09-13.md): earlier local-state observations
  and dataset recommendations, explicitly distinct from application capabilities.

- [Shared setup refinement audit](reviews/shared-setup-refinement-2026-09-08.md): reviewed
  findings, implementation plan, regression evidence and runtime validation.
- [Feature 1 data performance](reviews/feature-1-data-performance-2026-09-09.md): data flows,
  query analysis, measured changes and fresh-environment validation.
- [Feature 1 operator UI follow-up](ui/feature-1-operator-improvements.md): live observations,
  running-job design, logs and notification suggestions for the next UI pass.

## First-class documentation map

- [Root README](../README.md): current repository status, approved team allocation, and quick start
- [Approved feature scope](architecture/registered-feature-scope.md): tutor-approved team ownership,
  feature purposes, minimum frontend/backend/database boundaries, and implementation-status caveat
- [Contributing guide](../CONTRIBUTING.md): current developer workflow and canonical commands
- [Agent instructions](../AGENTS.md): current coding-agent ownership and quality rules
- [Release 0 index](release-0/README.md): current implementation/evidence navigation and release gates
- [Release 1 Shared/Feature 1 handoff](release-1/shared-feature-1-handoff.md): current local runtime,
  reviewed implementation, architecture/interaction diagrams, evidence and owner boundaries
- [Release 1 feature adoption](release-1/feature-adoption.md): registered tool/corpus integration and
  grounded source UI for independently owned features
- [Release 1 delivery plan](release-1/release-1-delivery-plan.md): earlier course interpretation and
  wider five-feature checklist; newer supplied rubric/ADR-043 supersede runtime assumptions
- [Release 0 technical report](reports/release-0-technical-report.md): final report source, evidence map,
  rubric traceability, and the frozen submitted [`41026Group20Release0Report.pdf`](reports/submissions/release-0/41026Group20Release0Report.pdf)
- [Release 1 technical report](reports/release-1-technical-report.md): draft report source, word
  budget and outstanding items; build with `scripts/build_release1_report.py`
- [Shared-platform design](architecture/shared-platform-design.md): living cross-release
  service and contract design
- [Feature integration contract](architecture/feature-integration-and-experience-contract.md): canonical
  routes, cross-feature HTTP/publication flows, shared UI rules, and onboarding gates
- [Agent-run state machine](architecture/agent-run-state-machine.md): normative Release 0
  execution/recovery model
- [OpenAI API operations](release-0/openai-api-operations.md): provider/profile background;
  [Release 1 host runtime](release-1/host-runtime.md) supersedes earlier container lifecycle/secret wiring
- [Feature onboarding](release-0/feature-onboarding.md): requirements for approved student
  vertical slices

The root documents and the files named above are maintained guidance. ADRs are durable
decision records. The [initial scaffold record](architecture/repository-architecture.md),
`architecture/reviews/`, and dated evidence retain point-in-time history; read their
status/date rather than treating historical statements as current implementation state.

- `architecture/`: individual and integrated architecture diagrams
- `reports/`: working report content and final group technical reports
- `release-0/`, `release-1/`, `release-2/`: release-specific plans and evidence
- `deliverables/`: independent deliverable packages and cross-cutting overhaul records

Do not commit secrets, private credentials, or disposable generated files.
