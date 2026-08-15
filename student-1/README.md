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
records. It never contacts an upstream publisher. The opt-in `--full-data` stack connects the
official NSW schools CSV, BOCSAR archive and Geoscape G-NAF bulk archive. All three use the same
durable run, content-addressed artifact, serial loader, candidate generation, quality and human
publication path as the showcase profile. Resource limits remain enforced in full-data mode.

The PSI yearly archive parser is implemented and verified against a real 2025 publisher archive,
but the publisher currently rejects requests from the Docker network with HTTP 403. PSI therefore
remains visibly catalogued/host-verified rather than being offered as a connected live option.
Fixture runs never silently stand in for a requested live run.

## Run it locally

Start Docker Desktop, then use the repository workflow from the project root:

```text
uv sync --locked --all-packages --all-groups
uv run scripts/dev.py up
```

Open <http://localhost:5200>. The normal operator path is:

1. Open **Jobs**, choose a registered job and select **Run now** or **Backfill**.
2. Select deterministic showcase/test data, preview the bounded plan, then launch it.
3. Follow durable task progress from **Runs**; failed work exposes retry/reprocess controls and an
   interrupted lease exposes resume.
4. Open the generated candidate under **Releases**. Inspect quality evidence and preview its
   actual rows before accepting or rejecting it.
5. Accepted G-NAF releases become searchable under **Properties**. Candidate rows are deliberately
   invisible until publication.
6. Open **AI diagnosis** to start or revisit persistent shared AI-mode investigations. Leaving the
   page does not discard their history.

Run `uv run scripts/dev.py down` when finished. Named model, AI history, PostgreSQL and artifact
volumes are preserved.

## Real-source captures

Real acquisition is isolated in a separate Compose project and PostgreSQL volume:

```text
uv run scripts/dev.py up --full-data
```

| Import profile | Full-data status | Upstream behaviour |
|---|---|---|
| `schools-master` | Connected | Streams the official Data.NSW master CSV with byte/row limits. |
| `bocsar-sparse` | Connected | Streams the official postcode or suburb ZIP and emits bounded sparse observations plus explicit coverage rows. |
| `gnaf-nsw` | Connected | Discovers the latest registered PSV ZIP from Data.gov.au, or uses the optional local source cache below; preserves unit identity and transforms declared GDA94/GDA2020 coordinates to WGS84 at import. |
| `psi-sales` | Host-verified, not Docker-connected | Parses real nested annual PSI packages, but the publisher's current HTTP 403 policy blocks the container transport. |

G-NAF is about 1.7 GB. To avoid downloading it for every new full-data project, place an official
PSV archive at `.propertyscope-source-cache/gnaf.zip` and declare its CRS before startup:

```powershell
$env:PROPERTYSCOPE_GNAF_CRS = "GDA94" # or GDA2020
uv run scripts/dev.py up --full-data
```

The cache directory is Git-ignored and mounted read-only. Without a cache, the runner discovers
and downloads the latest registered archive from the official CKAN package. A run can bound its
candidate to 1–50,000 addresses from the dashboard even though the source archive itself remains
an immutable, checksummed acquisition artifact.

Every release detail page includes a release-scoped dataset preview. Preview queries use fixed
registered projections, cap pages at 100 records and never mix candidate and accepted
generations. The API's runtime-capability response drives the browser controls, so live options
appear only in the explicit full-data stack.

## Shared integration boundary

The Feature 1 frontend calls only its backend. The backend and runner call the private database
API over HTTP; neither imports the database package nor receives PostgreSQL credentials. The
serial loader is the only process besides the database API that owns those credentials. Shared
AI-mode loads Feature 1's allowlisted tool catalogue, calls its bounded HTTP tools and stores
diagnosis history in AI-mode's own database. It never reads PropertyScope PostgreSQL directly.

Formal tutor/team approval evidence for the ADR-016 PostgreSQL/PostGIS exception still needs to be
linked before final submission; the implementation and executable architecture checks do not
invent that governance evidence.

## Frontend structure

The production browser remains framework-free and calls only the Feature 1 backend. Cross-cutting
behavior is split under `frontend/core/` (API/Problem Details, routing, formatting/evidence,
forms and polling guards), reusable DOM primitives live under `frontend/components/`, and migrated
screens live under `frontend/routes/`. Overview, sources/jobs, run planning and runs/run detail are
route-owned; `app.js` remains the transition composition root for releases, evidence, discovery and
AI diagnosis until those routes move in the same behavior-preserving sequence. The independently
built frontend image copies shared design-system v0.1 assets, while the development overlay mounts
the same source files for reload.
