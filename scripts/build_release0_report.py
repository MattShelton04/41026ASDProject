"""Build the Release 0 submission PDF from its maintained Markdown source."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import shutil
import subprocess
from collections.abc import Iterable
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
ASSET_DIR = REPORT_DIR / "assets" / "release-0"
CONTENT_WIDTH = A4[0] - 40 * mm
DIAGRAM_DIR = REPORT_DIR / "diagrams" / "release-0"
MERMAID_VERSION = "11.12.0"
NAVY = colors.HexColor("#153E46")
BLUE = colors.HexColor("#176B75")
PALE_BLUE = colors.HexColor("#EFF6F6")
PALE_GREY = colors.HexColor("#F3F5F7")
MID_GREY = colors.HexColor("#6B7280")
LIGHT_BORDER = colors.HexColor("#D9D9D9")


class ReportDocTemplate(BaseDocTemplate):
    """Document template with bookmarks and a generated table of contents."""

    def __init__(self, filename: str, **kwargs: object) -> None:
        super().__init__(filename, **kwargs)
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
            canvas.drawRightString(A4[0] - self.rightMargin, A4[1] - 13 * mm, "RELEASE 0")
        canvas.setStrokeColor(LIGHT_BORDER)
        canvas.setLineWidth(0.4)
        canvas.line(self.leftMargin, 15 * mm, A4[0] - self.rightMargin, 15 * mm)
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(MID_GREY)
        canvas.drawString(
            self.leftMargin, 10 * mm, "PropertyScope NSW  |  Release 0 Technical Report"
        )
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


def _diagram_pairs() -> dict[str, str]:
    return {
        "feature-1-runtime.mmd": "individual-boundaries.png",
        **{f"feature-{i}-runtime.mmd": f"feature-{i}-runtime.png" for i in range(2, 6)},
        **{f"feature-{i}-erd.mmd": f"feature-{i}-erd.png" for i in range(1, 6)},
        **{
            f"{name}.mmd": f"{name}.png"
            for name in (
                "integrated-architecture",
                "compose-topology",
                "agent-loop",
                "devops-pipeline",
            )
        },
    }


def _diagram_fingerprint(source: Path, asset: Path) -> dict[str, str]:
    return {
        "source_sha256": hashlib.sha256(
            source.read_text(encoding="utf-8").encode("utf-8")
        ).hexdigest(),
        "asset_sha256": hashlib.sha256(asset.read_bytes()).hexdigest(),
    }


def render_diagrams() -> None:
    """Render pinned Mermaid sources and record hashes to detect stale derivatives."""
    npx = shutil.which("npx.cmd") or shutil.which("npx")
    if not npx:
        raise RuntimeError("Node.js and npx are required for --render-diagrams")
    ASSET_DIR.mkdir(parents=True, exist_ok=True)
    manifest_path = ASSET_DIR / "manifest.json"
    previous = (
        json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    )
    manifest = {}
    for source_name, asset_name in _diagram_pairs().items():
        source, asset = DIAGRAM_DIR / source_name, ASSET_DIR / asset_name
        if (
            previous.get("mermaid_version") == MERMAID_VERSION
            and source.exists()
            and asset.exists()
            and previous.get("diagrams", {}).get(source_name) == _diagram_fingerprint(source, asset)
        ):
            manifest[source_name] = _diagram_fingerprint(source, asset)
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
        manifest[source_name] = _diagram_fingerprint(source, asset)
    manifest_path.write_text(
        json.dumps({"mermaid_version": MERMAID_VERSION, "diagrams": manifest}, indent=2) + "\n",
        encoding="utf-8",
    )


def _validate_mermaid_diagrams() -> None:
    """Fail before publication if a source or rendered diagram has changed."""
    manifest = json.loads((ASSET_DIR / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("mermaid_version") != MERMAID_VERSION:
        raise ValueError("Mermaid version changed; run --render-diagrams")
    for source_name, asset_name in _diagram_pairs().items():
        source, asset = DIAGRAM_DIR / source_name, ASSET_DIR / asset_name
        if manifest["diagrams"].get(source_name) != _diagram_fingerprint(source, asset):
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


def _resolve_link(target: str, source: Path, baseline: str) -> str:
    if target.startswith(("https://", "http://", "mailto:")):
        return target
    target_path = (source.parent / target.split("#", 1)[0]).resolve()
    try:
        rel = target_path.relative_to(ROOT).as_posix()
    except ValueError:
        return target
    fragment = "#" + target.split("#", 1)[1] if "#" in target else ""
    return f"https://github.com/MattShelton04/41026ASDProject/blob/{baseline}/{rel}{fragment}"


def _inline(text: str, source: Path, baseline: str) -> str:
    escaped = html.escape(text, quote=False)
    escaped = re.sub(r"`([^`]+)`", r"<font name='Courier'>\1</font>", escaped)
    escaped = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", escaped)
    escaped = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<i>\1</i>", escaped)

    def replace_link(match: re.Match[str]) -> str:
        label, target = match.group(1), html.unescape(match.group(2))
        resolved = html.escape(_resolve_link(target, source, baseline), quote=True)
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


def _image_flowable(path: Path, caption: str, styles: dict[str, ParagraphStyle]) -> list[Flowable]:
    with Image.open(path) as image:
        width_px, height_px = image.size
    max_width = CONTENT_WIDTH
    if path.stem.endswith("-erd") or "screenshots" in path.parts or "readme" in path.parts:
        max_height = 100 * mm
    elif path.stem == "compose-topology":
        max_height = 115 * mm
    elif path.stem == "agent-loop":
        max_height = 135 * mm
    else:
        max_height = 185 * mm
    scale = min(max_width / width_px, max_height / height_px)
    rendered = RLImage(str(path), width=width_px * scale, height=height_px * scale)
    return [KeepTogether([rendered, Paragraph(html.escape(caption), styles["caption"])])]


def parse_markdown(source: Path, baseline: str) -> list[Flowable]:
    styles = _styles()
    lines = source.read_text(encoding="utf-8").splitlines()
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

    for line in lines:
        if line.startswith("```"):
            if in_code:
                in_code = False
                flush_code()
            else:
                flush_paragraph()
                flush_list()
                flush_table()
                in_code = True
            continue
        if in_code:
            code_lines.append(line)
            continue
        if line.strip() == "[[TOC]]":
            flush_paragraph()
            flush_list()
            flush_table()
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
            flush_paragraph()
            flush_list()
            flush_table()
            story.append(PageBreak())
            continue
        image_match = re.fullmatch(r"!\[([^\]]+)\]\(([^)]+)\)", line.strip())
        if image_match:
            flush_paragraph()
            flush_list()
            flush_table()
            image_path = (source.parent / image_match.group(2)).resolve()
            story.extend(_image_flowable(image_path, image_match.group(1), styles))
            continue
        heading = re.match(r"^(#{1,4})\s+(.+)$", line)
        if heading:
            flush_paragraph()
            flush_list()
            flush_table()
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
            flush_paragraph()
            flush_list()
            flush_table()
            story.append(Paragraph(_inline(line[2:], source, baseline), styles["quote"]))
            continue
        if not line.strip():
            flush_paragraph()
            flush_list()
            flush_table()
            continue
        if line.startswith("**") and line.endswith("**") and len(story) < 12:
            flush_paragraph()
            flush_list()
            flush_table()
            story.append(Paragraph(_inline(line, source, baseline), styles["subtitle"]))
            continue
        paragraph_lines.append(line)

    flush_paragraph()
    flush_list()
    flush_table()
    flush_code()
    return story


def build(source: Path, output: Path, baseline: str) -> None:
    _validate_mermaid_diagrams()
    output.parent.mkdir(parents=True, exist_ok=True)
    document = ReportDocTemplate(
        str(output),
        pagesize=A4,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        topMargin=23 * mm,
        bottomMargin=22 * mm,
        title="PropertyScope NSW Release 0 Technical Report",
        author="Group 20",
        subject="41026 Advanced Software Development Assessment 1",
        invariant=True,
    )
    story = parse_markdown(source, baseline)
    document.multiBuild(story)


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=REPORT_DIR / "release-0-technical-report.md")
    parser.add_argument("--output", type=Path, default=REPORT_DIR / "group20.pdf")
    parser.add_argument("--baseline", default="7d5350d19023fb1e978e85127a72e3500a1556f3")
    parser.add_argument(
        "--render-diagrams",
        action="store_true",
        help="Refresh Mermaid PNGs and their drift manifest before building",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)
    if args.render_diagrams:
        render_diagrams()
    build(args.source.resolve(), args.output.resolve(), args.baseline)
    print(args.output.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
