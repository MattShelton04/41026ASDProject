# Student 5

- Name: Derek Song
- Student ID: 24833978
- UTS email: Derek.song@student.uts.edu.au
- Feature: Buyer Journey and Agent Workspace (Feature 5)

## Ownership

- `frontend/`: assigned feature's frontend microservice
- `backend/`: assigned feature's backend/API microservice and AI interaction
- `database/`: assigned feature's schema, migrations, and seed data
- `tests/`: unit and integration tests for the assigned microservices
- `Dockerfile`: container definition for the assigned services

The completed feature must support CRUD, contain at least ten records per table,
integrate with the unified home page and shared styling, interact with the
approved LLM, and remain part of the integrated group application.

## Approved feature boundary

Provide a buyer-journey and agent workspace for organising shortlisted properties, tracking buying
stages, recording notes and tasks, and reviewing relevant research from other PropertyScope
features. AI-assisted summaries and suggested next actions must identify missing information and
limitations.

- Frontend: buyer-case CRUD; shortlist add/remove; journey-stage changes; buyer preferences, notes
  and ratings; task CRUD/completion; related sales, suburb and due-diligence information; AI case
  summaries and suggested next actions; and AI-unavailable/missing-data states.
- Backend/API: buyer-case, shortlist, note and task CRUD; Feature 1 property validation; evidence
  retrieval from other PropertyScope services; stage transitions; input and case-ownership
  validation; bounded AI evidence retrieval, summary and adaptation; health and readiness.
- Database: `buyer_case`, `case_property`, `case_note` and `case_task`, each with at least ten
  deterministic records.

The approved allocation and complete minimum boundary are maintained in the
[approved feature scope](../docs/architecture/registered-feature-scope.md). This README records
ownership and planned scope only; no Feature 5 implementation is claimed yet.
