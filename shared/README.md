# Shared components

This directory owns team-wide integration components: domain-neutral API contracts,
test utilities, the implemented AI-mode operations assets, the unified product entry point,
common presentation assets, and configuration templates. The shared frontend provides the
product home plus live system-status, bounded evidence-reference and capability-roadmap views;
it also provides a domain-neutral browser mapping provider but does not own feature layers, data
or business interpretation. Individual features remain in their assigned `student-N/` directories
and integrate through shared contracts and independently running services.

Production services may depend on `shared-contracts`. `shared-testkit` is for test code
only. Neither package may contain a student's feature entities or business rules.
