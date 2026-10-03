"""Build the Release 1 technical report (Assessment 2) from its maintained Markdown source.

Every build writes the Canvas file ``docs/reports/submissions/release-1/group-20.pdf``, which is
committed so the team can track the report as it fills in. Until submission it is a draft: TODO
callouts and pending-image placeholders are rendered and the word budget is printed. ``--final``
builds the same file but refuses to while anything is outstanding.

    uv run python scripts/build_release1_report.py --status      # budget and outstanding items only
    uv run python scripts/build_release1_report.py               # draft of group-20.pdf
    uv run python scripts/build_release1_report.py --render-diagrams
    uv run python scripts/build_release1_report.py --final --baseline <40-character commit SHA>

All five enabled features register tools and corpora. The maintained source supplies the
remaining evidence and a hidden RELEASE1_METADATA index; see docs/reports/README.md. Final
builds validate that index against rendered content and the selected Git commit. A successful
build establishes report completeness, not demonstration attendance or a predicted mark.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from collections.abc import Iterable
from dataclasses import replace
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

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
REQUIRED_SECTIONS = (
    "scope",
    "requirements",
    "nonfunctional",
    "architecture",
    "design",
    "validation",
    "integration",
    "limitations",
    "contributions",
    "planning",
)
SHARED_EVIDENCE = ("terminal", "deployment", "loop-mcp", "loop-rag")
STUDENT_EVIDENCE = ("feature-mcp", "feature-rag", "feature-crud", "ci")

# Targets that add up to the 3,000-word limit. Chapter titles are matched by prefix, so renaming a
# chapter's words is fine as long as its number stays the same. Adjust as sections fill in.
SECTION_WORD_BUDGETS = {
    "1 ": 300,  # Project overview and Release 1 scope
    "2 ": 200,  # Functional requirements
    "3 ": 250,  # Non-functional requirements
    "4 ": 200,  # Architecture and repository structure
    "5 ": 800,  # MCP and RAG design, including full generated tool schemas
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
    rows = [
        "| Feature / corpus | Document and source | Source date | Provenance / licence |",
        "|---|---|---|---|",
    ]
    for manifest in _feature_manifests():
        corpus = _corpus(manifest)
        if corpus is None:
            continue
        for document in corpus["documents"]:
            manifest_path = (manifest.get("onboarding") or {}).get("ai", {}).get("rag_corpus")
            local_source = (ROOT / manifest_path).parent / document["path"]
            source_link = Path(os.path.relpath(local_source, SOURCE.parent)).as_posix()
            provenance = str(document.get("evidence_kind", "unspecified")).replace("_", " ")
            rows.append(
                f"| {manifest['_student'].split('-')[1]} / `{corpus['corpus_id']}` "
                f"| [{document['document_id']}: {document['title']}]({source_link}) "
                f"| {document.get('source_date', '-')} "
                f"| {provenance}; {document.get('license', 'unspecified')} |"
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
        f"feature     {data.get('feature_key', 'not recorded in this capture')}",
        f"tool        {data.get('tool_name', 'not recorded in this capture')}",
        f"corpus      {data.get('corpus_id') or '-'}",
        f"run_id      {data['run_id']}",
        f"request_id  {data.get('request_id', 'not recorded in this capture')}",
        f"phases      {' -> '.join(data['phases'])}",
        f"transport   {data['transport']}   decisions={data['decision_provider']}",
    ]
    for result in data.get("tool_results", []):
        retrieval = result.get("retrieval") or {}
        detail = f"{result['outcome']} in {result.get('duration_ms', '?')} ms"
        if retrieval:
            detail += f", retrieval {retrieval['status']}, {len(retrieval['citations'])} citations"
            lines.append(f"tool call   {result.get('call_id', '?')}: {detail}")
            lines.append(f"  version   {retrieval.get('corpus_version') or '-'}")
            lines += [
                f"  cites     {citation['document_id']}: {citation['title']}"
                for citation in retrieval["citations"][:3]
            ]
        else:
            fields = ", ".join(list((result.get("content") or {}).keys())[:4])
            lines.append(f"tool call   {result.get('call_id', '?')}: {detail}; fields: {fields}")
    final = data.get("final_result") or {}
    if "confidence" in final:
        lines.append(
            f"final       confidence={final['confidence']}  "
            f"grounding={final.get('grounding_status', '-')}"
        )
    if final.get("summary"):
        lines.append(f"summary     {final['summary'][:88]}")
    lines.append(f"boundary    {data.get('evidence_boundary', 'not recorded in this capture')}")
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
    count_appendices_and_code=True,
)


def _git(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(ROOT), *arguments], capture_output=True, text=True, check=False
    )


def _commit_exists(reference: str) -> bool:
    # Restrict input to a commit identity, never a user-supplied Git option or expression.
    return (
        bool(re.fullmatch(r"[0-9a-f]{7,40}", reference))
        and _git("cat-file", "-e", f"{reference}^{{commit}}").returncode == 0
    )


def _section_bodies(source: Path, *, expand: bool = True) -> dict[str, str]:
    """Index actual rendered headings, including the content of their subsections."""
    lines = report_pdf.source_lines(source, SPEC if expand else replace(SPEC, directives={}))
    headings: list[tuple[int, int, str]] = []
    in_code = False
    for index, line in enumerate(lines):
        if line.startswith("```"):
            in_code = not in_code
        heading = re.fullmatch(r"(#{2,4})\s+(.+)", line)
        if heading and not in_code:
            headings.append((index, len(heading[1]), heading[2].strip()))
    sections: dict[str, str] = {}
    for position, (index, level, title) in enumerate(headings):
        end = next(
            (other for other, depth, _ in headings[position + 1 :] if depth <= level), len(lines)
        )
        content = [
            line
            for line in lines[index + 1 : end]
            if line.strip()
            and not line.startswith("#")
            and not report_pdf.TODO_PATTERN.fullmatch(line.strip())
            and line.strip() not in {"[[TOC]]", "[[PAGEBREAK]]"}
        ]
        sections[title] = "\n".join(content)
    return sections


def _metadata(source: Path) -> dict[str, Any]:
    blocks = re.findall(
        r"<!--\s*RELEASE1_METADATA\s*\n(.*?)-->", source.read_text(encoding="utf-8"), re.DOTALL
    )
    if len(blocks) != 1:
        raise ValueError("include exactly one hidden RELEASE1_METADATA YAML block")
    try:
        metadata = yaml.safe_load(blocks[0])
    except yaml.YAMLError as error:
        raise ValueError("RELEASE1_METADATA is not valid YAML") from error
    if not isinstance(metadata, dict) or metadata.get("schema_version") != 1:
        raise ValueError("RELEASE1_METADATA must be a mapping with schema_version: 1")
    return metadata


def _cover_value(source: Path, label: str, baseline: str) -> str:
    for line in report_pdf.source_lines(source, SPEC):
        if line.startswith("## "):
            break
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) == 2 and cells[0] == label:
            value = cells[1].replace("[[BASELINE]]", baseline).strip("` ")
            link = re.fullmatch(r"\[[^\]]+\]\(([^)]+)\)", value)
            return link[1] if link else value
    return ""


def _linked_evidence(source: Path, body: str, path: Path) -> bool:
    targets = re.findall(r"\[[^\]]*\]\(([^)]+)\)", body)
    if any((source.parent / target.split("#", 1)[0]).resolve() == path for target in targets):
        return True
    # Generated output is evidence shown in the PDF, even though it has no Markdown link.
    return any(
        (ROOT / argument.strip()).resolve() == path
        for argument in re.findall(r"\[\[(?:LOOP_OUTPUT|RETRIEVAL_SUMMARY)\s+([^\]]+)\]\]", body)
    )


def _loop_capture_issue(path: Path, kind: str) -> str | None:
    """Require successful production-loop output with the identities the report displays."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return "loop evidence must be a captured validation JSON file"
    if not isinstance(data, dict):
        return "loop evidence must be a captured validation JSON object"
    mode = kind.removeprefix("loop-")
    if (
        data.get("mode") != mode
        or data.get("passed") is not True
        or data.get("status") != "succeeded"
        or data.get("phases") != ["plan", "act", "observe", "adapt"]
    ):
        return f"capture must show successful four-phase {mode} validation"
    required = ["feature_key", "tool_name", "run_id", "request_id", "evidence_boundary"]
    if mode == "rag":
        required.append("corpus_id")
    if any(not isinstance(data.get(key), str) or not data[key].strip() for key in required):
        return "loop capture omits required feature/tool/corpus/run/request/boundary identities"
    results = data.get("tool_results")
    if (
        not isinstance(results, list)
        or not results
        or any(
            not isinstance(result, dict)
            or not result.get("call_id")
            or result.get("outcome") != "succeeded"
            for result in results
        )
    ):
        return "loop capture must retain successful identified tool results"
    if mode == "rag" and not any(
        isinstance(result.get("retrieval"), dict)
        and result["retrieval"].get("corpus_version")
        and result["retrieval"].get("status") in {"ready", "no_match", "empty"}
        for result in results
    ):
        return "RAG loop capture must retain the retrieved corpus version and status"
    return None


