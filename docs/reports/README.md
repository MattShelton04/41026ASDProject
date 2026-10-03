# Reports

Each release report is maintained as Markdown and rendered to PDF by one shared engine,
[`scripts/report_pdf.py`](../../scripts/report_pdf.py). A thin builder per release supplies its
title, figures and rules. Builds need no network, browser, model credential or Docker, and give
byte-identical output for the same inputs and locked environment.

| Release | Source | Builder | Submitted PDF |
|---|---|---|---|
| 0 | [`release-0-technical-report.md`](release-0-technical-report.md) | `scripts/build_release0_report.py` | [`submissions/release-0/41026Group20Release0Report.pdf`](submissions/release-0/41026Group20Release0Report.pdf) (frozen) |
| 1 | [`release-1-technical-report.md`](release-1-technical-report.md) | `scripts/build_release1_report.py` | [`submissions/release-1/group-20.pdf`](submissions/release-1/group-20.pdf) (draft until submission) |

`submissions/` holds what goes to Canvas. The Release 0 PDF is exactly what was uploaded and is
never regenerated: a test pins its SHA-256, and Release 0 rebuilds write to `tmp/reports/` instead.
The Release 1 PDF is rebuilt and committed as the report fills in, so it always shows the current
draft; it becomes the submitted file after the `--final` build.

## Layout

- `diagrams/release-N/*.mmd`: Mermaid source for every figure.
- `assets/release-N/*.png`: rendered figures, bound to their sources by SHA-256 in
  `assets/release-N/manifest.json` (line endings are normalised across Windows and Unix).
- `assets/release-1/screenshots/`: application screenshots for the Release 1 report.
- `evidence/`: retained execution records linked from the reports.

## Release 1 workflow

The Release 1 brief allows **3,000 words plus diagrams**. The builder counts the assessed body and
shows each chapter against its budget in `SECTION_WORD_BUDGETS`:

```text
uv run python scripts/build_release1_report.py --status   # word budget, TODOs, pending screenshots
uv run python scripts/build_release1_report.py            # rebuild submissions/release-1/group-20.pdf
```

Counted: chapter headings, prose, lists, generated tables, fenced evidence output and substantive
appendices from the first chapter onwards. The brief grants no appendix or terminal-output
exemption. Excluded: cover, generated contents, figures and captions, TODO callouts and hidden
author notes. Moving a table or log into an appendix does not reduce the count. Release 0 retains
its historical counting policy and frozen submission.

The Markdown supports a few extras on top of the Release 0 syntax:

| Syntax | Effect |
|---|---|
| `[[TODO: Owner \| what is needed]]` | Amber "to complete" callout in drafts; listed by `--status`; blocks `--final` |
| `![Figure N caption](path.png)` for a missing file | "Image pending" placeholder in drafts; blocks `--final` |
| `<!-- ... -->` at the start of a line | Writing guidance for authors; never rendered |
| `[[TOOL_TABLE]]`, `[[TOOL_DETAIL]]` | Registered MCP tools, generated from every enabled feature's `tool-catalog.yaml` |
| `[[CORPUS_TABLE]]` | RAG knowledge sources, generated from each registered `config/rag/corpus.json` |
| `[[RETRIEVAL_SUMMARY path]]` | Summary of a committed retrieval evaluation baseline |
| `[[LOOP_OUTPUT path]]` | Terminal-style summary of a `dev.py ai validate` JSON capture |
| `[[BASELINE]]` within prose or a table | The selected `--baseline`, including the cover commit row |

Generated tables change as soon as a feature registers tools or a corpus, so nobody hand-copies them.

To fill in your part:

1. Run `--status` and find the TODOs with your name.
2. Replace each TODO line with content, keeping inside your chapter's word budget.
3. Capture screenshots with the live stack running
   (`uv run python scripts/capture_release1_screenshots.py --only feature-N`). The script lists
   every expected screenshot, its question and its owner.
4. Rebuild the PDF, look at every page you changed, and commit it with your Markdown changes.

To submit, rebuild with the submission commit. `--final` writes the same file, but refuses to run
while any TODO, pending image, unresolved baseline, incomplete evidence index or word-limit
overrun remains:

```text
uv run python scripts/build_release1_report.py --final --baseline <40-character commit SHA>
```

