"""Build the Release 2 technical report (Assessment 3) from its maintained Markdown source.

Every build writes the Canvas file ``docs/reports/submissions/release-2/group-20.pdf``. Until
submission it is a draft: TODO callouts and pending-image placeholders are rendered and the word
budget is printed. ``--final`` builds the same file but refuses to while anything is outstanding.

    uv run python scripts/build_release2_report.py --status      # budget and outstanding items only
    uv run python scripts/build_release2_report.py               # draft of group-20.pdf
    uv run python scripts/build_release2_report.py --render-diagrams
    uv run python scripts/build_release2_report.py --final --baseline <40-character commit SHA>

The PDF template, Markdown dialect, word count and diagram checks come from ``report_pdf``; the
feature-manifest readers come from the Release 1 builder. This module adds Release 2's generated
evidence tables, which read ``docs/release-2/evidence/`` and turn a missing file into a TODO, and
the final guard over the hidden RELEASE2_METADATA evidence index. See docs/reports/README.md.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from collections import Counter
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml
from reportlab.lib.units import mm

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import build_release1_report as release1
from scripts import report_pdf
from scripts.report_pdf import REPORT_DIR, ROOT, ReportSpec

SOURCE = REPORT_DIR / "release-2-technical-report.md"
EVIDENCE_DIR = ROOT / "docs" / "release-2" / "evidence"
# The brief requires exactly this file name for the single group upload.
OUTPUT = REPORT_DIR / "submissions" / "release-2" / "group-20.pdf"
DRAFT_BASELINE = "main"
WORD_LIMIT = 3000
TEAM = {
    "1": "Matthew Shelton",
    "2": "Burhan Naeem",
    "3": "James Huang",
    "4": "Michael White",
    "5": "Derek Song",
}
SHARED_OWNER = TEAM["1"]
REVIEW_MODES = ("multi-agent", "testing", "cloud")
# The brief's Technical Report table, in order. Values name the metadata `sections` keys.
REQUIRED_SECTIONS = (
    "overview",
    "repository",
    "design",
    "architecture",
    "security",
    "ci",
    "testing_review",
    "local",
    "cloud",
    "multi_agent",
    "commits",
    "contributions",
    "bonus",
    "showcase",
)
SHARED_EVIDENCE = (
    "security-report",
    "testing-review",
    "multi-agent-review",
    "cloud-review",
    "release-decision",
    "local-deployment",
    "cloud-deployment",
    "cloud-workflow",
)
STUDENT_EVIDENCE = ("ci", "multi-agent")
URL_KINDS = {"ci", "cloud-workflow"}

# Targets that add up to the 3,000-word limit, cover included. Chapters are matched by their
# number prefix. Each student-owned chapter reserves room for Students 2-5.
SECTION_WORD_BUDGETS = {
    "1 ": 220,  # Project overview, team, allocation, Release 1 to Release 2
    "2 ": 160,  # Final repository structure
    "3 ": 320,  # Design flow: shared flows plus about 40 words per student
    "4 ": 230,  # Azure reference architecture and DevOps flow
    "5 ": 210,  # Pre-commit security testing (generated summary and slice table)
    "6 ": 440,  # Post-commit CI: generated run table plus about 70 words per student
    "7 ": 130,  # Testing review
    "8 ": 210,  # Local deployment and multi-terminal logs
    "9 ": 190,  # Cloud deployment report, review and human release decision
    "10 ": 400,  # Multi-agent evidence: shared, F1 worked example, about 50 words per student
    "11 ": 30,  # GitHub commit log URL
    "12 ": 300,  # Contribution logs, about 60 words per student
    "13 ": 60,  # Bonus evidence
    "14 ": 40,  # Showcase video and participation
}


def _diagram_pairs() -> dict[str, str]:
    names = (
        "release-2-architecture",
        "multi-agent-sequence",
        "azure-reference-architecture",
        "devops-flow",
    )
    return {f"{name}.mmd": f"{name}.png" for name in names}


def _image_max_height(path: Path) -> float:
    if "screenshots" in path.parts:
        return float(95 * mm)
    if path.stem == "multi-agent-sequence":
        return float(215 * mm)
    return float(190 * mm)


# --------------------------------------------------------------------------------------------
# Evidence readers. Each directive reads only committed evidence and is deterministic; a missing
# or unreadable file becomes a TODO line, which renders as a callout and blocks --final.


def _todo(owner: str, text: str) -> str:
    return f"[[TODO: {owner} | {text}]]"


def _cell(value: object) -> str:
    # The report's table parser splits on every pipe, escaped or not.
    return str(value).replace("\\|", "/").replace("|", "/").replace("\n", " ").strip() or "-"


def _link(path: Path) -> str:
    """A Markdown link target for an evidence file, relative to the report source."""
    try:
        return Path(os.path.relpath(path, SOURCE.parent)).as_posix()
    except ValueError:  # Another drive on Windows.
        return path.as_posix()


def _evidence_path(relative: str) -> Path:
    return EVIDENCE_DIR / relative.strip()


def _shown(path: Path) -> str:
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def _fields(text: str) -> dict[str, str]:
    """Two-column ``| Field | Value |`` rows, first occurrence wins."""
    fields: dict[str, str] = {}
    for line in text.splitlines():
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if line.lstrip().startswith("|") and len(cells) >= 2 and cells[0]:
            fields.setdefault(cells[0], " | ".join(cells[1:]).strip())
    return fields


def _table_after(text: str, heading: str) -> list[list[str]]:
    """Body rows of the first Markdown table after a heading, without the header row."""
    lines = text.splitlines()
    try:
        start = next(index for index, line in enumerate(lines) if line.strip() == heading)
    except StopIteration:
        return []
    rows: list[list[str]] = []
    for line in lines[start + 1 :]:
        stripped = line.strip()
        if stripped.startswith("#"):
            break
        if not stripped.startswith("|"):
            if rows:
                break
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells):
            continue
        rows.append(cells)
    return rows[1:]


def _plain(value: str) -> str:
    return re.sub(r"\*\*([^*]+)\*\*", r"\1", value).strip("` ")


def feature_flows(_: str) -> list[str]:
    """Each enabled feature's CRUD path, retained Release 1 AI wiring and Release 2 workflow."""
    rows = [
        "| Student | Frontend → backend/API → database | MCP tools | RAG documents "
        "| Multi-agent template |",
        "|---|---|---|---|---|",
    ]
    for manifest in release1._feature_manifests():
        onboarding = manifest.get("onboarding") or {}
        port = (onboarding.get("frontend") or {}).get("host_port_default", "?")
        databases = ", ".join(
            f"`{item['database_service']}`"
            for item in onboarding.get("databases") or []
            if isinstance(item, dict) and item.get("database_service")
        )
        corpus = release1._corpus(manifest)
        template = ROOT / manifest["_student"] / "config" / "multi-agent" / "workflow.yaml"
        workflow = "Not registered yet"
        if template.is_file():
            document = yaml.safe_load(template.read_text(encoding="utf-8")) or {}
            tools = len(document.get("allowed_tools") or [])
            workflow = f"`{document.get('id', '?')}` ({tools} read-only tools)"
        rows.append(
            f"| {manifest['_student'].split('-')[1]} | :{port} → "
            f"`{manifest.get('backend_base_path', '?')}` → {databases or '-'} "
            f"| {len(release1._catalog_tools(manifest))} "
            f"| {len(corpus['documents']) if corpus else 0} | {workflow} |"
        )
    return rows


