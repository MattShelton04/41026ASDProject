"""Build the Release 1 technical report (Assessment 2) from its maintained Markdown source.

Every build writes the Canvas file ``docs/reports/submissions/release-1/group-20.pdf``, which is
committed so the team can track the report as it fills in. Until submission it is a draft: TODO
callouts and pending-image placeholders are rendered and the word budget is printed. ``--final``
builds the same file but refuses to while anything is outstanding.

    uv run python scripts/build_release1_report.py --status      # budget and outstanding items only
    uv run python scripts/build_release1_report.py               # draft of group-20.pdf
    uv run python scripts/build_release1_report.py --render-diagrams
    uv run python scripts/build_release1_report.py --final --baseline <40-character commit SHA>

Still to fill in before submission (each is also a TODO callout in the Markdown, so ``--status``
lists the current set with owners and line numbers):

- FINAL_BASELINE: pin every repository link to the submission commit. Draft builds link to
  ``main``; ``--final`` rejects anything but a full SHA.
- Showcase video URL and the Week 9 demonstration record (cover and Section 9).
- Features 2-5: register a corpus (``docs/release-1/adopt-mcp-and-rag.md``), then capture the
  MCP, grounded-answer and insufficient-context screenshots listed in
  ``capture_release1_screenshots.py``.
  The tool and knowledge-source tables below regenerate from ``feature.yaml`` automatically.
- Re-run both loop validation modes at the submission commit and replace the JSON under
  ``docs/release-1/evidence/`` (the retained captures predate the 26 September confidence change).
- Final ``student-N.yml`` run links at the submission commit, and a fresh Compose status capture.
- Individual contribution logs and identifiable Release 1 commits for Students 2-5.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import yaml
from reportlab.lib.units import mm

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import report_pdf
from scripts.report_pdf import REPORT_DIR, ROOT, ReportSpec

SOURCE = REPORT_DIR / "release-1-technical-report.md"
# The brief requires exactly this file name for the single group upload. Drafts are written here
# too, so the committed PDF always shows the report's current state.
OUTPUT = REPORT_DIR / "submissions" / "release-1" / "group-20.pdf"
# TODO(before submission): pass the submission commit with --baseline; drafts link to main.
DRAFT_BASELINE = "main"
WORD_LIMIT = 3000

# Targets that add up to the 3,000-word limit. Chapter titles are matched by prefix, so renaming a
# chapter's words is fine as long as its number stays the same. Adjust as sections fill in.
SECTION_WORD_BUDGETS = {
    "1 ": 300,  # Project overview and Release 1 scope
    "2 ": 350,  # Functional requirements
    "3 ": 350,  # Non-functional requirements
    "4 ": 300,  # Architecture and repository structure
    "5 ": 450,  # MCP and RAG design
    "6 ": 650,  # Validation and results
    "7 ": 150,  # Integration summary
    "8 ": 200,  # Known issues and limitations
    "9 ": 250,  # Contributions, repository and showcase links
}


def _diagram_pairs() -> dict[str, str]:
    names = (
        "release-1-architecture",
        "mcp-rag-interaction",
        "rag-pipeline",
        "agent-loop-validation",
        "ci-and-deployment",
    )
    return {f"{name}.mmd": f"{name}.png" for name in names}


def _image_max_height(path: Path) -> float:
    if "screenshots" in path.parts:
        return 105 * mm
    if path.stem in {"agent-loop-validation", "ci-and-deployment"}:
        return 120 * mm
    return 200 * mm


def _feature_manifests() -> list[dict[str, Any]]:
    """Enabled feature manifests in registry order."""
    registry = yaml.safe_load((ROOT / "deployment" / "features.yaml").read_text(encoding="utf-8"))
    enabled = [item["feature_key"] for item in registry["features"] if item.get("enabled")]
    manifests = {}
    for path in sorted(ROOT.glob("student-*/feature.yaml")):
        manifest = yaml.safe_load(path.read_text(encoding="utf-8"))
        manifest["_student"] = path.parent.name
        manifests[manifest["feature_key"]] = manifest
    return [manifests[key] for key in enabled]


def _short_name(manifest: dict[str, Any]) -> str:
    name = str(manifest.get("display_name", manifest["feature_key"]))
    return name.removeprefix("PropertyScope ").strip()


def _catalog_tools(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    catalog = (manifest.get("onboarding") or {}).get("ai", {}).get("tool_catalog")
    if not catalog:
        return []
    document = yaml.safe_load((ROOT / catalog).read_text(encoding="utf-8"))
    return [tool["definition"] for tool in document.get("tools", [])]


def _corpus(manifest: dict[str, Any]) -> dict[str, Any] | None:
    path = (manifest.get("onboarding") or {}).get("ai", {}).get("rag_corpus")
    if not path:
        return None
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def _access(tools: list[dict[str, Any]]) -> str:
    reads = sum(tool.get("side_effect") == "read_only" for tool in tools)
    writes = len(tools) - reads
    approvals = sum(bool(tool.get("requires_approval")) for tool in tools)
    parts = [f"{reads} read-only"] + ([f"{writes} write"] if writes else [])
    if approvals:
        parts.append(f"{approvals} need approval")
    return ", ".join(parts)


def tool_table(_: str) -> list[str]:
    """Body table: every enabled feature's registered MCP tools and knowledge corpus."""
    rows = [
        "| Student | Feature | Registered MCP tools | Access | RAG corpus |",
        "|---|---|---|---|---|",
    ]
    for manifest in _feature_manifests():
        tools = _catalog_tools(manifest)
        corpus = _corpus(manifest)
        corpus_cell = (
            f"{corpus['corpus_id']} ({len(corpus['documents'])} documents)"
            if corpus
            else "Not registered yet"
        )
        names = ", ".join(f"`{tool['name']}`" for tool in tools) or "None"
        rows.append(
            f"| {manifest['_student'].split('-')[1]} | {_short_name(manifest)} | {names} "
            f"| {_access(tools)} | {corpus_cell} |"
        )
    rows.append(
        "| Shared | Grounded runs | `context.retrieve.v1`, added by AI-mode to runs of features "
        "with a registered corpus | Read-only | The feature's own corpus |"
    )
    return rows


