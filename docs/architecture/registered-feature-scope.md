# PropertyScope approved team and feature scope

## Document control

| Field | Value |
|---|---|
| Status | Approved team allocation and feature-scope baseline |
| Confirmed | 29 August 2026 |
| Canvas group | 20 |
| Project | PropertyScope — NSW property research website with agentic capabilities |
| Cloud | Azure |
| Production LLM profiles | OpenAI API using GPT-5.6 Luna and GPT-5.6 Terra |
| Development compatibility | An OpenAI-compatible API may be used for local testing, including Gemini-compatible development profiles |

This document records the approved scope from the signed group registration form and the team's
confirmation of tutor approval. It is the authority for student allocation and the minimum domain
boundary of each assessed feature. Detailed product, design and architecture documents may refine
implementation mechanics, but they must not silently add a required product capability or move
business rules, persistence or assessed work between students.

Approval and allocation do not imply implementation. Feature 1 is the currently implemented
vertical slice. Features 2–5 remain planned and disabled in the product shell until each owner
delivers and integrates a complete frontend, backend/API and database microservice set.

## Team allocation

| Student | Name | Student ID | Email | Approved feature |
|---|---|---:|---|---|
| 1 | Matthew Shelton | 24763373 | matthew.n.shelton@student.uts.edu.au | Data Platform and Property Discovery |
| 2 | Burhan Naeem | 24764134 | Burhan.Naeem@wisetechglobal.com | Property Sales Explorer and Market Cases |
| 3 | James Huang | 24970865 | Zihuang.huang@student.uts.edu.au | Suburb, Crime, and Liveability Analytics |
| 4 | Michael White | 24846267 | Michael.h.white@student.uts.edu.au | Site, Planning, and Building Due Diligence |
| 5 | Derek Song | 24833978 | Derek.song@student.uts.edu.au | Buyer Journey and Agent Workspace |

## Common assessed responsibilities

Every student owns and maintains one frontend microservice, one backend/API microservice, one
database microservice, the associated tests and Docker targets, and their own CI/CD workflow.
Every feature must provide visible CRUD through its frontend and backend, populate every assessed
database table with at least ten deterministic records, interact with the approved LLM through the
shared AI-mode boundary, and demonstrate a bounded Plan → Act → Observe → Adapt workflow. Direct
CRUD and deterministic evidence views must continue to work when the model provider is unavailable.

All five slices must integrate into the shared repository, Docker Compose application, unified home
page and common visual system. Feature services communicate through versioned HTTP APIs or validated
publication artefacts. They never import another student's implementation or access another
feature's database, credentials or volume.

## Feature 1 — Data Platform and Property Discovery

**Owner:** Matthew Shelton (`student-1`)

**Purpose:** Provide PropertyScope's governed data control plane and buyer-facing property
discovery. The feature acquires and validates attributed NSW datasets, publishes immutable accepted
releases, maintains canonical property/address identity, and lets users search supported properties
while seeing source coverage, provenance, freshness and uncertainty.

**Frontend scope:** Source- and job-definition CRUD; bounded refresh/backfill launch; run monitoring,
cancellation, retry and resume; validation/provenance inspection; dataset-release review,
publication and rejection; property discovery; and AI-assisted failure diagnosis with review of any
proposed action.

**Backend/API scope:** REST APIs for source/job CRUD, orchestration and release operations, property
discovery, and bounded AI-mode workflows such as ETL failure diagnosis and dataset inspection.

**Persistence scope:** Feature 1-owned PostgreSQL/PostGIS tables supporting the source/job scheduler,
governed releases, canonical property/address data and attributed datasets. No other feature receives
Feature 1 database credentials.

## Feature 2 — Property Sales Explorer and Market Cases

**Owner:** Burhan Naeem (`student-2`)

**Purpose:** Provide an evidence-based property-sales explorer using accepted NSW Property Sales
Information releases from Feature 1. Users can inspect recorded sale history and simple deterministic
market summaries, save research cases, and request AI explanations that cite selected evidence and
state missing data and limitations. The feature does not estimate value or recommend whether to buy.

**Frontend scope:** Market-case CRUD; selection of a verified property and date range; attributed sale
records; sample count, median price and transaction-volume summaries in a table and simple chart;
editable filters, notes and status; an AI explanation action; and explicit source-release,
exclusion, insufficient-data and AI-unavailable states.

**Backend/API scope:** Market-case CRUD; Feature 1 property-reference validation; versioned
`nsw-psi-sales` release import into the Student 2 database; sale-history queries; deterministic
sample-count, median-price and period-volume calculations; date/filter validation; a bounded shared
AI-mode evidence workflow; and health/readiness endpoints.