def security_summary(argument: str) -> list[str]:
    """Scan results, scanned commit and per-slice results from the pre-commit security report."""
    path = _evidence_path(argument or "security/pre-commit-report.md")
    text = _read_text(path)
    if text is None:
        return [_todo(SHARED_OWNER, f"Run `dev.py security report` to write `{_shown(path)}`")]
    commit = re.search(r"\*\*Commit scanned:\*\*\s*`([0-9a-f]{7,40})`", text)
    generated = re.search(r"\*\*Generated:\*\*\s*(\d{4}-\d{2}-\d{2})", text)
    overall = re.search(r"\*\*Overall:\*\*\s*\*\*(\w+)\*\*", text)
    rows = [
        f"[Security report]({_link(path)}): overall **{overall[1] if overall else 'unknown'}**, "
        f"commit `{commit[1][:7] if commit else 'unrecorded'}`, "
        f"{generated[1] if generated else 'undated'}.",
        "",
        "| Scan | Result | Findings |",
        "|---|---|---|",
    ]
    scans = _table_after(text, "## Summary")
    rows += [f"| {_cell(row[1])} | {_cell(row[2])} | {_cell(row[3])} |" for row in scans[:3]]
    slices = [row for row in _table_after(text, "## Results by slice") if len(row) >= 8]
    if slices:
        rows += [
            "",
            "| Slice | Owner | Ruff open | Fixed | Noqa | Pending owner | Secrets to act on |",
            "|---|---|---|---|---|---|---|",
        ]
        rows += [
            f"| {_cell(row[0])} | {_cell(row[1].split('(')[0])} | {row[2]} | {row[3]} "
            f"| {row[4]} | {row[5]} | {row[7]} |"
            for row in slices
        ]
    if not scans:
        rows.append(_todo(SHARED_OWNER, f"`{_shown(path)}` has no scan summary table"))
    return rows