The SHA must resolve to a real commit. It identifies the software and retained evidence being
assessed; the later PDF commit does not need to refer to itself. Local indexed evidence must be
tracked and unchanged at that baseline (Git's line-ending normalisation is respected). Successful
CI runs may use an earlier traceable commit when the relevant
feature and workflow have not changed; the report must explain the evidence's scope.

### Submission evidence index

Include one hidden YAML block in the Markdown source. It references content already in the PDF;
it adds no rendered text. `--status` lists missing references without preventing a draft build.
Use `[[BASELINE]]` in both this block and the cover's `Commit reference` row, and give the cover
the same repository and video URLs. For example:

```yaml
<!-- RELEASE1_METADATA
schema_version: 1
baseline: '[[BASELINE]]'
repository_url: https://github.com/MattShelton04/41026ASDProject
showcase_url: https://youtu.be/0Z0Rt146lD0
sections:
  scope: '1 Project overview and Release 1 scope'
  requirements: '2 Functional requirements'
  nonfunctional: '3 Non-functional requirements'
  architecture: '4 Architecture and repository structure'
  design: '5 MCP and RAG design'
  validation: '6 Validation and results'
  integration: '7 Integration summary'
  limitations: '8 Known issues and limitations'
  contributions: '9 Contributions, repository and showcase'
  planning: '1.2 Delivery plan and risks'
evidence:
  - kind: loop-rag
    section: '6.2 Shared agentic loop'
    path: docs/release-1/evidence/validation-rag.json
    boundary: Real local services with deterministic model decisions.
  - kind: ci
    student: 1
    section: '6.5 GitHub Actions'
    workflow: student-1.yml
    url: https://github.com/MattShelton04/41026ASDProject/actions/runs/36293980721
    boundary: Retained successful run; report states the commit and checks covered.
contributions:
  - student: 1
    section: 'Student 1 Matthew Shelton'
    commits: [1e109ac]
attendance:
  1: 'Actual participation statement, or a clear statement that it is unconfirmed.'
-->
```

This example is partial. Supply these evidence kinds:

- Shared: `terminal`, `deployment`, `loop-mcp`, `loop-rag`.
- For each enabled student: `feature-mcp`, `feature-rag`, `feature-crud`, `ci`.
- One contribution entry and attendance statement per enabled student (currently 1–5).

Each evidence entry requires a populated exact heading in `section`, a factual `boundary`, and
either a root-relative repository `path` or an HTTPS `url`. Link or display it in that section:
Markdown links, screenshot images, `LOOP_OUTPUT` and `RETRIEVAL_SUMMARY` count as references.
CI URLs must identify a run of this repository and declare the matching `student-N.yml` workflow.
Loop entries must reference successful four-phase validation JSON with feature, tool, corpus,
run, request and tool-result identities; RAG output must include its corpus version and status.
Contribution commits must resolve, belong to the baseline's history and appear in that student's
nonempty log. Attendance statements must also appear in the contributions chapter; recording an
unconfirmed attendance limitation keeps the report honest and does not establish compliance.

The guard checks the evidence index's structure and traceability. Authors still need to inspect
screenshots, confirm CI results, review provider answers and verify video access, duration and
coverage. A final build does not establish the quality of those observations or guarantee marks.

## Diagrams

After changing a `.mmd` file, install Node.js with `npx` and refresh the figures and manifest:

```text
uv run python scripts/build_release1_report.py --render-diagrams
uv run python scripts/build_release0_report.py --render-diagrams
```

This invokes Mermaid CLI **11.12.0**, which may download its npm package and Chromium on first use.
Commit the Mermaid sources, PNGs and manifest together, and never edit a manifest by hand to get past
a stale-diagram error.

## Visual review

Tests cover reproducibility, navigation, figure inclusion, stale assets, the word count and the
final-build guard. They do not replace looking at the PDF. Render the pages and check for clipped
tables, tiny diagram labels, orphaned headings and caption placement:

```text
pdftoppm -scale-to 1400 -png docs/reports/submissions/release-1/group-20.pdf tmp/pdfs/report
```

## Release 0 notes

The Release 0 report covers all five feature slices, architecture, Docker Compose, AI mode and the
agentic loop, local and GitHub Actions evidence, screenshots, contribution records and known
limitations. Its repository links point to the Release 0 commit `7d5350d`; Sections 5.5 and 8.2 link
later review and execution records at separate immutable commits. ERDs are curated schema views
(Feature 1's cover migrations through `049_index_gnaf_identity_anchors.sql`), not database dumps. The
[6 September execution record](evidence/release-0-compose-2026-09-06.md) retains the simultaneous
local all-feature startup, status, HTTP checks and fixture collection.
