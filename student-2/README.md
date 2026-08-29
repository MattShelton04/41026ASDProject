# Student 2

- Name: Burhan Naeem
- Student ID: 24764134
- Email: Burhan.Naeem@wisetechglobal.com
- Feature: Property Sales Explorer and Market Cases (Feature 2)

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

Provide an evidence-based property-sales explorer using accepted NSW Property Sales Information
releases from Feature 1. Users can inspect recorded sale history and simple deterministic market
summaries, save research cases, and request AI explanations that cite selected evidence and clearly
state missing data and limitations. The feature does not estimate value or recommend whether to buy.

- Frontend: market-case CRUD; verified property/date selection; attributed sale records; sample
  count, median price and transaction-volume summaries; filters, notes and status; AI explanations;
  and source-release, exclusion, insufficient-data and AI-unavailable states.
- Backend/API: market-case CRUD; Feature 1 property-reference validation; versioned sales-release
  import; deterministic sale-history and summary calculations; validated dates/filters; bounded
  AI-mode evidence workflow; health and readiness.
- Database: `sale_observation` and `market_case`, each with at least ten deterministic records.

The approved allocation and complete minimum boundary are maintained in the
[approved feature scope](../docs/architecture/registered-feature-scope.md). This README records
ownership and planned scope only; no Feature 2 implementation is claimed yet.