TOTALS = re.compile(
    r"(\d+) passed, (\d+) failed, (\d+) errors?, (\d+) skipped of (\d+) tests", re.IGNORECASE
)
RUN_LINK = re.compile(r"\[#(\d+)[^\]]*\]\((https://github\.com/[^)]+/actions/runs/\d+[^)]*)\)")


def _ci_row(student: str) -> tuple[str, str | None]:
    path = EVIDENCE_DIR / "ci" / f"student-{student}.md"
    text = _read_text(path)
    if text is None:
        return (
            f"| {student} | Pending | - | - | - |",
            _todo(
                TEAM.get(student, "Owner"),
                f"Record a green `student-{student}.yml` run on main with "
                f"`collect_ci_evidence.py --student {student}`",
            ),
        )
    fields = _fields(text)
    run = RUN_LINK.search(fields.get("Run", ""))
    conclusion = _plain(fields.get("Conclusion", "unknown"))
    sha = _plain(fields.get("Head SHA", ""))[:7] or "-"
    totals = [tuple(int(value) for value in match) for match in TOTALS.findall(text)]
    failed = errors = 0
    if totals:
        passed, failed, errors = (sum(item[index] for item in totals) for index in range(3))
        reports = f"{len(totals)} report{'s' if len(totals) != 1 else ''}"
        tests = f"{passed} passed, {failed + errors} failed ({reports})"
    else:
        tests = "No JUnit totals"
    run_cell = f"[#{run[1]}]({run[2]})" if run else "Unlinked"
    record = f"[record]({_link(path)})"
    row = f"| {student} | {run_cell} | {_cell(conclusion)} | `{sha}` | {tests} ({record}) |"
    issue = None
    if not run or conclusion != "success" or not totals or failed + errors:
        issue = _todo(
            TEAM.get(student, "Owner"),
            f"`{_shown(path)}` must link a successful run whose endpoint tests all pass",
        )
    return row, issue


def ci_evidence(_: str) -> list[str]:
    """One row per student from ``ci/student-N.md``, written by ``collect_ci_evidence.py``."""
    rows = [
        "| Student | `student-N.yml` run | Conclusion | Commit | Endpoint tests |",
        "|---|---|---|---|---|",
    ]
    issues: list[str] = []
    for student in TEAM:
        row, issue = _ci_row(student)
        rows.append(row)
        if issue:
            issues.append(issue)
    return rows + (["", *issues] if issues else [])


