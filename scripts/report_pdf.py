"""Render a release technical report from maintained Markdown into a navigable PDF.

Each release keeps a thin builder (``build_release0_report.py``, ``build_release1_report.py``)
that supplies a :class:`ReportSpec`. This module owns everything they share: the PDF template,
the small Markdown dialect, Mermaid figure drift checks, the word count and draft checks.

Markdown dialect beyond headings, paragraphs, lists, tables, quotes, code and images:

- ``[[TOC]]`` and ``[[PAGEBREAK]]`` insert the contents page and a page break.
- ``[[TODO: Owner | What is still needed]]`` renders a visible "to complete" callout in draft
  builds. It is excluded from the word count and blocks ``--final``.
- ``<!-- ... -->`` blocks (starting at the beginning of a line) are writing guidance for authors.
  They are never rendered or counted.
- An image whose file does not exist yet renders as a labelled placeholder in draft builds.
- A release may register extra ``[[NAME argument]]`` directives that expand into Markdown lines
  (for example, tables generated from checked-in tool catalogues).
"""

from __future__ import annotations

import hashlib
import html
import json
import re
import shutil
import subprocess
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import override

from PIL import Image
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    BaseDocTemplate,
    CondPageBreak,
    Flowable,
    KeepTogether,
    PageBreak,
    PageTemplate,
    Paragraph,
    Preformatted,
    Spacer,
    Table,
    TableStyle,
)
from reportlab.platypus import (
    Image as RLImage,
)
from reportlab.platypus.frames import Frame
from reportlab.platypus.tableofcontents import TableOfContents

ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = ROOT / "docs" / "reports"
REPOSITORY_URL = "https://github.com/MattShelton04/41026ASDProject"
CONTENT_WIDTH = A4[0] - 40 * mm
MERMAID_VERSION = "11.12.0"
NAVY = colors.HexColor("#153E46")
BLUE = colors.HexColor("#176B75")
PALE_BLUE = colors.HexColor("#EFF6F6")
PALE_GREY = colors.HexColor("#F3F5F7")
MID_GREY = colors.HexColor("#6B7280")
LIGHT_BORDER = colors.HexColor("#D9D9D9")
AMBER = colors.HexColor("#B7791F")
PALE_AMBER = colors.HexColor("#FFF6DD")

TODO_PATTERN = re.compile(r"^\[\[TODO:\s*(?P<owner>[^|\]]+?)\s*\|\s*(?P<text>.+?)\s*\]\]$")
DIRECTIVE_PATTERN = re.compile(r"^\[\[(?P<name>[A-Z_]+)(?:\s+(?P<argument>[^\]]*))?\]\]$")
IMAGE_PATTERN = re.compile(r"!\[([^\]]+)\]\(([^)]+)\)")
COMMIT_SHA_PATTERN = re.compile(r"[0-9a-f]{40}")

Directive = Callable[[str], list[str]]


def default_image_max_height(path: Path) -> float:
    """Keep screenshots and ERDs compact; let architecture figures use most of a page."""
    if path.stem.endswith("-erd") or "screenshots" in path.parts or "readme" in path.parts:
        return 100 * mm
    return 185 * mm


