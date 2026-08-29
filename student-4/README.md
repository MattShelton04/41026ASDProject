# Student 4

- Name: Michael White
- Student ID: 24846267
- UTS email: Michael.h.white@student.uts.edu.au
- Feature: Site, Planning, and Building Due Diligence (Feature 4)

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

Provide an evidence-based site due-diligence workspace using accepted PropertyScope planning,
environmental, strata and building information. The feature distinguishes confirmed observations,
non-intersections, partial coverage and unavailable coverage, and does not certify compliance,
safety or legal suitability.

- Frontend: site-review CRUD; verified property selection; source-attributed planning controls;
  supported environmental map layers; strata/building-order/tribunal evidence; explicit evidence
  states; editable checklists/questions/notes/disposition/status; and an AI-generated professional-
  verification question pack.
- Backend/API: site-review CRUD; Feature 1 property validation without database access; versioned
  evidence import; constraint/source retrieval; bounded GeoJSON; match method/confidence; validated
  evidence states; bounded Plan → Act → Observe → Adapt question generation; health and readiness.
- Database: `constraint_observation`, `building_observation` and `site_review`, each with at least ten
  deterministic records.

The approved allocation and complete minimum boundary are maintained in the
[approved feature scope](../docs/architecture/registered-feature-scope.md). This README records
ownership and planned scope only; no Feature 4 implementation is claimed yet.
