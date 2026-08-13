# Student 1

- Name: Matthew Shelton
- Student ID: 24763373
- UTS email: matthew.n.shelton@student.uts.edu.au
- Feature: PropertyScope Data Platform and Property Discovery (Feature 1)

## Ownership

- `frontend/`: assigned feature's frontend microservice
- `backend/`: assigned feature's backend/API microservice and AI interaction
- `database/`: assigned feature's schema, migrations, and seed data
- `tests/`: unit and integration tests for the assigned microservices
- `Dockerfile`: container definition for the assigned services

The completed feature must support CRUD, contain at least ten records per table,
integrate with the unified home page and shared styling, interact with the
approved LLM, and remain part of the integrated group application.

## Feature boundary

PropertyScope owns registered source acquisition, reproducible ingestion evidence, the
canonical property/address registry, quality-gated immutable dataset releases, and bounded
property discovery. Other features receive versioned artifacts over HTTP and import them into
their own stores; they never access this feature's PostgreSQL/PostGIS database directly.

Version-controlled source/job configuration lives in `config/`, HTTP and release schemas in
`contracts/`, and persistence-neutral Pydantic/domain policy in
`backend/src/propertyscope_data_platform/`. Checked-in fixture data is synthetic and explicitly
licensed; live and licensed source artifacts remain outside Git.

The default stack deliberately exercises every import profile with deterministic synthetic
records. The opt-in `--full-data` runner currently has one connected live transport: the NSW
Department of Education schools master CSV. It downloads the official bounded extract, verifies
its media/byte/row limits, parses it into the canonical schools contract and sends it through the
same artifact, serial loader, candidate and quality path. G-NAF, PSI and BOCSAR remain catalogued
until their source-scale streaming transports are connected; full-data runs for those profiles
fail closed and never silently substitute fixture records.
