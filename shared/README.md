# Shared components

This directory owns team-wide integration components: domain-neutral API contracts,
test utilities, the unified home page, common presentation assets, and configuration
templates. Individual features remain in their assigned `student-N/` directories and
integrate through the shared contracts and independently running services.

Production services may depend on `shared-contracts`. `shared-testkit` is for test code
only. Neither package may contain a student's feature entities or business rules.
