# Reports

This directory contains the maintained Release 0 report source and submission PDF.

- [`release-0-technical-report.md`](release-0-technical-report.md) is the evidence-backed source.
- [`group20.pdf`](group20.pdf) is the Canvas submission artefact.
- `diagrams/release-0/*.mmd` contains the reviewable Mermaid source for every report diagram.
- `assets/release-0/*.png` contains the rendered Mermaid figures embedded in the PDF.
- `assets/release-0/manifest.json` binds every figure to its Mermaid source and rendered PNG by SHA-256
  (source line endings are normalised for Windows and Unix checkouts).
- `scripts/build_release0_report.py` checks those hashes and regenerates the PDF.

The report covers all five enabled feature slices, architecture, Docker Compose, AI mode and the
agentic loop, local and GitHub Actions evidence, screenshots, contribution records and known
limitations. Regenerate and visually inspect the PDF after changing its source.

Build from a clean checkout using the locked development dependencies (ReportLab, Pillow and pypdf):

```text
uv sync --locked --all-packages --all-groups
uv run python scripts/build_release0_report.py
```

Ordinary PDF builds require no network, browser, model credential or Docker. They use the checked-in
figures, retain clickable evidence links and PDF bookmarks, and produce byte-identical output for
the same inputs and locked environment. Repository links retain URL fragments and point to the
software evidence baseline; rebuilding the report does not refresh historical execution evidence.

After changing a diagram, install Node.js with `npx` and refresh all figures and their manifest:

```text
uv run python scripts/build_release0_report.py --render-diagrams
```

This explicitly invokes Mermaid CLI **11.12.0**, which may download its npm package and Chromium on
first use. Commit the changed Mermaid sources, PNGs, manifest, Markdown and regenerated `group20.pdf`
together. Do not update the manifest by hand to bypass a stale-diagram error.

The report includes a runtime architecture and selected-key ERD for every student. ERDs label query
associations separately from actual foreign keys; the linked owned schemas remain authoritative for
all columns and constraints. OpenAI is the registered provider; the team's complimentary-token
allowance is recorded as an account-specific rationale, separately from historical Gemini tests.

Before handoff, run the canonical gate and render the PDF for visual review:

```text
uv run python scripts/check.py
pdftoppm -scale-to 1400 -png docs/reports/group20.pdf tmp/pdfs/report
```

Create `tmp/pdfs` first and install Poppler if it is not available. Inspect every page for clipped
tables, tiny diagram labels, orphaned text, caption placement and contents destinations. Generator
tests cover reproducibility, navigation, figure inclusion and stale assets; they do not replace this
visual review. The report's evidence limitations are retained in Section 9, including missing
Feature 3-5 screenshots and the absence of a final simultaneous local all-feature startup record.
