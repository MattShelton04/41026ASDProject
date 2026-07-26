# Repository Architecture and Scaffold Record

## Document status

- Status: Initial scaffold implemented; project implementation not started
- Date: 26 July 2026
- Student initiating the work: Matthew Shelton
- Initial AI-assisted engineering tool: OpenAI Codex using GPT-5.6-sol
- Adversarial reviewer: Gemini 3.6 Flash in Antigravity
- Publication: Initial scaffold commit `17c1e76`, pull request #1
- Review state: Adversarial-review improvements accepted by Matthew for
  publication; tutor approval remains required for the six-person team and
  other project decisions identified below

## Purpose

This document records the planning, architectural decisions, implementation
boundary, and validation of the repository's initial scaffold. It began as the
pre-implementation scaffold plan and was updated after the plan was carried
out, preserving both the intent and evidence of the resulting structure.

The product topic, individual features, cloud provider, database engine, and
detailed service architecture remain undecided. The scaffold therefore defines
ownership and integration boundaries without prematurely implementing a
solution.

## Evidence scope

This record can support evidence of:

- AI-assisted requirements analysis, repository design, and documentation
- Early software architecture and source-control planning
- Separation of individual and shared responsibilities
- Incremental release planning
- Validation of the initial repository structure

It does not replace the required individual and integrated software
architecture diagrams, Docker Compose architecture, agentic-loop diagram, or
later MCP, RAG, multi-agent, DevOps, and cloud architecture artefacts. It also
does not demonstrate the project's required Ollama-based Agentic AI
implementation; Codex was used as a development assistant, not as the
application's runtime LLM.

## Sources reviewed

- `ASD_2026_Project_Specifications.txt` and the original 22-page PDF
- The repository-structure diagram in the specification and the supplied image
- `Project_Group_Registration_Form.docx`
- Published 41026 Canvas pages, including team formation, assessment overview,
  subject schedule, subject resources, and the AI Agent Configuration Guide
- Lecture 0 material covering Agile, planning, risk, architecture, DevOps,
  testing, and deployment
- Local 41026 release checklists, semester plan, and content-conflict notes

The current Project Specifications and Assessment Overview were treated as
authoritative where the Canvas FAQ contained older, conflicting assessment
information.

## AI-assisted engineering process

Matthew directed Codex to:

1. Inspect the locally archived 41026 group-project material.
2. Plan the scaffold in Markdown before changing the repository.
3. Follow the supplied repository diagram while adapting it for six students.
4. Record Matthew as Student 1 and leave clear placeholders for other members.
5. Create scaffolding only, without application implementation.
6. Avoid committing or pushing any changes.

Codex reviewed the source material, proposed the structure below, created the
files, detected and corrected an overly broad `build/` ignore rule, and ran the
validation checks recorded in this document. Matthew then authorised the
initial scaffold to be committed, pushed, and opened as pull request #1.
Matthew remains responsible for reviewing, understanding, revising, and
approving the work before submission.

### Adversarial review and iteration

Matthew asked Gemini 3.6 Flash in Antigravity to perform an adversarial review
of the scaffold. The resulting review was saved without being treated as
authoritative, then independently checked by Codex against the repository and
course sources. The original review input is retained at
`reviews/2026-07-26-gemini-antigravity-scaffold-review.md`.

| Review finding | Disposition | Result |
|---|---|---|
| Written specification names workflows `student-N.yml` | Accepted | Renamed all six student workflows; retained `integration-ci.yml` from the repository diagram |
| Six-person approval and ten-minute showcase pressure | Accepted as project risk | Approval remains an open action; the team must plan less than 100 seconds per student after shared introduction and integration coverage |
| Database isolation/container model needs a decision | Accepted as future architecture work | Expanded the open decision; no topology was invented before the project design exists |
| Add active path-filtered workflow triggers now | Deferred | Disabled manual placeholders remain intentional until real build and test commands exist |
| Pre-allocate Student 1-6 ports in Compose | Rejected for the scaffold | The proposal assumes service boundaries and conflicts with course example ports; ports will follow the approved architecture |
| Build the shared UI design system now | Deferred | This would be application implementation; the shared locations already exist for Release 0 work |
| Add test runner scripts now | Deferred | Test locations already exist; runners should be added with the selected runtime and test strategy |
| Commit a six-person registration form | Rejected for the repository | The form requires approval and contains personal information/signatures; it should be handled through the authorised submission channel |

This review cycle demonstrates iterative AI-assisted engineering: generation,
independent challenge by a different model, verification against primary
sources, selective remediation, and recorded rationale for rejected or deferred
recommendations.

## Architectural drivers

- One integrated Agentic AI application must be assembled from individual
  frontend, backend/API, and database microservices.
- Individual work and contribution evidence need clear ownership.
- Shared integration assets must remain separate from student-owned features.
- Architecture must grow incrementally across Releases 0, 1, and 2.
- The complete application must eventually run through one shared Docker
  Compose definition and one shared cloud deployment.
- Secrets, generated artefacts, local databases, and temporary files must not
  enter source control.
- Team-size changes should require predictable, localised edits.

## Repository architecture

```mermaid
flowchart TD
    R[Shared repository]
    R --> W[GitHub Actions workflows]
    R --> D[Documentation and release evidence]
    R --> S[Shared integration components]
    R --> I[Six student workspaces]
    R --> A[Shared AI services]
    R --> U[Build, test, and deploy scripts]

    I --> F[Frontend + backend/API + database + tests]
    F --> S
    S --> C[Integrated Docker Compose application]
    A --> C

    A --> A0[Release 0: AI mode and Ollama]
    A --> A1[Release 1: MCP and RAG]
    A --> A2[Release 2: multi-agent orchestration]
    U --> C
    C --> L[Local deployment]
    C --> P[Release 2 cloud deployment]
```

