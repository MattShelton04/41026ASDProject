# Feature 1 marking evidence

> Historical evidence note: this file records the canonical-import and candidate runs observed on
> 15 August 2026. It predates the registered `release_export` consumer contracts and is not, by
> itself, proof of artifact binding, consumer receipt, or property activation for those products.
> Current implementation and test claims belong in `DATA_PRODUCT_CONSUMER_GUIDE.md`.

This record is evidence from a fresh full-data deployment on 15 August 2026. The PostgreSQL and
artifact volumes for the isolated `propertyscope-full-data` Compose project were empty
before the runs below. The ordinary development volumes, Ollama model volume and read-only source
cache were not reset.

## Official-source results

Every row below is backed by a completed durable ingestion run, a content-addressed canonical
artifact, two passing blocking quality rules and a candidate dataset release. Candidate status is
intentional: the system does not publish new product data without human review.

| Acquisition profile | Observed result and example | Effective operator bounds | Evidence |
| --- | --- | --- | --- |
| NSW government schools | 2,210 of 2,210 source rows accepted, zero rejected. Example: school `1001`, Abbotsford Public School, open primary school, Canada Bay, point `151.131206,-33.852728`. | One registered CSV; 25 MB; 5,000 rows; 300 seconds. The current 1,277,226-byte source fits and the run captures the complete file. | Run `7b29bd18-f37d-4395-9acc-8ccbdf4a1c29`; release `21adaaec-a39d-499e-b381-be9883e807fc`; SHA-256 `90d31de45fd8ba586d1e5d35d8776657b774d5fc677e89fcc033bc307a727375`; 4.85 seconds. |
| BOCSAR postcode crime | 6,827 canonical rows accepted, zero rejected: 6,641 non-zero observations and 186 explicit coverage rows. Example: postcode `2000`, Abduction and kidnapping, February 2021, count 1; the source declares 60 observed months from January 2021 to December 2025 and blanks mean observed zero. | Registered postcode or suburb ZIP; 50 MB; 100,000 parsed wide rows; 50,000 canonical rows per run; 900 seconds. Evidence scope was postcodes `2000`, `2007`, `2010`, January 2021–December 2026. | Run `d8e8593a-4ece-485a-8532-68fe9eb13b68`; release `adda5962-5869-4288-b7d4-49c81bdca35f`; SHA-256 `ed95068d5953fc14a169641b702ad1d9ba9eafc400a03eb15d2480d8e863eb62`; 4.46 seconds. |
| NSW Valuer General PSI sales | **6,667,588 unique sales accepted** from 7,079,728 parsed rows across every official annual archive (1990–2025) and all 32 current-year weekly archives through 10 August 2026. The 412,140 retransmissions (5.82%) were deduplicated and zero rows were rejected. The complete 2025 annual partition alone contains 230,480 rows; weekly 10 August contains 2,964, including key `001:2962123:1`. | Complete mode resolves annual partitions 1990–previous year plus every Monday archive in the current year. Explicit annual or weekly jobs remain available. Canonical NDJSON and database COPY stream without a truncation setting; 750 MB per-archive expansion guards, a 20 GB artifact capacity and 100 million-row capacity abort corrupt/unsafe work atomically. Stable natural keys collapse annual/weekly retransmissions, and legacy row hashes preserve pre/current-format identity. | Complete run `c4bdc07b-abbd-4fc5-baba-3ad2f643044a`; candidate release `005622b4-104c-4555-8226-497cddf91430`; two passing blocking checks; 19m14s. Its 2,893,661,012-byte canonical artifact has SHA-256 `6954720f21055df0bdd0e55e47a27a4c9d3491df1079b5bfb26f96b3dae0d748`. Cached reprocess `e0edd96f-afa8-4138-a222-c4f152a60122` skipped acquisition and reproduced exactly 7,079,728 staged / 6,667,588 accepted in candidate `f0728fdd-8fa7-403a-98e4-de53179b40fb`. The 68 ZIP-verified source archives total 405,050,795 compressed bytes. |
| Geoscape G-NAF NSW addresses | 5,000 rows accepted, zero rejected, reaching the selected UI bound. Example: PID `GANSW711351856`, 20 Heysen Street, Abbotsbury NSW 2176, current `GG` geocode, declared EPSG:4283 transformed to point `150.86966825,-33.86735306`. | UI selection 1–50,000 addresses; source job maximum 2.5 GB, 6.5 million parsed rows and 24 hours. Evidence used the official February 2026 GDA94 archive (1,700,877,251 bytes); without a cache, discovery selects the latest registered Data.gov.au PSV resource. | Run `5329239a-34e8-44ca-baf4-88c171625b03`; release `4f2361b6-abea-4b9a-a09c-425497491528`; SHA-256 `2ae01855dba886e03c0834d791c7381503023beb5afa0339a8c06cc503096469`; 4 minutes 38 seconds including archive verification and parsing. Source SHA-256 `52786da19fb2e0a9c2b13446763434fec7db107de27bc81a40b5984eaf78c426`. |
| Deterministic property fixture | Exactly 10 stable `fixture-001`…`fixture-010` records per run. This is the repeatable offline critical path, not padding for unrelated persistence tables or a substitute for an official source. | No network; 50 MB/100,000 registered safety limits; the implementation emits exactly 10 deterministic rows. | Covered by unit, component, integration and frontend tests in the canonical quality gate. |