@dataclass(frozen=True)
class ReportSpec:
    """Everything that differs between two release reports."""

    release_label: str
    footer_title: str
    pdf_title: str
    pdf_subject: str
    asset_dir: Path
    diagram_dir: Path
    diagram_pairs: Mapping[str, str]
    image_max_height: Callable[[Path], float] = default_image_max_height
    directives: Mapping[str, Directive] = field(default_factory=dict)
    word_limit: int | None = None
    section_word_budgets: Mapping[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class Todo:
    line: int
    owner: str
    text: str


@dataclass(frozen=True)
class WordCount:
    total: int
    sections: tuple[tuple[str, int], ...]


@dataclass(frozen=True)
class ReportStatus:
    """Draft readiness: what is unfinished and how long the counted body is."""

    todos: tuple[Todo, ...]
    missing_images: tuple[str, ...]
    words: WordCount

    def final_blockers(self, spec: ReportSpec, baseline: str) -> list[str]:
        blockers = [f"line {todo.line}: TODO for {todo.owner}" for todo in self.todos]
        blockers += [f"missing image {path}" for path in self.missing_images]
        if spec.word_limit is not None and self.words.total > spec.word_limit:
            blockers.append(f"{self.words.total} counted words exceed {spec.word_limit}")
        if not COMMIT_SHA_PATTERN.fullmatch(baseline):
            blockers.append(f"baseline {baseline!r} is not a full commit SHA")
        return blockers


class ReportDocTemplate(BaseDocTemplate):
    """Document template with bookmarks and a generated table of contents."""

    def __init__(self, filename: str, spec: ReportSpec, **kwargs: object) -> None:
        super().__init__(filename, **kwargs)
        self._spec = spec
        frame = Frame(
            self.leftMargin,
            self.bottomMargin,
            self.width,
            self.height,
            id="normal",
            leftPadding=0,
            rightPadding=0,
            topPadding=0,
            bottomPadding=0,
        )
        self.addPageTemplates(PageTemplate(id="report", frames=frame, onPage=self._page))
        self._heading_index = 0

    @override
    def beforeDocument(self) -> None:
        self._heading_index = 0

    def _page(self, canvas: object, doc: object) -> None:
        page_number = getattr(doc, "page", 1)
        canvas.saveState()
        if page_number == 1:
            canvas.setFillColor(NAVY)
            canvas.rect(0, A4[1] - 18 * mm, A4[0], 18 * mm, fill=1, stroke=0)
            canvas.setFillColor(colors.white)
            canvas.setFont("Helvetica-Bold", 9)
            canvas.drawString(self.leftMargin, A4[1] - 11 * mm, "PROPERTYSCOPE NSW  /  GROUP 20")
        else:
            canvas.setFont("Helvetica", 8)
            canvas.setFillColor(MID_GREY)
            canvas.drawString(
                self.leftMargin, A4[1] - 13 * mm, "41026  /  ADVANCED SOFTWARE DEVELOPMENT"
            )
            canvas.drawRightString(
                A4[0] - self.rightMargin, A4[1] - 13 * mm, self._spec.release_label
            )
        canvas.setStrokeColor(LIGHT_BORDER)
        canvas.setLineWidth(0.4)
        canvas.line(self.leftMargin, 15 * mm, A4[0] - self.rightMargin, 15 * mm)
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(MID_GREY)
        canvas.drawString(self.leftMargin, 10 * mm, self._spec.footer_title)
        canvas.drawRightString(A4[0] - self.rightMargin, 10 * mm, str(page_number))
        canvas.restoreState()

    @override
    def afterFlowable(self, flowable: Flowable) -> None:
        if not isinstance(flowable, Paragraph):
            return
        level = getattr(flowable, "_heading_level", None)
        if level is None:
            return
        text = flowable.getPlainText()
        key = f"heading-{self._heading_index}"
        self._heading_index += 1
        self.canv.bookmarkPage(key)
        self.canv.addOutlineEntry(text, key, level=level, closed=level > 0)
        if level == 0:
            self.notify("TOCEntry", (level, text, self.page, key))


class ReportContents(TableOfContents):
    """Compact linked chapter index; detailed navigation remains in PDF bookmarks."""

    @override
    def wrap(self, availWidth: float, availHeight: float) -> tuple[float, float]:
        styles = _styles()
        label_style = ParagraphStyle(
            "ContentsLabel",
            parent=styles["body"],
            fontSize=11,
            leading=15,
            textColor=NAVY,
            spaceAfter=0,
        )
        page_style = ParagraphStyle(
            "ContentsPage", parent=label_style, alignment=TA_RIGHT, fontName="Helvetica-Bold"
        )
        entries = self._lastEntries or [(0, "Building contents", 0, None)]
        rows = []
        for _, title, page, key in entries:
            label = html.escape(title)
            number = str(page)
            if key:
                label = f'<link href="#{key}">{label}</link>'
                number = f'<link href="#{key}">{number}</link>'
            rows.append([Paragraph(label, label_style), Paragraph(number, page_style)])
        self._table = Table(
            rows,
            colWidths=[availWidth - 16 * mm, 16 * mm],
            style=TableStyle(
                [
                    ("LINEBELOW", (0, 0), (-1, -1), 0.4, LIGHT_BORDER),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 0),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                    ("TOPPADDING", (0, 0), (-1, -1), 10),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
                ]
            ),
        )
        self.width, self.height = self._table.wrapOn(self.canv, availWidth, availHeight)
        return self.width, self.height


