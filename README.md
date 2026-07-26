# 41026 Advanced Software Development Group Project

Shared repository for the Spring 2026 group project.

The project topic, individual features, cloud provider, and detailed architecture
are still to be decided. This repository currently contains scaffolding only;
there is no runnable application yet.

## Team

This scaffold has room for six students. The published course specification and
registration form currently describe five-person teams, so the six-person team
and sixth individual feature must be confirmed with the tutor or subject
coordinator.

| Student | Name | Student ID | UTS email | Feature |
|---|---|---|---|---|
| 1 | Matthew Shelton | 24763373 | matthew.n.shelton@student.uts.edu.au | To be decided |
| 2 | To be confirmed | To be confirmed | To be confirmed | To be decided |
| 3 | To be confirmed | To be confirmed | To be confirmed | To be decided |
| 4 | To be confirmed | To be confirmed | To be confirmed | To be decided |
| 5 | To be confirmed | To be confirmed | To be confirmed | To be decided |
| 6 | To be confirmed | To be confirmed | To be confirmed | To be decided |

Each student has an equivalent `student-N/` workspace for their frontend,
backend/API, database, tests, Dockerfile, and ownership notes.

## Release path

| Release | Planned scope |
|---|---|
| Release 0 | Integrated microservices, AI mode/Ollama, shared agentic loop, Docker Compose, and student CI |
| Release 1 | Release 0 plus MCP, RAG, and grounded AI responses |
| Release 2 | Release 1 plus multi-agent orchestration, advanced testing, and Azure or AWS deployment |

MCP, RAG, and multi-agent services are intended for local execution. The course
specification requires these services to remain disabled in the Release 2 cloud
deployment.

## Repository guide

- `.github/workflows/`: student, integration, and cloud workflow placeholders
- `docs/`: architecture, reports, and release-specific evidence
- `shared/`: integrated home page, common assets, and configuration templates
- `student-1/` to `student-6/`: individual feature workspaces
- `ai-services/`: shared AI mode, MCP, RAG, and multi-agent service locations
- `scripts/`: shared build, test, and deployment automation
- `docker-compose.yml`: future integrated local application definition
- `docs/architecture/repository-architecture.md`: scaffold plan, architectural
  decisions, AI-assisted process record, and validation evidence

## Next decisions

Before implementation begins, the team should confirm its membership with the
tutor, select and obtain approval for an Agentic AI project topic, allocate one
integrated feature per student, choose SQLite or PostgreSQL, and select Azure or
AWS for Release 2.
