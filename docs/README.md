# Project documentation

Store maintained project documentation here throughout all three releases.

## First-class documentation map

- [Root README](../README.md): current repository status, approved team allocation, and quick start
- [Approved feature scope](architecture/registered-feature-scope.md): tutor-approved team ownership,
  feature purposes, minimum frontend/backend/database boundaries, and implementation-status caveat
- [Contributing guide](../CONTRIBUTING.md): current developer workflow and canonical commands
- [Agent instructions](../AGENTS.md): current coding-agent ownership and quality rules
- [Release 0 index](release-0/README.md): current implementation/evidence navigation and release gates
- [Release 0 technical report](reports/release-0-technical-report.md): final report source, evidence map,
  rubric traceability, and reproducible [`41026Group20Release0Report.pdf`](reports/41026Group20Release0Report.pdf)
- [Shared-platform design](architecture/shared-platform-design.md): living cross-release
  service and contract design
- [Feature integration contract](architecture/feature-integration-and-experience-contract.md): canonical
  routes, cross-feature HTTP/publication flows, shared UI rules, and onboarding gates
- [Agent-run state machine](architecture/agent-run-state-machine.md): normative Release 0
  execution/recovery model
- [OpenAI API operations](release-0/openai-api-operations.md): canonical provider setup,
  secret handling, and troubleshooting guide
- [Feature onboarding](release-0/feature-onboarding.md): requirements for approved student
  vertical slices

The root documents and the files named above are maintained guidance. ADRs are durable
decision records. The [initial scaffold record](architecture/repository-architecture.md),
`architecture/reviews/`, and dated evidence retain point-in-time history; read their
status/date rather than treating historical statements as current implementation state.

- `architecture/`: individual and integrated architecture diagrams
- `reports/`: working report content and final group technical reports
- `release-0/`, `release-1/`, `release-2/`: release-specific plans and evidence

Do not commit secrets, private credentials, or disposable generated files.