def review_summary(argument: str) -> list[str]:
    """Verdict, checklist, engine, loop run and summary of one agentic-loop review mode."""
    mode = argument.strip()
    if mode not in REVIEW_MODES:
        raise ValueError(f"unknown review mode {mode!r}")
    path = EVIDENCE_DIR / "reviews" / f"{mode}-review.md"
    log = EVIDENCE_DIR / "reviews" / f"{mode}-validation-log.jsonl"
    text = _read_text(path)
    if text is None:
        return [_todo(SHARED_OWNER, f"Run `dev.py ai review {mode}` to write `{_shown(path)}`")]
    fields = _fields(text)
    checklist = re.search(r"^## Checklist \((\d+)/(\d+) passed\)", text, re.MULTILINE)
    summary = re.search(r"^## Summary\s*\n+(.+?)\n\s*\n", text, re.MULTILINE | re.DOTALL)
    run = re.search(r"`([0-9a-f-]{8})[0-9a-f-]*`", fields.get("Loop run ID", ""))
    model = fields.get("Provider / model", "")
    engine = "deterministic" if "deterministic" in fields.get("Engine", "").lower() else "AI-mode"
    when = fields.get("Started / finished", "")[:10] or "-"
    entries = 0
    log_text = _read_text(log)
    if log_text is not None:
        entries = sum(1 for line in log_text.splitlines() if line.strip())
    rows = [
        "| Verdict | Checklist | Engine and model | Loop run | Date | Validation log |",
        "|---|---|---|---|---|---|",
        f"| **{_plain(fields.get('Verdict', 'unknown'))}** "
        f"| {f'{checklist[1]}/{checklist[2]} passed' if checklist else '-'} "
        f"| {engine}, {_cell(model) if model else '-'} | `{run[1] if run else '-'}` | {when} "
        f"| [{entries} {'entry' if entries == 1 else 'entries'}]({_link(log)}) |",
    ]
    if summary:
        rows += ["", f"> {_cell(' '.join(summary[1].split()))} ([full review]({_link(path)}))"]
    if log_text is None:
        rows.append(_todo(SHARED_OWNER, f"Commit the validation log `{_shown(log)}`"))
    return rows


def _jsonl(path: Path) -> list[dict[str, Any]] | None:
    text = _read_text(path)
    if text is None:
        return None
    try:
        return [json.loads(line) for line in text.splitlines() if line.strip()]
    except ValueError:
        return None


