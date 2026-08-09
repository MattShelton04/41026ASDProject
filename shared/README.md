# Shared components

This directory owns team-wide integration components: domain-neutral API contracts,
test utilities, the implemented AI-mode operations assets, the location reserved for the
future unified product entry point, common presentation assets, and configuration templates.
The unified product home page is not implemented yet. Individual features remain in their
assigned `student-N/` directories and integrate through shared contracts and independently
running services.

Production services may depend on `shared-contracts`. `shared-testkit` is for test code
only. Neither package may contain a student's feature entities or business rules.
