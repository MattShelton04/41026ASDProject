# PropertyScope redesign validation report

## 1. What this report proves

This report separates three questions that are easy to blur together:

1. **Was the existing repository foundation inspected and did its dependency-light checks pass?**
2. **Is the redesign pack internally complete and does the prototype render without browser errors?**
3. **Was a live Docker/Flask/PostgreSQL application proven end-to-end in this environment?**

The first two are supported by executed checks below. The third is **not** claimed: the isolated
execution environment has no Docker executable, cannot download the repository's pinned Python
3.12 toolchain, and does not have the workspace's Flask/Hypothesis dependencies installed.

## 2. Validation environment

| Tool/capability | Observed state |
|---|---|
| Host Python | 3.13.5 |
| Repository Python contract | 3.12 (`.python-version`; `>=3.12,<3.13` in `pyproject.toml`) |
| Node.js | 22.16.0 |
| Git | 2.47.3 |
| `uv` | 0.10.0 |
| Chromium | Available at `/usr/bin/chromium` |
| Playwright | Available in the execution environment |
| Docker | Not installed |
| Network access for `uv` toolchain download | Unavailable |
| Flask in host Python | Not installed |
| Hypothesis in host Python | Not installed |

## 3. Existing repository checks that passed

Commands were executed from the unmodified extracted repository.

| Check | Command | Result |
|---|---|---|
| Architecture boundaries | `python scripts/validate_architecture.py` | **Pass** — workspace dependency, import, credential and volume boundaries validated |
| Generated shared contracts | `PYTHONPATH=shared/contracts/python python scripts/generate_contracts.py --check` | **Pass** — exit code 0; generated contracts match their source |
| Feature 1 browser-core tests | `node --test student-1/tests/frontend/core.test.mjs` | **Pass — 21/21** |
| Shared AI operations polling tests | `node --test shared/frontend/operations/ai-mode/polling.test.mjs` | **Pass — 8/8** |
| Shared contracts and agent-core tests available without Hypothesis | `PYTHONPATH=shared/contracts/python:shared/testkit/python:ai-services/agent-core/src python -m pytest shared/contracts/tests ai-services/agent-core/tests --ignore=ai-services/agent-core/tests/test_state_machine.py -q` | **Pass — 72 tests** |
| Repository script tests | `PYTHONPATH=shared/contracts/python:shared/testkit/python:ai-services/agent-core/src python -m pytest scripts/tests -q` | **Pass — 17 tests** |

The agent-core state-machine test file was excluded from that local run only because Hypothesis is
not installed in the host interpreter. Its exclusion is a validation limitation, not a test result.

## 4. Redesign-pack checks that passed

### 4.1 Static integrity

Run:

```bash
python scripts/validate_redesign.py
```

The validator checks:

- valid top-level HTML structure and required application/landmark IDs;
- JavaScript syntax for all prototype modules and the shared-shell script;
- a manifest containing 38 unique routes;
- all 38 desktop captures, 9 mobile captures and 5 full-page captures;
- absence of recorded browser console/page errors during prototype capture;
- presence of every route in the single-file offline prototype;
- all local Markdown links in the pack; and
- required overlay, design-system, prototype, script and storyboard deliverables; and
- syntax/shape of the shared-shell Compose service definition supplied by the redesign pack.

**Result: pass.** The exact output is retained at `scripts/validation-output.txt`.

### 4.2 Prototype browser capture

Run:

```bash
python scripts/capture_screenshots.py
```

**Result: 38 desktop, 9 mobile and 5 full-page screenshots captured.** Chromium reported no
console errors or uncaught page errors. The capture manifest records the route, document title,
primary heading and screenshot path for every desktop view.

This is a static product prototype backed by showcase data. The result proves that its routes and
rendering work; it does not imply that every screen is connected to the live Feature 1 API.

### 4.3 Shared-shell preview capture

Run:

```bash
python scripts/capture_shared_shell.py
```

**Result: pass.** Clean full-page desktop and mobile previews were generated from the repository-ready
shared shell with local CSS/JavaScript inlined, animations disabled and the scroll position reset.
No browser console or page errors were recorded.

### 4.4 Shared-shell browser smoke test

Run:

```bash
python scripts/validate_shared_shell.py
```

