# Feature 1 marking evidence

This record is evidence from a fresh full-data deployment on 15 August 2026. The PostgreSQL and
artifact volumes for the isolated `41026-asd-propertyscope-full-data` Compose project were empty
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
| NSW Valuer General PSI sales | 50,000 rows accepted, zero rejected, reaching the configured canonical ceiling. Example: business key `258:1382319:36`, dealing `AU493308`, contract date `1956-03-12`, settlement date `1993-02-26`, price $4,686 and area 695.6 m². It remains unmatched rather than inventing an address link. | 1–40 explicit annual partitions from 1990 through next year; maximum 50 MB per annual ZIP in the runner; effective 50,000 canonical rows total per run. The registered job also bounds source work at 10 objects, 5 GB and 24 hours. | Run `83892af0-acdb-42b0-9d53-46ca2fa741ae`; release `2c0c64fe-553e-445a-ae54-84fdba273630`; SHA-256 `dfdc624abc174c095160d9a7b66c4ff302e6c15fb38f8a0b44077b81d69df7e6`; 8.15 seconds. The official 2025 ZIP was 15,425,614 bytes with source SHA-256 `6368968e1a9d509b8224d747fb6c76d852d4da9a7ac8afd2bca0bbb8a4aaaa87`. |
| Geoscape G-NAF NSW addresses | 5,000 rows accepted, zero rejected, reaching the selected UI bound. Example: PID `GANSW711351856`, 20 Heysen Street, Abbotsbury NSW 2176, current `GG` geocode, declared EPSG:4283 transformed to point `150.86966825,-33.86735306`. | UI selection 1–50,000 addresses; source job maximum 2.5 GB, 6.5 million parsed rows and 24 hours. Evidence used the official February 2026 GDA94 archive (1,700,877,251 bytes); without a cache, discovery selects the latest registered Data.gov.au PSV resource. | Run `5329239a-34e8-44ca-baf4-88c171625b03`; release `4f2361b6-abea-4b9a-a09c-425497491528`; SHA-256 `2ae01855dba886e03c0834d791c7381503023beb5afa0339a8c06cc503096469`; 4 minutes 38 seconds including archive verification and parsing. Source SHA-256 `52786da19fb2e0a9c2b13446763434fec7db107de27bc81a40b5984eaf78c426`. |
| Deterministic property fixture | Exactly 10 stable `fixture-001`…`fixture-010` records per run. This is the offline critical path and minimum-ten-record marking fixture, not a substitute for any requested official source. | No network; 50 MB/100,000 registered safety limits; the implementation emits exactly 10 deterministic rows. | Covered by unit, component, integration and frontend tests in the canonical quality gate. |

The release-record API uses a registered projection per profile and pages at no more than 100 rows.
For BOCSAR the preview total is 6,641 observations while the release manifest count is 6,827 because
coverage rows are retained as separate canonical evidence and are not duplicated in the observation
projection.

## Acquisition reproducibility

Start the isolated official-source environment with:

```text
uv run scripts/dev.py up --full-data
```

Schools and BOCSAR stream their registered HTTPS resources directly. G-NAF discovers the current
Data.gov.au CKAN resource and streams it, or verifies and uses
`.propertyscope-source-cache/gnaf.zip` when repeated 1.7 GB downloads are undesirable. PSI annual
packages belong at `.propertyscope-source-cache/psi/<year>.zip`; the startup helper detects exact
years, mounts the directory read-only, advertises only those years, and the API rejects a missing
year before creating work.

The cache requirement is an evidenced upstream limitation, not synthetic fallback. On 15 August
2026, both host and Docker requests to the registered Valuer General yearly URL returned HTTP 403
from Cloudflare, and the replacement portal returned HTTP 500. The official 2025 archive retained
from the earlier prototype was therefore checksum-verified and used unchanged. Source URLs remain
in the run evidence. If the publisher transport becomes available again, the runner's registered
network path remains implemented and tested.

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
an available RTX 3060 Ti; `scripts/dev.py up` now detects the NVIDIA runtime and applies the GPU
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
  available. Capability discovery, plan validation, read-only cache mounting and exact-year UI
  guidance now form one fail-closed path.

## Marking alignment

The implementation directly evidences the Release 0 criteria for service integration, Docker
Compose, working CRUD, AI-mode integration, the Plan → Act → Observe → Adapt loop, prompt/tool
context, local testing and an integrated demonstration. The Feature 1 README contains the operator
workflow and architecture links; this file supplies run IDs, counts, examples, hashes, limitations
and a short repeatable showcase journey suitable for the report and video.

The remaining action is governance, not missing implementation: a reviewer must accept and publish
a candidate before another feature may treat it as current product data. New PSI downloads also
remain dependent on the NSW publisher restoring its official endpoint or supplying another annual
archive.