```text
.
|-- .github/
|   `-- workflows/
|       |-- student-1.yml ... student-6.yml
|       |-- integration-ci.yml
|       `-- cloud-deployment.yml
|-- docs/
|   |-- architecture/
|   |   |-- README.md
|   |   |-- repository-architecture.md
|   |   `-- reviews/
|   |-- reports/
|   |-- release-0/
|   |-- release-1/
|   `-- release-2/
|-- shared/
|   |-- frontend/
|   |   |-- index.html
|   |   |-- css/
|   |   |-- js/
|   |   `-- assets/
|   `-- configuration/
|-- student-1/ ... student-6/
|   |-- README.md
|   |-- frontend/
|   |-- backend/
|   |-- database/
|   |-- tests/
|   `-- Dockerfile
|-- ai-services/
|   |-- ai-mode/
|   |-- mcp-server/
|   |-- rag-server/
|   `-- multi-agent-server/
|-- scripts/
|   |-- build/
|   |-- test/
|   `-- deploy/
|-- .editorconfig
|-- .gitignore
|-- docker-compose.yml
`-- README.md
```

## Architectural decisions

### ADR-001: Six student workspaces

- Decision: Create `student-1` through `student-6` with identical structures.
- Reason: The requested working team size is six and consistent templates make
  ownership clear.
- Consequence: The published brief and registration form currently specify
  five students. The sixth member and feature require tutor or subject
  coordinator approval.
- Change cost: Adding or removing a member requires one `student-N/` directory,
  one student workflow, and roster/integration updates.

### ADR-002: Separate individual and shared components

- Decision: Keep feature work in `student-N/` and team-wide integration in
  `shared/`, `ai-services/`, and the root Compose configuration.
- Reason: This mirrors the course's individual ownership model while retaining
  one integrated application.
- Consequence: Shared code must not become an unowned substitute for individual
  feature contributions.

### ADR-003: Scaffold all release locations early

- Decision: Create directories for later-release services before implementing
  them.
- Reason: The progressive target architecture is visible from the beginning.
- Consequence: Release labels and placeholders must not be misrepresented as
  completed functionality.

### ADR-004: Keep executable placeholders inactive

- Decision: Use a valid empty Compose model and manually triggered workflows
  whose placeholder jobs are disabled.
- Reason: Syntax and repository shape can be validated without creating false
  CI or deployment behaviour.
- Consequence: Real triggers, tests, images, and deployment steps must be added
  after the application architecture is approved.

### ADR-005: Align student workflow names with the written requirements

- Decision: Name student workflows `student-N.yml`.
- Reason: Sections 7.3 and 10.3 repeatedly use these exact names, making them
  the safer compliance choice.
- Consequence: The repository diagram uses `student-N-ci.yml`, so the source
  conflict is recorded here. The additional `integration-ci.yml` from the
  diagram is retained.

## Release evolution

| Release | Repository architecture introduced or extended |
|---|---|
| Release 0 | Student microservices, unified frontend, AI mode/Ollama, Docker Compose, student CI, integration validation |
| Release 1 | MCP server, RAG server, grounded responses, updated local integration and CI |
| Release 2 | Local multi-agent server, pre-commit pytest, post-commit AI-assisted tests, integrated Azure or AWS deployment |

For the Release 2 cloud deployment, MCP, RAG, and multi-agent services remain
disabled according to the current specification.

## Implemented scaffold contents

- Root project overview, team roster, release path, and next decisions
- Six student READMEs and equivalent frontend, backend, database, test, and
  Dockerfile placeholders
- Six student CI placeholders plus integration and cloud workflow placeholders
- Documentation areas for architecture, reports, and Releases 0-2
- Unified frontend and shared configuration locations
- Release-gated AI service locations
- Build, test, and deployment script locations
- Cross-platform editor settings and source-control exclusions
- A syntactically valid but empty Docker Compose definition

## Validation evidence

The following checks were completed after scaffolding:

| Check | Result |
|---|---|
| Six equivalent student workspaces | Passed |
| Six matching student CI workflow files | Passed |
| All planned shared and release directories retained | Passed |
| YAML syntax for eight workflows and Docker Compose | Passed before and after workflow renaming |
| Docker Compose schema validation | Passed |
| `.env.example` and `scripts/build/.gitkeep` visible to Git | Passed |
| Final newlines and trailing-whitespace check | Passed |
| Temporary PDF and DOCX inspection artefacts removed | Passed |
| Initial scaffold publication | Commit `17c1e76`; pull request #1 |
| Adversarial-review changes | Validated and accepted by Matthew for publication in pull request #1 |

## Known open decisions

- Obtain approval for a six-person team and sixth feature.
- Select the project problem and Agentic AI topic.
- Allocate one approved integrated feature to each student.
- Plan the ten-minute showcase so all six students demonstrate their feature
  and LLM interaction while leaving time for integrated context.
- Choose SQLite or PostgreSQL and record the database ownership, isolation,
  persistence, and containerisation model.
- Choose Azure or AWS.
- Define service boundaries, ports, APIs, data ownership, and integration
  contracts.
- Define shared UI conventions and real CI/test commands during Release 0.
- Create the required individual and integrated architecture diagrams as the
  design matures.

## Updating this record

Update this document when an architectural decision changes. Significant
changes should add or revise an ADR, record the reason, identify affected
components, and update the validation evidence. The initial scaffold is
traceable through commit `17c1e76` and pull request
`https://github.com/MattShelton04/41026ASDProject/pull/1`. Later review changes
should record their own commit or pull-request references after publication.