def _run_row(directory: Path) -> str | None:
    """A summary row for one exported run, or None when the export is incomplete."""
    try:
        run = json.loads((directory / "run.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    history = _jsonl(directory / "workflow_history.jsonl")
    audit = _jsonl(directory / "coordination_audit.jsonl")
    if not isinstance(run, dict) or history is None or audit is None:
        return None
    events = Counter(str(item.get("event")) for item in audit)
    decisions = " → ".join(
        str(item.get("decision")) for item in run.get("decisions") or [] if isinstance(item, dict)
    )
    return (
        f"| [`{str(run.get('id', '?'))[:8]}`]({_link(directory / 'summary.md')}) "
        f"| {len(history)} | {len(audit)} | {events['agent.handoff']} | {events['tool.call']} "
        f"| {decisions or '-'} | `{_cell(run.get('state', '?'))}` |"
    )


def multi_agent_runs(argument: str) -> list[str]:
    """Exported runs under ``multi-agent/student-N/``; students without one get a TODO."""
    students = argument.split() or [f"student-{number}" for number in TEAM]
    rows = [
        "| Student | Run | History events | Audit events | Handoffs | Tool calls "
        "| Decisions | Final state |",
        "|---|---|---|---|---|---|---|---|",
    ]
    issues: list[str] = []
    for student in students:
        number = student.removeprefix("student-")
        base = EVIDENCE_DIR / "multi-agent" / student
        found = [
            row
            for row in (_run_row(path.parent) for path in sorted(base.rglob("run.json")))
            if row is not None
        ]
        rows += [f"| {number} {row}" for row in found]
        if not found:
            rows.append(f"| {number} | Pending | - | - | - | - | - | - |")
            issues.append(
                _todo(
                    TEAM.get(number, "Owner"),
                    f"Export a decided run with `multi-agent-server export <run> --server` "
                    f"into `{_shown(base)}/`",
                )
            )
    return rows + (["", *issues] if issues else [])


def _clock(value: object) -> str:
    match = re.search(r"T(\d{2}:\d{2}:\d{2})", str(value))
    return match[1] if match else "--:--:--"


def workflow_history(argument: str) -> list[str]:
    """The exported state transitions of one run as a compact terminal-style block."""
    directory = _evidence_path(argument)
    history = _jsonl(directory / "workflow_history.jsonl")
    if not history:
        return [_todo(SHARED_OWNER, f"Export the workflow history into `{_shown(directory)}`")]
    lines = ["```text", f"$ multi-agent-server export {history[0].get('run_id', '?')}"]
    for item in history:
        source = item.get("from_state") or "-"
        lines.append(
            f"{_clock(item.get('at'))} r{item.get('round', '?')} {source:>14} -> "
            f"{item.get('to_state', '?'):<18} {item.get('actor', '?')}"
        )
    return [*lines, "```"]


def _check_groups(text: str) -> list[tuple[str, int, int]]:
    """PASS and FAIL rows per ``###`` group below the report's ``## All checks`` heading."""
    groups: list[tuple[str, int, int]] = []
    inside = False
    for line in text.splitlines():
        if line.startswith("## "):
            inside = line.strip() == "## All checks"
            continue
        if not inside:
            continue
        if line.startswith("### "):
            groups.append((line[4:].strip(), 0, 0))
            continue
        result = re.match(r"^\|\s*(PASS|FAIL)\s*\|", line)
        if result and groups:
            name, passed, failed = groups[-1]
            groups[-1] = (name, passed + (result[1] == "PASS"), failed + (result[1] == "FAIL"))
    return groups


def local_evidence(argument: str) -> list[str]:
    """The local deployment report's verdict, check groups and multi-terminal logs."""
    directory = _evidence_path(argument or "local")
    report = directory / "local-deployment-report.md"
    text = _read_text(report)
    rows: list[str] = []
    terminals: list[list[str]] = []
    if text is None:
        rows.append(_todo(SHARED_OWNER, f"Record the local deployment report `{_shown(report)}`"))
    else:
        verdict = re.search(r"\*\*Verdict:\s*(\w+)\*\*,?\s*(\d+) of (\d+) checks passed", text)
        fields = _fields(text)
        commit = re.search(r"`([0-9a-f]{7,40})`", fields.get("Commit", ""))
        rows.append(
            f"[Local deployment report]({_link(report)}): "
            + (f"**{verdict[1]}**, {verdict[2]} of {verdict[3]} checks passed" if verdict else "")
            + f", captured {fields.get('Captured', '')[:10] or 'undated'} at commit "
            f"`{commit[1][:7] if commit else 'unrecorded'}`."
        )
        groups = _check_groups(text)
        if groups:
            rows += ["", "| Check group | Passed | Failed |", "|---|---|---|"]
            rows += [f"| {_cell(name)} | {passed} | {failed} |" for name, passed, failed in groups]
        if not verdict or verdict[2] != verdict[3]:
            rows.append(_todo(SHARED_OWNER, f"`{_shown(report)}` must record every check passing"))
        terminals = [row for row in _table_after(text, "## Terminals") if len(row) >= 4]
    if terminals:
        rows += ["", "| Terminal | Ran as | Command | Log |", "|---|---|---|---|"]
        for row in terminals:
            # Find cells by content, so a column added to the capture's table never shifts them.
            log_cell = next((cell for cell in row if re.search(r"\]\(terminal-", cell)), "")
            log = re.search(r"\]\(([^)]+)\)", log_cell)
            target = f"[`{Path(log[1]).name}`]({_link(directory / log[1])})" if log else "-"
            command = next((cell for cell in row[2:] if cell.startswith("`")), "-")
            ran_as = next((cell for cell in row if cell in {"managed", "foreground"}), "-")
            rows.append(f"| {_cell(row[1])} | {ran_as} | {_cell(command)} | {target} |")
        return rows
    logs = sorted(directory.glob("terminal-*.log")) if directory.is_dir() else []
    if logs:
        rows += ["", "| Terminal log | Lines |", "|---|---|"]
        for path in logs:
            lines = len((_read_text(path) or "").splitlines())
            rows.append(f"| [`{path.name}`]({_link(path)}) | {lines} |")
    else:
        rows.append(
            _todo(
                SHARED_OWNER, f"Record the multi-terminal logs `{_shown(directory)}/terminal-*.log`"
            )
        )
    return rows


def cloud_summary(_: str) -> list[str]:
    """Cloud deployment result and the human release decision, from ``evidence/cloud/``."""
    report = EVIDENCE_DIR / "cloud" / "cloud-deployment-report.md"
    decision = EVIDENCE_DIR / "cloud" / "release-decision.md"
    rows = ["| Item | Recorded |", "|---|---|"]
    issues: list[str] = []
    text = _read_text(report)
    if text is None:
        rows.append("| Deployment | Pending |")
        issues.append(
            _todo(SHARED_OWNER, f"Copy the workflow's deployment report into `{_shown(report)}`")
        )
    else:
        fields = _fields(text)
        rows += [
            f"| Deployment | **{_cell(_plain(fields.get('Result', 'unknown')))}** "
            f"([report]({_link(report)})) |",
            f"| Public URL | {_cell(fields.get('Public URL', '-'))} |",
            f"| Commit / image tag | {_cell(fields.get('Commit / image tag', '-'))} |",
            f"| Workflow run | {_cell(fields.get('Workflow run', '-'))} |",
            f"| AI tier | {_cell(fields.get('AI tier', '-'))} |",
        ]
    text = _read_text(decision)
    if text is None:
        rows.append("| Human release decision | Pending |")
        issues.append(
            _todo(SHARED_OWNER, "Record the human decision with `dev.py ai review decide`")
        )
    else:
        fields = _fields(text)
        rows.append(
            f"| Human release decision | **{_cell(_plain(fields.get('Decision', 'unknown')))}** "
            f"by {_cell(fields.get('Decided by', '?'))}, {fields.get('Decided at', '')[:10]} "
            f"([record]({_link(decision)})) |"
        )
    return rows + (["", *issues] if issues else [])


SPEC = ReportSpec(
    release_label="RELEASE 2",
    footer_title="PropertyScope NSW  |  Release 2 Technical Report",
    pdf_title="PropertyScope NSW Release 2 Technical Report",
    pdf_subject="41026 Advanced Software Development Assessment 3",
    asset_dir=REPORT_DIR / "assets" / "release-2",
    diagram_dir=REPORT_DIR / "diagrams" / "release-2",
    diagram_pairs=_diagram_pairs(),
    image_max_height=_image_max_height,
    directives={
        "FEATURE_FLOWS": feature_flows,
        "SECURITY_SUMMARY": security_summary,
        "CI_EVIDENCE": ci_evidence,
        "REVIEW_SUMMARY": review_summary,
        "MULTI_AGENT_RUNS": multi_agent_runs,
        "WORKFLOW_HISTORY": workflow_history,
        "LOCAL_EVIDENCE": local_evidence,
        "CLOUD_SUMMARY": cloud_summary,
    },
    word_limit=WORD_LIMIT,
    fit_code_columns=True,
    section_word_budgets=SECTION_WORD_BUDGETS,
    count_appendices_and_code=True,
    count_cover_and_captions=True,
    figure_min_scale=0.7,
    subsection_min_space=35 * mm,
)


# --------------------------------------------------------------------------------------------
# Final guard over the hidden RELEASE2_METADATA evidence index.


def _git(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - fixed git argv, no shell
        ["git", "-C", str(ROOT), *arguments],  # noqa: S607 - git is resolved from the developer PATH
        capture_output=True,
        text=True,
        check=False,
    )


def _commit_exists(reference: str) -> bool:
    # Restrict input to a commit identity, never a user-supplied Git option or expression.
    return (
        bool(re.fullmatch(r"[0-9a-f]{7,40}", reference))
        and _git("cat-file", "-e", f"{reference}^{{commit}}").returncode == 0
    )


def _section_bodies(source: Path) -> dict[str, str]:
    """Rendered headings with the expanded content of their subsections, TODOs excluded."""
    lines = report_pdf.source_lines(source, SPEC)
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
        sections[title] = "\n".join(
            line
            for line in lines[index + 1 : end]
            if line.strip()
            and not line.startswith("#")
            and not report_pdf.TODO_PATTERN.fullmatch(line.strip())
            and line.strip() not in {"[[TOC]]", "[[PAGEBREAK]]"}
        )
    return sections


def _metadata(source: Path) -> dict[str, Any]:
    blocks = re.findall(
        r"<!--\s*RELEASE2_METADATA\s*\n(.*?)-->", source.read_text(encoding="utf-8"), re.DOTALL
    )
    if len(blocks) != 1:
        raise ValueError("include exactly one hidden RELEASE2_METADATA YAML block")
    try:
        metadata = yaml.safe_load(blocks[0])
    except yaml.YAMLError as error:
        raise ValueError("RELEASE2_METADATA is not valid YAML") from error
    if not isinstance(metadata, dict) or metadata.get("schema_version") != 1:
        raise ValueError("RELEASE2_METADATA must be a mapping with schema_version: 1")
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


def _linked(source: Path, body: str, path: Path) -> bool:
    targets = re.findall(r"\[[^\]]*\]\(([^)]+)\)", body)
    return any((source.parent / target.split("#", 1)[0]).resolve() == path for target in targets)


def _https(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme == "https" and bool(parsed.netloc) and not parsed.username


def _evidence_issue(
    item: Mapping[str, Any], source: Path, body: str, baseline: str, baseline_exists: bool
) -> str | None:
    kind, student = str(item.get("kind", "")), str(item.get("student", ""))
    path, url = str(item.get("path", "")), str(item.get("url", ""))
    if bool(path) == bool(url):
        return "supply one path or URL"
    if url:
        if not _https(url) or url not in body:
            return "HTTPS URL must be linked in its section"
        if kind in URL_KINDS and not re.fullmatch(
            re.escape(report_pdf.REPOSITORY_URL) + r"/actions/runs/\d+", url
        ):
            return "a workflow URL must be a run of the shared repository"
        if kind == "ci" and item.get("workflow") != f"student-{student}.yml":
            return f"CI needs workflow student-{student}.yml"
        return None
    if kind == "cloud-workflow":
        return "cloud-workflow evidence must be the Actions run URL"
    resolved = (ROOT / path).resolve()
    if not resolved.is_relative_to(ROOT) or not resolved.is_file() or not resolved.stat().st_size:
        return f"missing repository file {path}"
    if not _linked(source, body, resolved):
        return f"{path} is not shown or linked in its section"
    if baseline_exists:
        repository_path = resolved.relative_to(ROOT).as_posix()
        stored = _git("rev-parse", "--verify", f"{baseline}:{repository_path}")
        if stored.returncode:
            return f"{path} is not tracked at the baseline"
        current = _git("hash-object", "--path", repository_path, str(resolved))
        if current.returncode or current.stdout.strip() != stored.stdout.strip():
            return f"{path} differs from the baseline evidence"
    return None


def final_content_blockers(source: Path, baseline: str) -> list[str]:
    """Check the evidence index against rendered content and the selected baseline commit."""
    blockers: list[str] = []
    is_sha = bool(report_pdf.COMMIT_SHA_PATTERN.fullmatch(baseline))
    baseline_exists = is_sha and _commit_exists(baseline)
    if is_sha and not baseline_exists:
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
    if not _https(video) or _cover_value(source, "Showcase video", baseline) != video:
        blockers.append("cover and metadata must contain the same HTTPS showcase URL")
    sections = _section_bodies(source)
    declared = metadata.get("sections")
    declared = declared if isinstance(declared, dict) else {}
    for requirement in REQUIRED_SECTIONS:
        title = declared.get(requirement)
        if not isinstance(title, str) or not sections.get(title, "").strip():
            blockers.append(f"missing or empty required section: {requirement}")
    commits_url = f"{repository}/commits/main"
    if commits_url not in sections.get(str(declared.get("commits", "")), ""):
        blockers.append(f"the commit log section must link {commits_url}")
    evidence = metadata.get("evidence")
    covered: set[tuple[str, str]] = set()
    for number, item in enumerate(evidence if isinstance(evidence, list) else [], 1):
        if not isinstance(item, dict):
            blockers.append(f"evidence {number}: expected a mapping")
            continue
        body = sections.get(str(item.get("section", "")), "")
        if not body or not str(item.get("boundary", "")).strip():
            blockers.append(
                f"evidence {number}: a populated section and evidence boundary are required"
            )
            continue
        issue = _evidence_issue(item, source, body, baseline, baseline_exists)
        if issue:
            blockers.append(f"evidence {number}: {issue}")
            continue
        kind = str(item.get("kind", ""))
        covered.add((kind, str(item.get("student", "")) if kind in STUDENT_EVIDENCE else ""))
    expected = {(kind, "") for kind in SHARED_EVIDENCE} | {
        (kind, student) for student in TEAM for kind in STUDENT_EVIDENCE
    }
    blockers += [
        f"missing evidence: {kind}" + (f" for Student {student}" if student else "")
        for kind, student in sorted(expected - covered)
    ]
    contributions = metadata.get("contributions")
    recorded: set[str] = set()
    for item in contributions if isinstance(contributions, list) else []:
        if not isinstance(item, dict):
            continue
        student = str(item.get("student", ""))
        body = sections.get(str(item.get("section", "")), "")
        commits = item.get("commits")
        if not body or not isinstance(commits, list) or not commits:
            continue
        valid = True
        for commit in map(str, commits):
            if commit not in body or not _commit_exists(commit):
                blockers.append(
                    f"Student {student}: commit {commit!r} must resolve and appear in the log"
                )
                valid = False
            elif (
                baseline_exists and _git("merge-base", "--is-ancestor", commit, baseline).returncode
            ):
                blockers.append(f"Student {student}: commit {commit} is not in the baseline")
                valid = False
        if valid:
            recorded.add(student)
    blockers += [
        f"missing contribution log and commits for Student {student}"
        for student in TEAM
        if student not in recorded
    ]
    attendance = metadata.get("attendance")
    attendance = attendance if isinstance(attendance, dict) else {}
    showcase = sections.get(str(declared.get("showcase", "")), "")
    for student in TEAM:
        statement = attendance.get(int(student), attendance.get(student))
        if not isinstance(statement, str) or not statement.strip() or statement not in showcase:
            blockers.append(
                f"Student {student}: record actual showcase participation in the showcase section"
            )
    return blockers


def owner_summary(status: report_pdf.ReportStatus) -> str:
    counts = Counter(todo.owner for todo in status.todos)
    if not counts:
        return "No TODOs remain."
    return "TODOs by owner: " + ", ".join(
        f"{owner} {count}" for owner, count in sorted(counts.items())
    )


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build the Release 2 technical report.",
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
    print(owner_summary(status))
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
