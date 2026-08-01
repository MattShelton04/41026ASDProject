# Feature onboarding checklist

Use this checklist only after the tutor has approved the project topic and the feature
has an assigned student owner. It defines integration obligations without prescribing
feature entities, business rules, schemas, or user experience.

## Before implementation

- Record the owner, feature name, scope, functional requirements, non-functional
  requirements, risks, and explicit out-of-scope behavior.
- Confirm the database choice and the team's interpretation of the database-service
  requirement with the tutor.
- Identify Create, Read, Update, and Delete user flows and the tables that require at
  least ten deterministic seed records.
- Identify one bounded AI-assisted capability whose value and success criteria can be
  demonstrated from the feature frontend and backend.
- Read the root `AGENTS.md`, `CONTRIBUTING.md`, and shared-platform architecture before
  changing a shared contract or service boundary.

## Ownership and runtime boundaries

- Keep frontend, backend/API, database service, tests, and container files inside the
  assigned `student-N/` directory.
- Only the feature's database service may open its SQLite file. The backend reaches it
  over the feature's internal API.
- The feature backend starts and reads AI-mode runs over HTTP. It must not import
  `agent_core` or open AI-mode's workflow database.
- AI-mode calls only startup-allowlisted, feature-owned tool endpoints. Tool URLs,
  methods, policy, and schemas never come from model output.
- Do not import another student's feature code. Coordinate any genuinely shared
  contract change with affected owners.

## Required integration artifacts

- A strict feature manifest with a unique owner/key and safe frontend, backend, and
  health routes.
- A versioned `tool-catalog.yaml` for every model-callable endpoint. The canonical
  quality gate automatically discovers this filename under student/example slices.
- Application factories and injected clients/repositories at Flask and persistence
  boundaries.
- Health endpoints that distinguish process liveness from dependency readiness.
- A Dockerfile and root Compose services with private database networking, health
  checks, explicit configuration, and persistent data ownership.
- A functional `student-N.yml` workflow covering the owned slice and its shared
  contract compatibility.
- One accessible link from the shared home page and use of the agreed shared theme.

## HTTP and tool conventions

- Accept or propagate `X-Request-ID`; propagate `X-Agent-Run-ID`, `traceparent`, and
  `Idempotency-Key` where their semantics apply.
- Return the shared Problem Details payload with `application/problem+json` for HTTP
  request failures. Do not expose exception text, database paths, credentials, or
  upstream response bodies.
- Treat expected negative domain evidence as a schema-valid successful tool response,
  for example an empty `items` array or `found: false`. Reserve tool/HTTP failures for
  malformed, unauthorized, conflicting, unavailable, or contract-breaking operations.
- Give every write tool an atomic idempotency implementation. The business write and
  idempotency record must commit together, and an operation-status endpoint should
  support reconciliation after an ambiguous transport failure.
- Classify side effects accurately. Destructive/external operations require review;
  do not downgrade a classification to avoid the review flow.
- Bound request/response sizes and timeouts. A registered timeout is also capped by the
  AI-mode run's remaining deadline.

## Minimum deterministic tests

- Domain/service tests for CRUD rules, validation, uniqueness, and all seed invariants.
- Database migration tests from every released schema plus idempotent seed tests proving
  at least ten rows per required table.
- Backend/database contract tests proving that only the database service opens SQLite.
- Tool tests that validate successful outputs against the checked-in catalogue schemas.
- Expected-negative, malformed-input, dependency-unavailable, timeout, conflict, and
  oversized-response cases using safe Problem Details.
- Mutation replay and concurrent duplicate tests proving one durable business effect.
- AI-mode component tests with `ScriptedLLMProvider` for success, invalid planning,
  tool failure, cancellation, review, limits, and exact invocation counts.
- Frontend tests for CRUD, AI submission/polling, loading/error/review states,
  accessibility, and navigation from the shared home page.
- A Compose smoke test covering frontend → backend → database and backend → AI-mode →
  feature tool → backend → database over real HTTP without requiring a real model.

Keep real Ollama evaluation separate from deterministic CI. Record the model profile,
concrete tag/digest, prompt set, inputs, safe outputs, timings, and known failures as
release evidence.

## Integration sequence

1. Merge typed contracts and deterministic feature tests.
2. Integrate the database service and backend over private HTTP.
3. Register read-only AI tools and prove a scripted Plan → Act → Observe → Adapt run.
4. Add idempotent write tools and review/reconciliation behavior where required.
5. Integrate frontend navigation and the shared theme.
6. Add Compose services and the student workflow.
7. Run the root quality gate, Compose validation, deterministic full-stack smoke, and
   an explicitly marked real-model evaluation.

Do not claim feature completion until the integrated application, workflow execution,
test evidence, screenshots, and known limitations are captured for the release report.
