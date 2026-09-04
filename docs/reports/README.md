# Reports

This directory contains the maintained Release 0 report source and submission PDF.

- [`release-0-technical-report.md`](release-0-technical-report.md) is the evidence-backed source.
- [`group20.pdf`](group20.pdf) is the Canvas submission artefact.
- `diagrams/release-0/*.mmd` contains the reviewable Mermaid source for every report diagram.
- `assets/release-0/*.png` contains the rendered Mermaid figures embedded in the PDF.
- `scripts/build_release0_report.py` validates those diagram pairs and regenerates the PDF.

The report covers all five enabled feature slices, architecture, Docker Compose, AI mode and the
agentic loop, local and GitHub Actions evidence, screenshots, contribution records and known
limitations. Regenerate and visually inspect the PDF after changing its source.

Render a changed diagram with the pinned Mermaid CLI version, for example:

```text
npx --yes @mermaid-js/mermaid-cli@11.12.0 -i docs/reports/diagrams/release-0/feature-1-runtime.mmd -o docs/reports/assets/release-0/individual-boundaries.png -b white -w 2400 -s 2
```