The release-record API uses a registered projection per profile and pages at no more than 100 rows.
For BOCSAR the preview total is 6,641 observations while the release manifest count is 6,827 because
coverage rows are retained as separate canonical evidence and are not duplicated in the observation
projection.

## Acquisition reproducibility

Start the isolated official-source environment with:

```text
uv run scripts/dev.py stack up --full-data
```

For a from-scratch PSI history before startup, run `uv run scripts/dev.py data sync-psi --all`. The
host-side synchroniser validates every official ZIP and writes atomically to the read-only app cache;
this avoids the publisher's Cloudflare challenge for Linux container TLS fingerprints.

Schools and BOCSAR stream their registered HTTPS resources directly. G-NAF discovers the current
Data.gov.au CKAN resource and streams it, or verifies and uses
`.propertyscope-source-cache/gnaf.zip` when repeated 1.7 GB downloads are undesirable. PSI annual
packages belong at `.propertyscope-source-cache/psi/<year>.zip`; the startup helper detects exact
years, mounts the directory read-only, advertises only those years, and the API rejects a missing
year before creating work.

The cache requirement is an evidenced upstream limitation, not synthetic fallback. On 15 August
2026, ordinary requests from the Linux runner received a Cloudflare 403 challenge. The supported
host synchroniser acquired all 68 registered archives using validated bounded Range responses,
ZIP-tested each file and atomically installed 405,050,795 bytes into the read-only cache. Source
URLs and checksums remain in run evidence; the runner's direct registered network path is also
implemented and deterministically tested.

All downloads are allowlisted HTTPS, redirect-restricted, byte-bounded, serial and checksummed.
Parsing is deterministic. Source, network, clock and filesystem boundaries are injected or
explicit, and tests do not require the internet, Docker, Ollama or private data.

## Live UI and AI evidence

The schools evidence run was launched entirely through the browser: Jobs → NSW government schools
master snapshot → Run now → Live official Data.NSW schools CSV → Preview deterministic plan →
Launch run. The durable timeline immediately showed Discover succeeded and Acquire running, then
displayed all seven task stages, row counts, heartbeat, artifacts, quality evidence and candidate
release navigation. Release previews for all four official profiles used readable profile-specific
columns. Controls expose plain-language defaults first and keep raw JSON and manifests under
technical disclosure panels.

The original feature diagnosis screen fetched AI progress only once. A second race allowed an empty
detail `steps` array to hide already-returned events, so the UI could show “no durable events” for
minutes while the shared service was recording them. The corrected screen polls the run and its
targeted event endpoint every 0.8–1.5 seconds, updates one history item in place, stops on a terminal
state, resumes after tab visibility changes, survives transient failures and uses an ARIA live
region. Shared AI operations already polled correctly; no cross-service contract change was needed.

Fixed live diagnosis run `ea4149d0-d654-43da-8ded-e88581596e54` displayed Planning and its Plan
event immediately, then completed successfully with 10 Plan/Act/Observe/Adapt steps and three tool
calls. It took about 119 seconds: approximately 113 seconds was a cold first model response, not an
event-delivery delay. Docker had previously run Ollama on CPU and timed out at five minutes despite
an available RTX 3060 Ti; `scripts/dev.py stack up` now detects the NVIDIA runtime and applies the GPU
overlay automatically, with explicit `--cpu-only` and `--gpu` controls.

## Defects found by the evidence run

- The default job scopes contained only generic partition placeholders. Profile switching could
  therefore launch misleading requests. Migration `014_registered_job_scopes.sql` installs safe,
  meaningful source-specific defaults.
- A 30-second worker lease could expire while the 1.7 GB G-NAF archive was being checksummed after
  streaming. The full-data runner now uses a five-minute lease while still heartbeating each chunk.
  The interrupted run resumed idempotently and produced the successful G-NAF evidence above.
- Default and full-data Compose projects shared a fixed network name. Stopping one could remove the
  network beneath retained containers in the other. The full-data project now owns a distinct fixed
  network.
- The full-data startup path could not connect PSI even when an official archive was already
  available. Capability discovery, read-only cache mounting and bounded Range acquisition now form
  one fail-closed path for both cached and from-scratch partitions.
- Live PSI silently stopped at 50,000 rows, while the loader separately rejected more than 100,000
  JSON rows and the runner limited canonical artifacts to 50 MB. Complete annual/weekly acquisition
  now streams canonical NDJSON into PostgreSQL COPY, and stable keys collapse retransmissions.
- The 2008 archive legitimately contains 6,662 direct DAT members, above the original 5,000-member
  corruption guard. Source-wide ZIP and expansion checks now admit the documented archive shape.
- The official 2001 yearly archive contains legacy-layout `ARCHIVE` rows even though current weekly
  layout also begins in 2001. Per-record layout detection recovered 911 real sales previously
  collapsed by misread keys; the exact source row is retained as a regression test.
- Source-scale loader failures originally exposed only a safe public error. Internal structured
  tracebacks now identify the exact row/field while public responses remain non-sensitive, and
  transient control-plane disconnects are retried without abandoning durable database work.

## Marking alignment

The implementation directly evidences the Release 0 criteria for service integration, Docker
Compose, working CRUD, AI-mode integration, the Plan → Act → Observe → Adapt loop, prompt/tool
context, local testing and an integrated demonstration. The Feature 1 README contains the operator
workflow and architecture links; this file supplies run IDs, counts, examples, hashes, limitations
and a short repeatable showcase journey suitable for the report and video.

The remaining action is governance, not missing implementation: a reviewer must accept and publish
a candidate before another feature may treat it as current product data.