def diagram_fingerprint(source: Path, asset: Path) -> dict[str, str]:
    return {
        "source_sha256": hashlib.sha256(
            source.read_text(encoding="utf-8").encode("utf-8")
        ).hexdigest(),
        "asset_sha256": hashlib.sha256(asset.read_bytes()).hexdigest(),
    }


def render_diagrams(spec: ReportSpec) -> None:
    """Render pinned Mermaid sources and record hashes to detect stale derivatives."""
    npx = shutil.which("npx.cmd") or shutil.which("npx")
    if not npx:
        raise RuntimeError("Node.js and npx are required for --render-diagrams")
    spec.asset_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = spec.asset_dir / "manifest.json"
    previous = (
        json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    )
    manifest = {}
    for source_name, asset_name in spec.diagram_pairs.items():
        source, asset = spec.diagram_dir / source_name, spec.asset_dir / asset_name
        if (
            previous.get("mermaid_version") == MERMAID_VERSION
            and source.exists()
            and asset.exists()
            and previous.get("diagrams", {}).get(source_name) == diagram_fingerprint(source, asset)
        ):
            manifest[source_name] = diagram_fingerprint(source, asset)
            continue
        subprocess.run(
            [
                npx,
                "--yes",
                f"@mermaid-js/mermaid-cli@{MERMAID_VERSION}",
                "-i",
                str(source),
                "-o",
                str(asset),
                "-b",
                "white",
                "-w",
                "1800",
                "-s",
                "2",
            ],
            check=True,
        )
        manifest[source_name] = diagram_fingerprint(source, asset)
    manifest_path.write_text(
        json.dumps({"mermaid_version": MERMAID_VERSION, "diagrams": manifest}, indent=2) + "\n",
        encoding="utf-8",
    )