def final_content_blockers(source: Path, baseline: str) -> list[str]:
    """Validate explicit author evidence references without guessing from prose keywords."""
    blockers: list[str] = []
    baseline_exists = bool(report_pdf.COMMIT_SHA_PATTERN.fullmatch(baseline)) and _commit_exists(
        baseline
    )
    if report_pdf.COMMIT_SHA_PATTERN.fullmatch(baseline) and not baseline_exists:
        blockers.append(f"baseline {baseline!r} does not resolve to a Git commit")
    try:
        metadata = _metadata(source)
    except ValueError as error:
        return [*blockers, str(error)]
    if str(metadata.get("baseline", "")).replace("[[BASELINE]]", baseline) != baseline:
        blockers.append("metadata baseline does not match --baseline")
    if _cover_value(source, "Commit reference", baseline) != baseline:
        blockers.append("cover Commit reference does not match --baseline")
    repository = report_pdf.REPOSITORY_URL
    if (
        metadata.get("repository_url") != repository
        or _cover_value(source, "Repository", baseline) != repository
    ):
        blockers.append("cover and metadata must contain the shared repository URL")
    video = str(metadata.get("showcase_url", ""))
    parsed_video = urlparse(video)
    if (
        parsed_video.scheme != "https"
        or not parsed_video.netloc
        or parsed_video.username
        or _cover_value(source, "Showcase video", baseline) != video
    ):
        blockers.append("cover and metadata must contain the same HTTPS showcase URL")
    sections = _section_bodies(source)
    raw_sections = _section_bodies(source, expand=False)
    declared = metadata.get("sections")
    if not isinstance(declared, dict):
        declared = {}
    for requirement in REQUIRED_SECTIONS:
        title = declared.get(requirement)
        if not isinstance(title, str) or not sections.get(title, "").strip():
            blockers.append(f"missing or empty required section: {requirement}")
    evidence = metadata.get("evidence")
    if not isinstance(evidence, list):
        evidence = []
    covered: set[tuple[str, str]] = set()
    students = [str(manifest["_student"].split("-")[1]) for manifest in _feature_manifests()]
    for number, item in enumerate(evidence, 1):
        prefix = f"evidence {number}"
        if not isinstance(item, dict):
            blockers.append(f"{prefix}: expected a mapping")
            continue
        kind, student = str(item.get("kind", "")), str(item.get("student", ""))
        body = sections.get(str(item.get("section", "")), "")
        if not body or not str(item.get("boundary", "")).strip():
            blockers.append(f"{prefix}: a populated section and evidence boundary are required")
            continue
        path, url = str(item.get("path", "")), str(item.get("url", ""))
        if bool(path) == bool(url):
            blockers.append(f"{prefix}: supply one path or URL")
            continue
        if path:
            resolved = (ROOT / path).resolve()
            if (
                not resolved.is_relative_to(ROOT)
                or not resolved.is_file()
                or not resolved.stat().st_size
            ):
                blockers.append(f"{prefix}: missing repository file {path}")
                continue
            if not _linked_evidence(
                source, raw_sections.get(str(item.get("section", "")), ""), resolved
            ):
                blockers.append(f"{prefix}: {path} is not shown or linked in its section")
                continue
            if baseline_exists:
                repository_path = resolved.relative_to(ROOT).as_posix()
                stored = _git("rev-parse", "--verify", f"{baseline}:{repository_path}")
                if stored.returncode:
                    blockers.append(f"{prefix}: {path} is not tracked at the baseline")
                    continue
                current = _git("hash-object", "--path", repository_path, str(resolved))
                if current.returncode or current.stdout.strip() != stored.stdout.strip():
                    blockers.append(f"{prefix}: {path} differs from the baseline evidence")
                    continue
            if kind in {"loop-mcp", "loop-rag"}:
                issue = _loop_capture_issue(resolved, kind)
                if issue:
                    blockers.append(f"{prefix}: {issue}")
                    continue
        else:
            parsed = urlparse(url)
            if parsed.scheme != "https" or not parsed.netloc or parsed.username or url not in body:
                blockers.append(f"{prefix}: HTTPS URL must be linked in its section")
                continue
            if kind == "ci" and (
                not re.fullmatch(re.escape(repository) + r"/actions/runs/\d+", url)
                or item.get("workflow") != f"student-{student}.yml"
            ):
                blockers.append(f"{prefix}: CI needs its student workflow and repository run URL")
                continue
        covered.add((kind, student if kind in STUDENT_EVIDENCE else ""))
    expected = {(kind, "") for kind in SHARED_EVIDENCE} | {
        (kind, student) for student in students for kind in STUDENT_EVIDENCE
    }
    blockers += [
        f"missing evidence: {kind}" + (f" for Student {student}" if student else "")
        for kind, student in sorted(expected - covered)
    ]
    contributions = metadata.get("contributions")
    if not isinstance(contributions, list):
        contributions = []
    recorded: set[str] = set()
    for item in contributions:
        if not isinstance(item, dict):
            continue
        student = str(item.get("student", ""))
        body = sections.get(str(item.get("section", "")), "")
        commits = item.get("commits")
        if not body or not isinstance(commits, list) or not commits:
            continue
        valid = True
        for commit in commits:
            reference = str(commit)
            if reference not in body or not _commit_exists(reference):
                blockers.append(
                    f"Student {student}: commit {reference!r} must resolve and appear in the log"
                )
                valid = False
            elif (
                baseline_exists
                and _git("merge-base", "--is-ancestor", reference, baseline).returncode
            ):
                blockers.append(f"Student {student}: commit {reference} is not in the baseline")
                valid = False
        if valid:
            recorded.add(student)
    blockers += [
        f"missing contribution log and commits for Student {student}"
        for student in students
        if student not in recorded
    ]
    attendance = metadata.get("attendance")
    if not isinstance(attendance, dict):
        attendance = {}
    contribution_body = sections.get(str(declared.get("contributions", "")), "")
    for student in students:
        statement = attendance.get(int(student), attendance.get(student))
        if (
            not isinstance(statement, str)
            or not statement.strip()
            or statement not in contribution_body
        ):
            blockers.append(
                f"Student {student}: record actual showcase participation "
                "or its limitation in the report"
            )
    return blockers


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
    content_blockers = final_content_blockers(source, args.baseline)
    if content_blockers and (args.status or not args.final):
        print("Submission evidence to review:\n  " + "\n  ".join(content_blockers))
    if args.status:
        return 0
    if args.final:
        blockers = status.final_blockers(SPEC, args.baseline) + content_blockers
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
