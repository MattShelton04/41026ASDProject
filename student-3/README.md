# Student 3

- Name: James Huang
- Student ID: 24970865
- UTS email: Zihuang.huang@student.uts.edu.au
- Feature: Suburb, Crime, and Liveability Analytics (Feature 3)

## Ownership

- `frontend/`: assigned feature's frontend microservice
- `backend/`: assigned feature's backend/API microservice and AI interaction
- `database/`: assigned feature's schema, migrations, and seed data
- `tests/`: unit and integration tests for the assigned microservices
- `Dockerfile`: container definition for the assigned services

This directory contains the functional Feature 3 slice. It supports deterministic suburb search,
LGA/amenity filters and sorting, map/place filters, evidence-backed context cards, selected offence
categories, same-period count/rate comparisons with an accessible chart table, saved-comparison
CRUD, property-relative nearby places, and an optional bounded AI assistant. Deterministic views and
CRUD remain available when AI-mode is unavailable.

## Approved feature boundary

Provide suburb information, local crime and safety data, and liveability metrics that help users
assess a location and make informed property-research decisions using approved Australian Bureau of
Statistics, NSW Government and other relevant public datasets.

- Frontend: suburb search/filter/sort; saved and favourite suburb CRUD; summary cards and
  visualisations; and filters for liveability indicators, amenities, local government area and
  location.
- Backend/API: suburb and user-data CRUD; location validation; approved government-data ingestion;
  query, filter, sort, aggregate and pagination; liveability/amenity/location projections;
  authenticated user-specific saved-suburb endpoints; and structured data for cards,
  visualisations and maps.
- Database: `suburb_info`, `suburb_indicators`, `suburb_amenity`, `suburb_overview` and
  `user_suburbs`, each with at least ten deterministic records.

The approved allocation and complete minimum boundary are maintained in the
[approved feature scope](../docs/architecture/registered-feature-scope.md). This README records
ownership and implementation scope. The checked-in source data is explicitly a deterministic, partial
demonstration fixture; it is not represented as current official crime or liveability evidence.

## Feature layout

- `frontend/`: responsive product UI using the shared design-system and mapping assets at image
  build time; charts always include a data-table alternative.
- `backend/`: public `/api/suburb-analytics/v1` WSGI API, pagination and validation, neutral
  comparison projection, property map-context integration, AI-mode client and allowlisted tools.
- `database/`: the only process that opens the feature-owned SQLite file; migrations, five assessed
  tables, ten-plus deterministic records per table and internal CRUD endpoints.
- `tool-catalog.yaml`: read-only AI tools for suburb snapshots, crime comparison and methodology.
- `tests/`: persistence, version-conflict, responsible-comparison, AI-degradation and frontend
  contract checks.

## Local development

The feature deliberately uses Python's standard library so it does not require a shared lockfile
change. Start the database and backend in separate terminals from the repository root:

```powershell
$env:PYTHONPATH='student-3/database/src'; $env:SUBURB_DB_PATH='student-3/.local/suburbs.sqlite3'; python -m propertyscope_suburb_store.app
$env:PYTHONPATH='student-3/backend/src'; $env:SUBURB_STORE_URL='http://127.0.0.1:5302'; python -m propertyscope_suburb_analytics.app
$env:PORT='5300'; python student-3/frontend/dev_server.py
```

Then open `http://127.0.0.1:5300/`.

The Dockerfile exposes independent `database`, `backend` and `frontend` targets. The feature manifest
is ready for future deployment registration. Root Compose, deployment selection and shared proxy
routing are intentionally unchanged; the approved home-page button points at the local frontend on
port 5300.

## Current data and platform assumptions

- The checked-in dataset is a partial deterministic demonstration fixture, not live official data.
- Authentication remains a shared-platform decision, so local saved comparisons operate as a
  single-user demo rather than inventing a feature-specific identity scheme.
- Nearby-place distances are straight-line distances. School proximity never implies catchment or
  enrolment eligibility.

## Responsible analytics constraints

- Count and rate requests cannot be mixed within a comparison.
- Recorded zero is labelled explicitly; missing evidence remains null and is never plotted as zero.
- The UI and AI objective prohibit causal claims, prediction, and safe/unsafe or good/bad rankings.
- Nearby schools are not presented as catchment or eligibility evidence.
