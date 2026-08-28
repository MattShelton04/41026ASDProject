# Release 0 readiness assessment — 27 August 2026

## Verdict

The Shared platform and Feature 1 form an operational Release 0 candidate slice. They are not yet a
complete Release 0 submission.

This distinction matters because the published assessment grades the integrated five-student group
application and its evidence, not an isolated high-quality feature. Features 2–5 are still
unallocated placeholders, so the repository cannot yet demonstrate the required five integrated
frontend/backend/database feature sets or a complete group showcase.

This review uses the published **Assessment 1 — Release 0**, **ASD 2026 Project Specifications**, the
Canvas **Release 0 sample integrated microservices architecture**, and the repository's executable
tests and current evidence. The Canvas due-date field and Week 5 announcement set the report deadline
to 6 September 2026 at 11:59 pm Sydney time.

## Criterion review

| Release 0 criterion | Shared and Feature 1 evidence | Readiness |
| --- | --- | --- |
| Project setup | Reproducible Python 3.12 workspace, shared repository structure, ownership boundaries and a unified home exist. The other four student owners/features are not allocated. | **Slice ready; group blocked** |
| Frontend, backend/API and database services | Feature 1 has independently deployed frontend, backend, database API/loader, runner and PostgreSQL/PostGIS services with HTTP-only boundaries. | **Feature ready** |
| CRUD and seed data | Feature 1 CRUD is covered in the UI/API and deterministic tests. The specification literally requires at least ten records in every database table; the current README instead relies on ingestion volume and does not provide a per-table seed-count report or an approved interpretation. | **Evidence gap** |
| AI-mode and approved model | Shared AI-mode, durable runs, Feature 1 tools, live provider evaluations and offline degradation exist. The retained evaluation says written approval is still required for the remote Gemini/OpenAI departure from the published Ollama/open-source-model requirement. | **Approval gap** |
| Plan → Act → Observe → Adapt | A bounded persisted state machine, tool evidence, recovery behavior, review gates and deterministic/live scenarios are implemented and documented. | **Ready for the slice** |
| Prompt/context management | Versioned planner/adapter prompts, bounded tool contracts, model profiles and real-provider evaluation evidence exist. | **Ready for the slice** |
| GitHub Actions | Integration CI owns the canonical source gate. Student 1 owns browser-form and focused integrated Shared/Feature 1 stack checks. Actions are SHA-pinned and workflow syntax is linted. | **Ready when this PR passes** |
| Docker Compose | The production-like and development Compose models build and run Shared plus Feature 1 with exclusive database ownership. They do not and cannot yet demonstrate the sample five-feature group topology. | **Slice ready; group blocked** |
| Working integrated software | Shared and Feature 1 health, property search, CRUD, ingestion, release review and agent diagnosis have executable coverage and retained live-source evidence. Cross-feature Feature 2–5 journeys cannot run until those owners implement them. | **Slice ready; group blocked** |
| Report and demonstration | Feature 1 marking/evaluation material and design captures exist. `docs/reports/` has no Release 0 technical report, published video URL, final contribution/attendance evidence, or complete five-member demonstration record. | **Not complete** |

## Release gates

Before calling Shared and Feature 1 submission-complete:

1. Retain a durable copy or link for the confirmed Feature 1 PostgreSQL/PostGIS exception.
2. Obtain and retain written approval for the remote OpenAI/Gemini provider choice, or run an
   approved model configuration that satisfies the published requirement.
3. Resolve the literal ten-records-per-table requirement with the tutor and add a reproducible
   database seed-count report. Do not pad operational evidence tables without an approved domain
   interpretation.
4. Accept and publish the intended showcase candidate through the existing human-review boundary so
   current product data is demonstrable.
5. Capture one successful canonical workflow run and one successful Student 1 workflow run for the
   release commit.

The group must also allocate and integrate Features 2–5, complete the report and diagrams, capture
screenshots and contribution/attendance evidence, publish the maximum ten-minute group video, and
rehearse the Week 6 showcase. Those group obligations are outside Feature 1 ownership but remain
hard Release 0 completion gates.