**Persistence scope:** `sale_observation` for attributed imported sale facts and release provenance;
`market_case` for user-owned property/date scope, filters, notes, status, AI run reference,
timestamps and version.

## Feature 3 — Suburb, Crime, and Liveability Analytics

**Owner:** James Huang (`student-3`)

**Purpose:** Provide suburb information, local crime and safety data, and liveability metrics that
help users assess a location and make more informed property research decisions. Evidence is drawn
from government and relevant public datasets, including the Australian Bureau of Statistics and NSW
Government sources.

**Frontend scope:** Search, filter and sort suburbs; saved/favourite suburb CRUD; summary cards and
visualisations; and filters based on liveability indicators, public amenities, local government
area, location and other approved categories.

**Backend/API scope:** Suburb and user-data CRUD; suburb/location validation; ingestion and processing
of approved NSW and Australian Government datasets; query, filter, sort, aggregate and pagination;
liveability, amenity and location indicators; saved suburbs/favourites; input/date/filter validation;
authenticated user-specific endpoints; and structured projections for cards, visualisations and maps.

**Persistence scope:** `suburb_info`, `suburb_indicators`, `suburb_amenity`, `suburb_overview` and
`user_suburbs`, covering locality identity, indicators, crime statistics, amenities, descriptive
facts and saved user selections.

## Feature 4 — Site, Planning, and Building Due Diligence

**Owner:** Michael White (`student-4`)

**Purpose:** Provide an evidence-based site due-diligence workspace using accepted PropertyScope
planning, environmental, strata and building information. Users can review controls and constraints,
identify missing evidence, maintain checklists, and request AI-generated questions for professional
verification. The feature distinguishes confirmed observations, non-intersections, partial coverage
and unavailable coverage, and does not certify compliance, safety or legal suitability.

**Frontend scope:** Site-review CRUD; verified property selection; source-attributed zoning,
heritage, floor-space-ratio and building-height information; supported flood, bushfire and other
environmental layers; strata, building-order and tribunal observations; explicit evidence states;
editable checklists, questions, notes, disposition and status; and an AI-generated due-diligence
question pack with professional-verification guidance.

**Backend/API scope:** Site-review CRUD; Feature 1 property-reference validation without database
access; versioned evidence-release import into the Student 4 database; property-constraint and source
metadata retrieval; bounded GeoJSON layers; strata/building-order/tribunal evidence with match
method and confidence; validation of review/evidence states; a bounded Plan → Act → Observe → Adapt
question-generation workflow; and health/readiness endpoints.

**Persistence scope:** `constraint_observation` for planning/environmental evidence;
`building_observation` for strata, building-order, undertaking and tribunal evidence; and
`site_review` for user-owned checklists, verification questions, disposition, notes, status, AI run
reference, timestamps and version.

## Feature 5 — Buyer Journey and Agent Workspace

**Owner:** Derek Song (`student-5`)

**Purpose:** Provide a buyer-journey and agent workspace for organising shortlisted properties,
tracking buying stages, recording notes and tasks, and reviewing relevant research from other
PropertyScope features. Users can request AI-assisted summaries and suggested next actions based on
available evidence, with missing information and limitations made explicit.

**Frontend scope:** Buyer-case CRUD; shortlist add/remove; journey stages including Shortlisted,
Inspecting, Reviewing, Offer Considered and Closed; buyer preferences, notes and ratings; task CRUD
and completion; related sales, suburb and due-diligence information; AI-generated case summaries and
suggested next actions; and explicit AI-unavailable and missing-data states.

**Backend/API scope:** Buyer-case, shortlist, note and task CRUD; Feature 1 property-reference
validation; relevant-evidence retrieval from other PropertyScope services; stage transitions; input
and case-ownership validation; a bounded AI workflow that plans retrieval, produces a buyer-case
summary and suggested next actions, observes missing evidence and adapts when required; evidence,
limitation and AI-run references; and health/readiness endpoints.

**Persistence scope:** `buyer_case` for preferences, budget, target suburbs and state;
`case_property` for shortlisted properties and journey stages; `case_note` for case/property notes;
and `case_task` for due dates, completion state and related property/case references.

## Scope change control

The approved feature purposes above are commitments; detailed route names, schemas, UI composition,
data-source selections and release sequencing remain implementation decisions owned by the relevant
student and reviewed through normal architecture change control. Optional concepts in older planning
documents—such as valuation, automated recommendations, broad comparable selection, dossiers or
external actions—are not required unless the team and tutor explicitly approve a scope change.
