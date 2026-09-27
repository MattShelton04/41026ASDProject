# Reports

This directory contains the maintained Release 0 report source and submission PDF.

- [`release-0-technical-report.md`](release-0-technical-report.md) is the evidence-backed source.
- [`submissions/release-0/41026Group20Release0Report.pdf`](submissions/release-0/41026Group20Release0Report.pdf)
  is the PDF submitted on Canvas. It is frozen: a test pins its SHA-256 and the builder refuses to
  overwrite it.
- `diagrams/release-0/*.mmd` contains the reviewable Mermaid source for every report diagram.
- `assets/release-0/*.png` contains the rendered Mermaid figures embedded in the PDF.
- `assets/release-0/manifest.json` binds every figure to its Mermaid source and rendered PNG by SHA-256
  (source line endings are normalised for Windows and Unix checkouts).
- `scripts/build_release0_report.py` checks those hashes and rebuilds the PDF into
  `tmp/reports/release-0/` using the shared engine in `scripts/report_pdf.py`.

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
Release 0 commit reference; rebuilding the report does not refresh historical execution evidence.
Sections 5.5 and 8.2 explicitly link later review and execution records at separate immutable commits.
The review fixes are not attributed to Release 0; the local Compose capture runs the original
Release 0 software commit with fresh isolated volumes.

After changing a diagram, install Node.js with `npx` and refresh all figures and their manifest:

```text
uv run python scripts/build_release0_report.py --render-diagrams
```

This explicitly invokes Mermaid CLI **11.12.0**, which may download its npm package and Chromium on
first use. Commit the changed Mermaid sources, PNGs, manifest and Markdown together; the submitted PDF stays
unchanged. Do not update the manifest by hand to bypass a stale-diagram error.

The report includes a runtime architecture and selected-key ERD for every student. ERDs label query
associations separately from actual foreign keys; the linked owned schemas remain authoritative for
all columns and constraints. OpenAI is the registered provider; the team's complimentary-token
allowance is recorded as an account-specific rationale. Gemini is also supported as an alternative
with a free tier for eligible models; OpenAI remains preferred.

Feature 1's two ERDs cover selected current operational and publication/data-product relationships
after the complete migration chain through `049_index_gnaf_identity_anchors.sql`. The report links
the full SQL directory and migration runner, and records later changes to lineage, activation,
consumer delivery, SEIFA and lookup indexes. Review both diagrams and this boundary when migrations
change; the diagrams are curated schema views, not an automatically introspected database dump.

Before handoff, run the canonical gate and render the PDF for visual review:

```text
uv run python scripts/check.py
pdftoppm -scale-to 1400 -png tmp/reports/release-0/41026Group20Release0Report.pdf tmp/pdfs/report
```

Create `tmp/pdfs` first and install Poppler if it is not available. Inspect every page for clipped
tables, tiny diagram labels, orphaned text, caption placement and contents destinations. Generator
tests cover reproducibility, navigation, figure inclusion and stale assets; they do not replace this
visual review. The report's evidence limitations are retained in Section 9. Section 8.2 and the
[6 September execution record](evidence/release-0-compose-2026-09-06.md) retain the simultaneous
local all-feature startup, status, HTTP checks and deterministic fixture collection.