def validate_diagrams(spec: ReportSpec) -> None:
    """Fail before publication if a source or rendered diagram has changed."""
    if not spec.diagram_pairs:
        return
    manifest = json.loads((spec.asset_dir / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("mermaid_version") != MERMAID_VERSION:
        raise ValueError("Mermaid version changed; run --render-diagrams")
    for source_name, asset_name in spec.diagram_pairs.items():
        source, asset = spec.diagram_dir / source_name, spec.asset_dir / asset_name
        if not asset.exists() or manifest["diagrams"].get(source_name) != diagram_fingerprint(
            source, asset
        ):
            raise ValueError(f"Stale diagram {source_name}; run --render-diagrams")


def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    styles: dict[str, ParagraphStyle] = {}
    styles["title"] = ParagraphStyle(
        "ReportTitle",
        parent=base["Title"],
        fontName="Helvetica-Bold",
        fontSize=34,
        leading=39,
        textColor=NAVY,
        alignment=TA_LEFT,
        spaceAfter=10 * mm,
    )
    styles["subtitle"] = ParagraphStyle(
        "ReportSubtitle",
        parent=base["Normal"],
        fontName="Helvetica",
        fontSize=12,
        leading=17,
        textColor=NAVY,
        spaceAfter=5 * mm,
    )
    styles["h1"] = ParagraphStyle(
        "HeadingOne",
        parent=base["Heading1"],
        fontName="Helvetica-Bold",
        fontSize=18,
        leading=22,
        textColor=NAVY,
        spaceBefore=7 * mm,
        spaceAfter=4 * mm,
        keepWithNext=True,
    )
    styles["h2"] = ParagraphStyle(
        "HeadingTwo",
        parent=base["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=13.5,
        leading=17,
        textColor=NAVY,
        spaceBefore=5 * mm,
        spaceAfter=2.5 * mm,
        keepWithNext=True,
    )
    styles["h3"] = ParagraphStyle(
        "HeadingThree",
        parent=base["Heading3"],
        fontName="Helvetica-Bold",
        fontSize=11,
        leading=14,
        textColor=NAVY,
        spaceBefore=3.5 * mm,
        spaceAfter=1.5 * mm,
        keepWithNext=True,
    )
    styles["body"] = ParagraphStyle(
        "Body",
        parent=base["BodyText"],
        fontName="Helvetica",
        fontSize=9.5,
        leading=13.2,
        textColor=colors.HexColor("#222222"),
        spaceAfter=2.5 * mm,
        allowWidows=0,
        allowOrphans=0,
    )
    styles["small"] = ParagraphStyle(
        "Small",
        parent=styles["body"],
        fontSize=8,
        leading=10.5,
    )
    styles["bullet"] = ParagraphStyle(
        "Bullet",
        parent=styles["body"],
        leftIndent=6 * mm,
        firstLineIndent=-3.5 * mm,
        spaceAfter=1.5 * mm,
    )
    styles["caption"] = ParagraphStyle(
        "Caption",
        parent=styles["small"],
        alignment=TA_LEFT,
        textColor=MID_GREY,
        spaceBefore=1.5 * mm,
        spaceAfter=4 * mm,
    )
    styles["quote"] = ParagraphStyle(
        "Quote",
        parent=styles["body"],
        leftIndent=7 * mm,
        rightIndent=4 * mm,
        textColor=colors.HexColor("#404040"),
        borderColor=colors.HexColor("#AFC4D6"),
        borderWidth=0,
        borderPadding=(0, 0, 0, 8),
    )
    styles["code"] = ParagraphStyle(
        "Code",
        parent=base["Code"],
        fontName="Courier",
        fontSize=7.2,
        leading=10,
        leftIndent=4 * mm,
        rightIndent=4 * mm,
        spaceBefore=1.5 * mm,
        spaceAfter=3 * mm,
        backColor=PALE_GREY,
    )
    return styles


def resolve_link(target: str, source: Path, baseline: str) -> str:
    """Pin repository-relative links to the report's commit reference on GitHub."""
    if target.startswith(("https://", "http://", "mailto:")):
        return target
    target_path = (source.parent / target.split("#", 1)[0]).resolve()
    try:
        rel = target_path.relative_to(ROOT).as_posix()
    except ValueError:
        return target
    fragment = "#" + target.split("#", 1)[1] if "#" in target else ""
    kind = "tree" if target_path.is_dir() else "blob"
    return f"{REPOSITORY_URL}/{kind}/{baseline}/{rel}{fragment}"


def _inline(text: str, source: Path, baseline: str) -> str:
    escaped = html.escape(text, quote=False)
    escaped = re.sub(r"`([^`]+)`", r"<font name='Courier'>\1</font>", escaped)
    escaped = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", escaped)
    escaped = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<i>\1</i>", escaped)

    def replace_link(match: re.Match[str]) -> str:
        label, target = match.group(1), html.unescape(match.group(2))
        resolved = html.escape(resolve_link(target, source, baseline), quote=True)
        return f'<link href="{resolved}" color="#176B75"><u>{label}</u></link>'

    return re.sub(r"\[([^\]]+)\]\(([^)]+)\)", replace_link, escaped)


def _table(
    rows: list[list[str]], styles: dict[str, ParagraphStyle], source: Path, baseline: str
) -> Table:
    if not rows:
        return Table([])
    cols = max(len(row) for row in rows)
    normalised = [row + [""] * (cols - len(row)) for row in rows]
    weights: list[float] = []
    for col in range(cols):
        lengths = [
            min(max(len(re.sub(r"\[([^]]+)\]\([^)]+\)", r"\1", row[col])), 5), 80)
            for row in normalised
        ]
        weights.append(max(25.0, sum(lengths) / len(lengths)))
    total = sum(weights)
    available = CONTENT_WIDTH
    widths = [available * weight / total for weight in weights]
    cell_style = ParagraphStyle(
        "TableCell", parent=styles["small"], fontSize=8.1, leading=10.5, spaceAfter=0
    )
    header_style = ParagraphStyle(
        "TableHeader", parent=cell_style, fontName="Helvetica-Bold", textColor=colors.white
    )
    data: list[list[Paragraph]] = []
    for index, row in enumerate(normalised):
        style = header_style if index == 0 else cell_style
        data.append([Paragraph(_inline(value.strip(), source, baseline), style) for value in row])
    table = Table(data, colWidths=widths, repeatRows=1, hAlign="LEFT", splitByRow=1)
    commands: list[tuple[object, ...]] = [
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("LINEBELOW", (0, 0), (-1, -1), 0.35, LIGHT_BORDER),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]
    for row in range(1, len(data)):
        if row % 2 == 0:
            commands.append(("BACKGROUND", (0, row), (-1, row), PALE_BLUE))
    table.setStyle(TableStyle(commands))
    return table


def _callout(heading: str, text: str, styles: dict[str, ParagraphStyle]) -> Table:
    label = ParagraphStyle("CalloutLabel", parent=styles["small"], textColor=AMBER, spaceAfter=1)
    body = ParagraphStyle("CalloutBody", parent=styles["small"], spaceAfter=0)
    table = Table(
        [[[Paragraph(f"<b>{html.escape(heading)}</b>", label), Paragraph(text, body)]]],
        colWidths=[CONTENT_WIDTH],
        hAlign="LEFT",
    )
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), PALE_AMBER),
                ("LINEBEFORE", (0, 0), (0, -1), 2.5, AMBER),
                ("LEFTPADDING", (0, 0), (-1, -1), 7),
                ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    return table


def _image_flowable(
    path: Path, caption: str, styles: dict[str, ParagraphStyle], spec: ReportSpec
) -> list[Flowable]:
    if not path.exists():
        try:
            shown = path.relative_to(ROOT).as_posix()
        except ValueError:
            shown = path.as_posix()
        placeholder = _callout(
            "IMAGE PENDING",
            f"{html.escape(caption)}<br/><font name='Courier'>{html.escape(shown)}</font>",
            styles,
        )
        return [KeepTogether([placeholder, Spacer(1, 4 * mm)])]
    with Image.open(path) as image:
        width_px, height_px = image.size
    max_width = CONTENT_WIDTH
    max_height = spec.image_max_height(path)
    scale = min(max_width / width_px, max_height / height_px)
    rendered = RLImage(str(path), width=width_px * scale, height=height_px * scale)
    return [KeepTogether([rendered, Paragraph(html.escape(caption), styles["caption"])])]


def source_lines(source: Path, spec: ReportSpec) -> list[str]:
    """Return renderable lines: guidance comments removed and release directives expanded."""
    lines: list[str] = []
    in_comment = in_code = False
    for line in source.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if line.startswith("```"):
            in_code = not in_code
        if in_code or line.startswith("```"):
            lines.append(line)
            continue
        if in_comment:
            in_comment = "-->" not in stripped
            continue
        if stripped.startswith("<!--"):
            in_comment = "-->" not in stripped
            continue
        directive = DIRECTIVE_PATTERN.fullmatch(stripped)
        if directive and directive.group("name") in spec.directives:
            lines.extend(
                spec.directives[directive.group("name")](directive.group("argument") or "")
            )
            continue
        lines.append(line)
    return lines


def parse_markdown(source: Path, baseline: str, spec: ReportSpec) -> list[Flowable]:
    styles = _styles()
    lines = source_lines(source, spec)
    story: list[Flowable] = []
    paragraph_lines: list[str] = []
    list_items: list[str] = []
    list_ordered = False
    table_rows: list[list[str]] = []
    code_lines: list[str] = []
    in_code = False

    def flush_paragraph() -> None:
        if paragraph_lines:
            text = " ".join(line.strip() for line in paragraph_lines)
            story.append(Paragraph(_inline(text, source, baseline), styles["body"]))
            paragraph_lines.clear()

    def flush_list() -> None:
        nonlocal list_ordered
        if list_items:
            for index, item in enumerate(list_items, start=1):
                marker = f"{index}." if list_ordered else "-"
                story.append(
                    Paragraph(f"{marker} {_inline(item, source, baseline)}", styles["bullet"])
                )
            list_items.clear()
            list_ordered = False

    def flush_table() -> None:
        if table_rows:
            rows = [
                row
                for index, row in enumerate(table_rows)
                if not (
                    index == 1 and all(re.fullmatch(r":?-{3,}:?", cell.strip()) for cell in row)
                )
            ]
            story.append(_table(rows, styles, source, baseline))
            story.append(Spacer(1, 3 * mm))
            table_rows.clear()

    def flush_code() -> None:
        if code_lines:
            story.append(Preformatted("\n".join(code_lines), styles["code"], maxLineLength=100))
            code_lines.clear()

    def flush_all() -> None:
        flush_paragraph()
        flush_list()
        flush_table()

    for line in lines:
        if line.startswith("```"):
            if in_code:
                in_code = False
                flush_code()
            else:
                flush_all()
                in_code = True
            continue
        if in_code:
            code_lines.append(line)
            continue
        if line.strip() == "[[TOC]]":
            flush_all()
            story.extend(
                [
                    Paragraph("Contents", styles["h1"]),
                    Paragraph(
                        "Select a chapter or page number to navigate. "
                        "PDF bookmarks include every subsection.",
                        styles["small"],
                    ),
                    Spacer(1, 5 * mm),
                    ReportContents(),
                    PageBreak(),
                ]
            )
            continue
        if line.strip() == "[[PAGEBREAK]]":
            flush_all()
            story.append(PageBreak())
            continue
        todo = TODO_PATTERN.fullmatch(line.strip())
        if todo:
            flush_all()
            story.append(
                _callout(
                    f"TO COMPLETE / {todo.group('owner').upper()}",
                    _inline(todo.group("text"), source, baseline),
                    styles,
                )
            )
            story.append(Spacer(1, 3 * mm))
            continue
        image_match = IMAGE_PATTERN.fullmatch(line.strip())
        if image_match:
            flush_all()
            image_path = (source.parent / image_match.group(2)).resolve()
            story.extend(_image_flowable(image_path, image_match.group(1), styles, spec))
            continue
        heading = re.match(r"^(#{1,4})\s+(.+)$", line)
        if heading:
            flush_all()
            level = len(heading.group(1))
            title = heading.group(2).strip()
            if level == 1 and not story:
                story.append(Spacer(1, 20 * mm))
                story.append(Paragraph(_inline(title, source, baseline), styles["title"]))
            else:
                if level == 2:
                    story.append(CondPageBreak(70 * mm))
                paragraph = Paragraph(
                    _inline(title, source, baseline), styles[f"h{min(max(level - 1, 1), 3)}"]
                )
                paragraph._heading_level = max(0, level - 2)  # type: ignore[attr-defined]
                story.append(paragraph)
            continue
        if re.match(r"^\s*\|.*\|\s*$", line):
            flush_paragraph()
            flush_list()
            table_rows.append([cell.strip() for cell in line.strip().strip("|").split("|")])
            continue
        bullet = re.match(r"^\s*[-*]\s+(.+)$", line)
        numbered = re.match(r"^\s*\d+[.)]\s+(.+)$", line)
        if bullet or numbered:
            flush_paragraph()
            flush_table()
            if not list_items:
                list_ordered = bool(numbered)
            list_items.append((bullet or numbered).group(1))  # type: ignore[union-attr]
            continue
        if line.startswith("> "):
            flush_all()
            story.append(Paragraph(_inline(line[2:], source, baseline), styles["quote"]))
            continue
        if not line.strip():
            flush_all()
            continue
        if line.startswith("**") and line.endswith("**") and len(story) < 12:
            flush_all()
            story.append(Paragraph(_inline(line, source, baseline), styles["subtitle"]))
            continue
        paragraph_lines.append(line)

    flush_all()
    flush_code()
    return story


def _plain_words(text: str) -> int:
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"[`*]", "", text)
    return sum(1 for token in text.split() if re.search(r"[A-Za-z0-9]", token))