def _schema_fields(schema: dict[str, Any], *, required_only: bool) -> str:
    # Plain text, not code, so long field lists wrap between names.
    properties = schema.get("properties") or {}
    keys = schema.get("required", []) if required_only else list(properties)
    return ", ".join(keys) or "None"


def tool_detail(_: str) -> list[str]:
    """Appendix table: inputs, outputs and limits for every registered tool."""
    rows = [
        "| Tool | Required inputs | Output fields | Side effect | Timeout |",
        "|---|---|---|---|---|",
    ]
    for manifest in _feature_manifests():
        for tool in _catalog_tools(manifest):
            rows.append(
                f"| `{tool['name']}` | {_schema_fields(tool['input_schema'], required_only=True)} "
                f"| {_schema_fields(tool['output_schema'], required_only=False)} "
                f"| {tool.get('side_effect', 'unknown').replace('_', '-')}"
                f"{', approval' if tool.get('requires_approval') else ''} "
                f"| {tool.get('timeout_ms', '-')} ms |"
            )
    return rows


def corpus_table(_: str) -> list[str]:
    """Knowledge sources: one row per document of every registered corpus."""
    rows = ["| Feature | Document | Title | Source date |", "|---|---|---|---|"]
    for manifest in _feature_manifests():
        corpus = _corpus(manifest)
        if corpus is None:
            continue
        for document in corpus["documents"]:
            rows.append(
                f"| {manifest['_student'].split('-')[1]} | `{document['document_id']}` "
                f"| {document['title']} | {document.get('source_date', '-')} |"
            )
    return rows


def retrieval_summary(argument: str) -> list[str]:
    """Summarise a committed retrieval evaluation baseline (no excerpts are stored in it)."""
    path = ROOT / argument.strip()
    if not path.exists():
        return [f"[[TODO: Owner | Commit the retrieval evaluation baseline `{argument.strip()}`]]"]
    data = json.loads(path.read_text(encoding="utf-8"))
    corpus, settings = data["corpus"], data["settings"]
    return [
        "| Measure | Result |",
        "|---|---|",
        f"| Corpus | {corpus['document_count']} documents, {corpus['chunk_count']} chunks, "
        f"version `{corpus['corpus_version'][:12]}` |",
        f"| Embedding | `{corpus['embedding_model'].split('@')[0]}`, "
        f"{corpus['embedding_dimensions']} dimensions, local CPU |",
        f"| Settings | top-k {settings['top_k']}, relevance floor {settings['min_score']} |",
        f"| Supported questions | {data['supported_cases']}; expected-source recall@5 "
        f"{data['expected_source_recall_at_5']:.3f} |",
        f"| Questions the corpus does not cover | {data['absent_cases_without_context']} of "
        f"{data['absent_case_count']} retrieve no context |",
        f"| Evaluated | {data['executed_at'][:10]} |",
    ]


