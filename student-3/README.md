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

The completed feature must support CRUD, contain at least ten records per table,
integrate with the unified home page and shared styling, interact with the
approved LLM, and remain part of the integrated group application.

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
ownership and planned scope only; no Feature 3 implementation is claimed yet.