def count_words(source: Path, spec: ReportSpec) -> WordCount:
    """Count the assessed body: chapter headings, prose, lists and tables.

    Excluded: the cover (everything before the first ``##`` chapter), contents, figures and
    captions, fenced code (captured terminal output), TODO callouts, guidance comments and
    every chapter from the first ``## Appendix`` heading onwards.
    """
    sections: list[tuple[str, int]] = []
    in_code = False
    counting = False
    for line in source_lines(source, spec):
        if line.startswith("```"):
            in_code = not in_code
            continue
        stripped = line.strip()
        chapter = re.match(r"^##\s+(.+)$", line)
        if chapter and not in_code:
            if chapter.group(1).lower().startswith("appendix"):
                break
            counting = True
            sections.append((chapter.group(1).strip(), 0))
        if in_code or not counting or not stripped:
            continue
        if stripped.startswith("[[") or IMAGE_PATTERN.fullmatch(stripped):
            continue
        if re.fullmatch(r"\|?(\s*:?-{3,}:?\s*\|)+\s*:?-*:?\s*", stripped):
            continue
        text = re.sub(r"^#{1,4}\s+|^\s*(?:[-*]|\d+[.)])\s+|^>\s+", "", stripped)
        title, words = sections[-1]
        sections[-1] = (title, words + _plain_words(text.replace("|", " ")))
    return WordCount(total=sum(words for _, words in sections), sections=tuple(sections))