def loop_output(argument: str) -> list[str]:
    """Render a captured ``dev.py ai validate`` result as a compact terminal-style block."""
    path = ROOT / argument.strip()
    if not path.exists():
        return [f"[[TODO: Shared | Capture `{argument.strip()}` with `dev.py ai validate`]]"]
    data = json.loads(path.read_text(encoding="utf-8"))
    lines = [
        "```text",
        f"$ uv run scripts/dev.py ai validate {data['mode']}",
        f"mode        {data['mode']}   passed={str(data['passed']).lower()}"
        f"   status={data['status']}",
        f"run_id      {data['run_id']}",
        f"phases      {' -> '.join(data['phases'])}",
        f"transport   {data['transport']}   decisions={data['decision_provider']}",
    ]
    for result in data.get("tool_results", []):
        retrieval = result.get("retrieval") or {}
        detail = f"{result['outcome']} in {result.get('duration_ms', '?')} ms"
        if retrieval:
            detail += f", retrieval {retrieval['status']}, {len(retrieval['citations'])} citations"
            titles = [citation["title"] for citation in retrieval["citations"]][:3]
            lines.append(f"tool call   {detail}")
            lines += [f"  cites     {title}" for title in titles]
        else:
            fields = ", ".join(list((result.get("content") or {}).keys())[:4])
            lines.append(f"tool call   {detail}; structured fields: {fields}")
    final = data.get("final_result") or {}
    if "confidence" in final:
        lines.append(
            f"final       confidence={final['confidence']}  "
            f"grounding={final.get('grounding_status', '-')}"
        )
    if final.get("summary"):
        lines.append(f"summary     {final['summary'][:88]}")
    lines.append("```")
    return lines


SPEC = ReportSpec(
    release_label="RELEASE 1",
    footer_title="PropertyScope NSW  |  Release 1 Technical Report",
    pdf_title="PropertyScope NSW Release 1 Technical Report",
    pdf_subject="41026 Advanced Software Development Assessment 2",
    asset_dir=REPORT_DIR / "assets" / "release-1",
    diagram_dir=REPORT_DIR / "diagrams" / "release-1",
    diagram_pairs=_diagram_pairs(),
    image_max_height=_image_max_height,
    directives={
        "TOOL_TABLE": tool_table,
        "TOOL_DETAIL": tool_detail,
        "CORPUS_TABLE": corpus_table,
        "RETRIEVAL_SUMMARY": retrieval_summary,
        "LOOP_OUTPUT": loop_output,
    },
    word_limit=WORD_LIMIT,
    fit_code_columns=True,
    section_word_budgets=SECTION_WORD_BUDGETS,
)


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build the Release 1 technical report.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--source", type=Path, default=SOURCE)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--baseline", default=DRAFT_BASELINE, help="commit that links pin to")
    parser.add_argument("--status", action="store_true", help="print the budget and TODOs only")
    parser.add_argument(
        "--final", action="store_true", help="refuse to build while any item is outstanding"
    )
    parser.add_argument(
        "--render-diagrams",
        action="store_true",
        help="Refresh Mermaid PNGs and their drift manifest before building",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)
    source = args.source.resolve()
    status = report_pdf.review(source, SPEC)
    print(report_pdf.format_status(status, SPEC))
    if args.status:
        return 0
    if args.final:
        blockers = status.final_blockers(SPEC, args.baseline)
        if blockers:
            print("Final build blocked:\n  " + "\n  ".join(blockers), file=sys.stderr)
            return 1
    if args.render_diagrams:
        report_pdf.render_diagrams(SPEC)
    output = args.output.resolve()
    report_pdf.build(source, output, args.baseline, SPEC)
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
