# ADR-016: Use PostgreSQL/PostGIS for the PropertyScope Feature 1 database service

- Status: Proposed — requires written tutor and team approval
- Date: 9 August 2026
- Owner: PropertyScope Feature 1 / shared architecture review
- Supersedes: the SQLite default described as ADR-007 for Feature 1 only, if accepted

## Context

The shared-platform baseline gives every student slice an independently owned database
service and defaults that service to SQLite. The course technology table permits SQLite
or PostgreSQL, but several Release 0 deliverables and rubric statements specifically
refer to SQLite. Any exception therefore needs explicit approval and must not erase the
other students' database ownership.

Read-only inspection of previous project work completed by Matthew Shelton found a
PostgreSQL 16/PostGIS 3.4 corpus of about 29 GB. Material volumes include approximately
9.59 million address records, 5.42 million normalised sales, and 38.16 million dense
crime-month rows. The data also contains millions of spatial or source-aligned records
whose correct loading needs bulk `COPY`, set-based normalisation, release isolation,
spatial reference transforms, geometry validation and spatial indexes. A full NSW
implementation is not credible on SQLite.

The earlier work is valuable evidence and a migration source, but is not itself the new
assessed database. Its operational history also shows failed coupled refreshes, partial
source loads, abandoned running jobs and schema changes outside the canonical migration
history. PropertyScope needs a rebuildable, source-aware boundary rather than mounting
or adopting that database unchanged.

## Decision

Subject to written tutor approval, PropertyScope Feature 1 uses one feature-owned
PostgreSQL 16 database with PostGIS. Features 2–5 keep their independently owned SQLite
database services. AI-mode keeps its existing independent workflow store.

- Only the Feature 1 database-service trust boundary—its API plus one serial loader
  process—receives PostgreSQL credentials and opens the database.
- The Feature 1 backend, acquisition runner, other feature services, AI-mode and MCP/RAG
  services do not receive credentials or issue SQL.
- The runner writes content-addressed, checksum-verified artifacts and invokes only
  registered internal bulk-import commands. The API durably enqueues and returns `202`;
  the serial database loader performs `COPY`, source-specific normalisation, quality
  queries and short atomic generation activation outside normal HTTP request timeouts.
- Public and cross-feature access stays behind the Feature 1 backend. No general SQL,
  table proxy, shared schema or shared volume is exposed.
- Features 2–4 receive bounded, versioned releases through their backend contracts and
  import them into their own databases after domain-owner validation. Feature 5 composes
  evidence through feature APIs.
- Feature 1 owns source/job/run/release CRUD, provenance, stable property/addressable-
  location identity, property discovery, accepted source-aligned data and serving
  projections. It does not own consumer-domain saved work or analytical meaning.
- CI, ordinary Compose and the showcase use the same PostgreSQL schema/code path with a
  small deterministic fixture/profile. The persistent full-data profile is explicit and
  opt-in; no second SQLite implementation is maintained after approval.
- Migrations must rebuild from empty and produce a checked schema fingerprint. Manual DDL
  and direct reuse of the earlier database are prohibited.

The shared architecture diagram, Compose topology, architecture validator and tests must
be updated together when this ADR is accepted. Until then, this remains a proposal and no
boundary change is authorised.

## Data and release implications

The initial implementation is full-refresh-first. A run discovers a complete bounded
source snapshot, acquires immutable artifacts, loads an isolated candidate generation,
runs source-aware quality gates and atomically advances an accepted-generation pointer.
It never truncates the live accepted generation. `reprocess_cached` and failed-task
repair reuse the same run model; PSI year/week replacement is an explicit partition
scope, not a generic incremental-cursor claim.

The Release 0 implementation target is the common ingestion framework plus deterministic
fixtures and four real source families: NSW government-school master, sparse BOCSAR crime
with an explicit coverage universe, NSW G-NAF, and a bounded PSI partition using the same
path as the opt-in historical backfill. Other researched adapters remain staged follow-on
work until their coverage, licensing and normalisation are proven.

## Consequences

Feature 1 can truthfully support statewide address/source operations, spatial data and
robust bulk loads. The browser can expose genuine run planning, task timelines, quality
evidence, candidate-versus-accepted comparison, recovery and reviewed publication. The
same data boundary also supports later Azure PostgreSQL deployment more naturally than a
29 GB SQLite file.

The default Compose gains a PostgreSQL/PostGIS container and Feature 1 becomes the most
infrastructure-heavy slice. The team must cap the showcase profile, preserve five clear
feature ownership boundaries and prevent feature consumers from drifting into live
warehouse queries. Database-specific component tests and migration checks become part of
`student-1.yml`.

This decision does not weaken the rubric requirement that every persistent Release 0
table be populated for demonstration. Small deterministic CI/showcase seeds provide at
least ten rows per persistent R0 table; full-data tables have their source-scale counts.

## Fallback if approval is denied

Feature 1 implements the same public contracts over bounded SQLite extracts and removes
full-state ingestion/search from Release 0 claims. The product can still demonstrate
source/job CRUD, a fixture run, release quality, property discovery and downstream
publication, but cannot honestly migrate or operate the verified statewide corpus.

The fallback is a scope reduction, not a dual persistence strategy. The team records the
tutor decision before implementation and uses one database path thereafter.

## Alternatives considered

- **Five SQLite stores including Feature 1:** closest to literal rubric wording, but not
  suitable for the verified statewide volumes or PostGIS operations. Retained only as the
  bounded fallback.
- **One PostgreSQL database for all five features:** simpler for joins, but destroys clear
  individual database ownership and creates schema/SQL coupling. Rejected.
- **A sixth shared PostgreSQL warehouse plus five stores:** preserves nominal stores but
  creates duplicate truth, more containers and a hidden shared runtime dependency.
  Rejected.
- **Keep the earlier warehouse as optional external tooling:** does not produce a
  reproducible assessed Feature 1 implementation and makes data operations unavailable to
  the browser. Rejected as the target, though it remains a migration/evidence source.
- **Send bulk rows through ordinary JSON CRUD endpoints:** technically pure HTTP but
  impractical for millions of rows. Rejected in favour of fixed, registered database-
  service import operations over verified artifacts.

## Approval and validation record

Before changing the shared baseline, record:

1. written tutor approval for one Feature 1-owned PostgreSQL/PostGIS database service;
2. team approval of the database, publication and property-identity boundaries;
3. updated shared-platform and integrated Compose diagrams;
4. architecture-validator tests proving only the Feature 1 database service receives
   PostgreSQL access; and
5. migrations-from-empty, fixture, backup/restore and bounded full-refresh component-test
   evidence.