def find_todos(source: Path) -> tuple[Todo, ...]:
    todos = []
    for number, line in enumerate(source.read_text(encoding="utf-8").splitlines(), start=1):
        match = TODO_PATTERN.fullmatch(line.strip())
        if match:
            todos.append(Todo(number, match.group("owner"), match.group("text")))
    return tuple(todos)


def review(source: Path, spec: ReportSpec) -> ReportStatus:
    missing = []
    for line in source_lines(source, spec):
        match = IMAGE_PATTERN.fullmatch(line.strip())
        if match and not (source.parent / match.group(2)).resolve().exists():
            missing.append(match.group(2))
    return ReportStatus(
        todos=find_todos(source),
        missing_images=tuple(missing),
        words=count_words(source, spec),
    )


def format_status(status: ReportStatus, spec: ReportSpec) -> str:
    """Summarise the word budget and outstanding work for the terminal."""
    lines = ["Counted words by chapter (cover, figures, code and appendices excluded):"]
    for title, words in status.words.sections:
        budget = next(
            (
                value
                for prefix, value in spec.section_word_budgets.items()
                if title.startswith(prefix)
            ),
            None,
        )
        marker = f" / {budget}" + (" OVER" if words > budget else "") if budget else ""
        lines.append(f"  {words:>5}{marker:<12} {title}")
    limit = f" of {spec.word_limit}" if spec.word_limit else ""
    lines.append(f"  {status.words.total:>5}{limit} total")
    if status.todos:
        lines.append(f"Outstanding TODOs ({len(status.todos)}):")
        lines += [f"  line {todo.line:>4}  {todo.owner}: {todo.text}" for todo in status.todos]
    if status.missing_images:
        lines.append(f"Pending images ({len(status.missing_images)}):")
        lines += [f"  {path}" for path in status.missing_images]
    return "\n".join(lines)


def build(source: Path, output: Path, baseline: str, spec: ReportSpec) -> None:
    validate_diagrams(spec)
    output.parent.mkdir(parents=True, exist_ok=True)
    document = ReportDocTemplate(
        str(output),
        spec,
        pagesize=A4,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        topMargin=23 * mm,
        bottomMargin=22 * mm,
        title=spec.pdf_title,
        author="Group 20",
        subject=spec.pdf_subject,
        invariant=True,
    )
    story = parse_markdown(source, baseline, spec)
    document.multiBuild(story)