**Result: pass.** The browser test verified one `main` landmark, five feature cards, planned labels
for Features 2–5, runtime URL overrides, the planned-capability interaction and zero browser errors.
The structured result is retained at `scripts/shared-shell-browser-validation.json`.

### 4.5 Visual review

The desktop and mobile contact sheets, five long-form captures, five storyboards and shared-shell
previews were inspected after capture. This caught composition and responsive issues that simple
DOM assertions would not expose. There is no pixel-diff baseline yet, so this is a manual review,
not an automated visual-regression suite.

## 5. Safe-application checks that passed

The application script was tested against a disposable copy of the supplied repository.

```bash
python scripts/apply_redesign.py /tmp/propertyscope-copy --mode all --dry-run
python scripts/apply_redesign.py /tmp/propertyscope-copy --mode all
python scripts/apply_redesign.py /tmp/propertyscope-copy --restore <printed-backup-path>
```

The current `all` overlay plan contains **39 additions and 3 replacements**. The test established
that the script:

- recognises the expected repository shape;
- produces an exact dry-run plan;
- backs up every replaced file;
- hashes copied files after application;
- adds only overlay-owned paths;
- does not replace Feature 1 backend, database or runner code;
- removes newly added files and prunes overlay-created empty directories during restore;
- restores replaced files byte-for-byte;
- refuses to overwrite a file edited after application unless the reviewer explicitly supplies
  `--force`; and
- retains the backup manifest as audit evidence.

The final apply/restore, conflict-protection and force-restore outputs are kept in `scripts/`. A
separate Git-compatible patch is also validated with `git apply --check` before delivery.

## 6. Prebuilt redesigned repository check

A clean copy of the supplied repository was created, the complete overlay was applied, the
temporary backup directory was removed, and the following checks were rerun against that modified
copy:

| Check | Result |
|---|---|
| Architecture validator | **Pass** |
| Generated-contract check | **Pass** |
| Shared-shell JavaScript syntax | **Pass** |
| Feature 1 browser-core tests | **Pass — 21/21** |
| Shared AI operations polling tests | **Pass — 8/8** |
| Available shared-contract/agent-core tests | **Pass — 72** |
| Repository script tests | **Pass — 17** |
| Shared-shell Compose YAML and referenced container files | **Pass — parsed and present** |

This confirms that the overlay did not invalidate the dependency-light checks available in the
environment. It does not replace the live Docker/Flask verification described below.

## 7. Checks that could not be completed here

### 6.1 Repository-wide `uv` check

```bash
uv run scripts/check.py
```

`uv` attempted to obtain the repository's pinned CPython 3.12.12 build. The environment cannot
resolve external hosts, so the download failed after three retries. This is an environment failure;
it is not evidence that the repository check itself passes or fails.

### 6.2 Full Feature 1 Python suite

A direct host-interpreter invocation of `pytest student-1/tests` did not collect because the
workspace packages were not installed on the interpreter path and Flask is unavailable. Ordinarily
`uv` resolves the workspace packages and dependencies, but the toolchain download above could not
complete. The JavaScript portion and dependency-light Python subsets were still run as documented.

### 6.3 Docker Compose and live integration

Docker is not installed, so the following were not proven in this environment:

- Compose configuration merge/build execution, including the shared-shell service;
- Flask service startup and health endpoints;
- PostgreSQL/PostGIS migrations and persistence;
- frontend-to-backend-to-database calls;
- OpenAI/model integration;
- MCP, RAG or multi-agent local profiles; and
- cloud deployment.

## 8. Required verification on a normal development machine

Before merging the shared-shell PR, run from the repository root:

```bash
uv sync --locked
uv run scripts/check.py
node --test student-1/tests/frontend/core.test.mjs
node --test shared/frontend/operations/ai-mode/polling.test.mjs
python scripts/validate_architecture.py

docker compose config
docker compose up --build
```

Then verify the shared home page, Feature 1 property and operations routes, AI-mode operations,
CRUD flows, an accepted-release path, a failed-run/recovery path and durable evidence after a
container restart. Capture this as release evidence rather than relying on screenshots of static
prototype data.

## 9. Validation conclusion

The evidence supports a selective frontend/shared-platform redesign: the retained architecture and
available tests are credible; the new prototype, shell, design system, screenshots, documentation
and application tooling pass their local integrity checks. It does **not** support claiming a fully
executed end-to-end application or cloud deployment from this environment. Those remain explicit
team verification tasks.
