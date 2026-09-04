"""Build the Release 0 submission PDF from its maintained Markdown source."""

from __future__ import annotations

import argparse
import html
import re
from collections.abc import Iterable
from pathlib import Path
from typing import override

from PIL import Image, ImageDraw, ImageFont
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    BaseDocTemplate,
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
NAVY = colors.HexColor("#17365D")
BLUE = colors.HexColor("#2F5597")
PALE_BLUE = colors.HexColor("#EAF1F8")
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
        )
        self.addPageTemplates(PageTemplate(id="report", frames=frame, onPage=self._page))
        self._heading_index = 0

    @override
    def beforeDocument(self) -> None:
        self._heading_index = 0

    def _page(self, canvas: object, doc: object) -> None:
        page_number = getattr(doc, "page", 1)
        canvas.saveState()
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
        self.notify("TOCEntry", (level, text, self.page, key))


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        Path("C:/Windows/Fonts/aptos.ttf"),
        Path("C:/Windows/Fonts/arial.ttf"),
    ]
    if bold:
        candidates = [
            Path("C:/Windows/Fonts/aptos-display-bold.ttf"),
            Path("C:/Windows/Fonts/arialbd.ttf"),
        ]
    for candidate in candidates:
        if candidate.exists():
            return ImageFont.truetype(str(candidate), size=size)
    return ImageFont.load_default()


def _rounded_box(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int, int, int],
    text: str,
    *,
    fill: str = "#EAF1F8",
    outline: str = "#8AA4C0",
    font_size: int = 29,
) -> None:
    draw.rounded_rectangle(xy, radius=18, fill=fill, outline=outline, width=3)
    font = _font(font_size, bold=True)
    x1, y1, x2, y2 = xy
    lines = text.split("\n")
    heights = [draw.textbbox((0, 0), line, font=font)[3] for line in lines]
    line_gap = 8
    total_height = sum(heights) + line_gap * (len(lines) - 1)
    y = y1 + (y2 - y1 - total_height) / 2
    for line, height in zip(lines, heights, strict=True):
        bounds = draw.textbbox((0, 0), line, font=font)
        width = bounds[2] - bounds[0]
        draw.text((x1 + (x2 - x1 - width) / 2, y), line, fill="#111827", font=font)
        y += height + line_gap


def _arrow(
    draw: ImageDraw.ImageDraw,
    start: tuple[int, int],
    end: tuple[int, int],
    *,
    fill: str = "#2F5597",
    width: int = 6,
) -> None:
    draw.line((start, end), fill=fill, width=width)
    x1, y1 = start
    x2, y2 = end
    if abs(x2 - x1) >= abs(y2 - y1):
        direction = 1 if x2 > x1 else -1
        points = [(x2, y2), (x2 - direction * 20, y2 - 13), (x2 - direction * 20, y2 + 13)]
    else:
        direction = 1 if y2 > y1 else -1
        points = [(x2, y2), (x2 - 13, y2 - direction * 20), (x2 + 13, y2 - direction * 20)]
    draw.polygon(points, fill=fill)


def _canvas(
    title: str, size: tuple[int, int] = (1800, 1050)
) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    image = Image.new("RGB", size, "white")
    draw = ImageDraw.Draw(image)
    draw.text((60, 35), title, fill="#111827", font=_font(44, bold=True))
    draw.line((60, 100, size[0] - 60, 100), fill="#D9D9D9", width=3)
    return image, draw


def _save(image: Image.Image, name: str) -> None:
    ASSET_DIR.mkdir(parents=True, exist_ok=True)
    image.save(ASSET_DIR / name, optimize=True)


def build_diagrams() -> None:
    """Create readable report-sized architecture figures."""
    image, draw = _canvas("Integrated Release 0 architecture")
    _rounded_box(draw, (65, 430, 270, 600), "User\nbrowser", fill="#F3F5F7")
    _rounded_box(
        draw, (345, 400, 650, 630), "Shared frontend\nHTMX entry and\nreverse proxy", fill="#DCE6F1"
    )
    _arrow(draw, (270, 515), (345, 515))
    lane_y = [155, 325, 495, 665, 835]
    feature_names = [
        "F1 Data platform",
        "F2 Market cases",
        "F3 Suburb analytics",
        "F4 Due diligence",
        "F5 Buyer journey",
    ]
    for y, label in zip(lane_y, feature_names, strict=True):
        _rounded_box(draw, (745, y, 990, y + 110), f"{label}\nfrontend", font_size=24)
        _rounded_box(draw, (1080, y, 1325, y + 110), "Backend API", font_size=25)
        _rounded_box(
            draw,
            (1415, y, 1725, y + 110),
            "Database API\nand owned store",
            fill="#F3F5F7",
            font_size=24,
        )
        _arrow(draw, (650, 515), (745, y + 55))
        _arrow(draw, (990, y + 55), (1080, y + 55))
        _arrow(draw, (1325, y + 55), (1415, y + 55))
    _rounded_box(draw, (1030, 925, 1375, 1025), "Shared AI mode", fill="#D9EAD3", font_size=28)
    _rounded_box(
        draw,
        (1480, 925, 1725, 1025),
        "Approved remote\nmodel profile",
        fill="#FFF2CC",
        font_size=23,
    )
    _arrow(draw, (1375, 975), (1480, 975))
    for y in lane_y:
        draw.line((1200, y + 110, 1200, 925), fill="#76933C", width=3)
    _save(image, "integrated-architecture.png")

    image, draw = _canvas("Individual feature service boundaries")
    labels = [
        ("Student 1", "Frontend", "Backend + runner", "DB API + loader", "PostgreSQL/PostGIS"),
        ("Student 2", "Frontend", "Backend API", "DB API", "SQLite"),
        ("Student 3", "Frontend", "Backend API", "DB API", "SQLite"),
        ("Student 4", "Frontend", "Backend API", "DB API", "PostgreSQL/PostGIS"),
        ("Student 5", "Frontend", "Backend API", "DB API", "SQLite"),
    ]
    for i, row in enumerate(labels):
        y = 145 + i * 170
        draw.text((65, y + 40), row[0], fill="#17365D", font=_font(29, bold=True))
        xs = [280, 610, 940, 1270]
        widths = [250, 260, 260, 430]
        for x, width, value in zip(xs, widths, row[1:], strict=True):
            fill = (
                "#FFF2CC" if row[0] == "Student 4" and value == "PostgreSQL/PostGIS" else "#EAF1F8"
            )
            _rounded_box(draw, (x, y, x + width, y + 115), value, fill=fill, font_size=24)
        for left, right in zip(
            [(530, y + 58), (870, y + 58), (1200, y + 58)],
            [(610, y + 58), (940, y + 58), (1270, y + 58)],
            strict=True,
        ):
            _arrow(draw, left, right, width=4)
    draw.text(
        (1270, 1010),
        "Yellow marks the recorded SQLite requirement deviation",
        fill="#6B7280",
        font=_font(20),
    )
    _save(image, "individual-boundaries.png")

    image, draw = _canvas("Docker Compose release profile")
    groups = [
        ("Shared", "shared-frontend\nshared-ai-mode", (75, 180, 500, 450), "#DCE6F1"),
        (
            "Feature 1",
            "frontend  backend  runner\ndb-api  db-loader  postgres",
            (560, 150, 1180, 440),
            "#EAF1F8",
        ),
        (
            "Feature 2",
            "frontend  backend  db-api\nSQLite volume",
            (1250, 150, 1740, 440),
            "#EAF1F8",
        ),
        ("Feature 3", "frontend  backend  database\nSQLite volume", (75, 580, 565, 870), "#EAF1F8"),
        (
            "Feature 4",
            "frontend  backend  db-api\nPostgreSQL/PostGIS",
            (635, 580, 1125, 870),
            "#FFF2CC",
        ),
        (
            "Feature 5",
            "frontend  backend  db-api\nSQLite volume",
            (1195, 580, 1685, 870),
            "#EAF1F8",
        ),
    ]
    for name, body, xy, fill in groups:
        draw.rounded_rectangle(xy, radius=24, fill=fill, outline="#8AA4C0", width=4)
        x1, y1, _, _ = xy
        draw.text((x1 + 25, y1 + 22), name, fill="#17365D", font=_font(31, bold=True))
        draw.multiline_text((x1 + 25, y1 + 95), body, fill="#111827", font=_font(25), spacing=16)
    draw.text(
        (75, 950),
        "21 services  |  7 named volumes  |  one generated release-0 profile",
        fill="#111827",
        font=_font(30, bold=True),
    )
    _save(image, "compose-topology.png")

    image, draw = _canvas("DevOps pipeline and retained evidence")
    boxes = [
        (80, 380, 340, 570, "Branch and\npull request"),
        (430, 220, 760, 410, "Integration CI\ncanonical gate"),
        (430, 560, 760, 750, "Student 1 to 5\npath filtered CI"),
        (850, 220, 1190, 410, "Format lint types\ncontracts and tests"),
        (850, 560, 1190, 750, "Build containers\nstart fixture stack"),
        (1280, 380, 1710, 570, "Health seed CRUD\nand boundary smoke"),
    ]
    for x1, y1, x2, y2, label in boxes:
        _rounded_box(draw, (x1, y1, x2, y2), label, fill="#EAF1F8", font_size=29)
    for start, end in [
        ((340, 475), (430, 315)),
        ((340, 475), (430, 655)),
        ((760, 315), (850, 315)),
        ((760, 655), (850, 655)),
        ((1190, 315), (1280, 475)),
        ((1190, 655), (1280, 475)),
    ]:
        _arrow(draw, start, end)
    draw.text(
        (430, 835),
        "All six latest successful run URLs and SHAs are retained in Section 7",
        fill="#6B7280",
        font=_font(26),
    )
    _save(image, "devops-pipeline.png")

    image, draw = _canvas("Plan Act Observe Adapt workflow")
    positions = {
        "Plan": (185, 350, 520, 570),
        "Act": (725, 155, 1060, 375),
        "Observe": (1270, 350, 1660, 570),
        "Adapt": (725, 690, 1060, 910),
    }
    subtitles = {
        "Plan": "select bounded\nread-only tools",
        "Act": "validate and call\nfeature HTTP API",
        "Observe": "record result\nand evidence",
        "Adapt": "finish retry or\nrequest review",
    }
    for name, xy in positions.items():
        _rounded_box(draw, xy, f"{name}\n{subtitles[name]}", fill="#EAF1F8", font_size=28)
    _arrow(draw, (520, 430), (725, 290))
    _arrow(draw, (1060, 290), (1270, 430))
    _arrow(draw, (1470, 570), (1060, 780))
    _arrow(draw, (725, 780), (350, 570))
    _rounded_box(
        draw,
        (1270, 745, 1660, 910),
        "Succeeded failed\nor review required",
        fill="#D9EAD3",
        font_size=25,
    )
    _arrow(draw, (1060, 800), (1270, 825))
    draw.text(
        (600, 980),
        "Durable run events retain phase status prompt version tool evidence "
        "timing and safe outcome",
        fill="#6B7280",
        font=_font(23),
    )
    _save(image, "agent-loop.png")

    image, draw = _canvas("Release 0 data models")
    panels = [
        (
            "F1 Data platform",
            "Sources -> runs -> artifacts -> releases\n"
            "Properties -> identifiers -> coverage\n"
            "Warehouses -> accepted generations",
        ),
        (
            "F2 Market cases",
            "Market case 1 -> many sale observations\nFilters and summary remain deterministic",
        ),
        (
            "F3 Suburb analytics",
            "Suburb -> indicators and amenities\nOverview + user saved suburbs",
        ),
        (
            "F4 Due diligence",
            "Site review 1 -> many constraints\nSite review 1 -> many building records",
        ),
        (
            "F5 Buyer journey",
            "Buyer case 1 -> shortlist properties\nBuyer case 1 -> notes and tasks",
        ),
    ]
    for i, (name, body) in enumerate(panels):
        col = i % 2
        row = i // 2
        x1 = 80 + col * 860
        y1 = 145 + row * 290
        x2 = x1 + (780 if i < 4 else 1640)
        y2 = y1 + 220
        draw.rounded_rectangle(
            (x1, y1, x2, y2), radius=22, fill="#F8FAFC", outline="#8AA4C0", width=3
        )
        draw.text((x1 + 28, y1 + 22), name, fill="#17365D", font=_font(29, bold=True))
        draw.multiline_text((x1 + 28, y1 + 85), body, fill="#111827", font=_font(24), spacing=14)
    _save(image, "data-models.png")


def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    styles: dict[str, ParagraphStyle] = {}
    styles["title"] = ParagraphStyle(
        "ReportTitle",
        parent=base["Title"],
        fontName="Helvetica-Bold",
        fontSize=27,
        leading=32,
        textColor=colors.black,
        alignment=TA_LEFT,
        spaceAfter=10 * mm,
    )
    styles["subtitle"] = ParagraphStyle(
        "ReportSubtitle",
        parent=base["Normal"],
        fontName="Helvetica",
        fontSize=15,
        leading=20,
        textColor=NAVY,
        spaceAfter=5 * mm,
    )
    styles["h1"] = ParagraphStyle(
        "HeadingOne",
        parent=base["Heading1"],
        fontName="Helvetica-Bold",
        fontSize=18,
        leading=22,
        textColor=colors.black,
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
        textColor=colors.black,
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
        textColor=colors.black,
        spaceBefore=3.5 * mm,
        spaceAfter=1.5 * mm,
        keepWithNext=True,
    )
    styles["body"] = ParagraphStyle(
        "Body",
        parent=base["BodyText"],
        fontName="Helvetica",
        fontSize=9.4,
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
        alignment=TA_CENTER,
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
        fontSize=7.5,
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
    return f"https://github.com/MattShelton04/41026ASDProject/blob/{baseline}/{rel}"


def _inline(text: str, source: Path, baseline: str) -> str:
    escaped = html.escape(text, quote=False)
    escaped = re.sub(r"`([^`]+)`", r"<font name='Courier'>\1</font>", escaped)
    escaped = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", escaped)
    escaped = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<i>\1</i>", escaped)

    def replace_link(match: re.Match[str]) -> str:
        label, target = match.group(1), html.unescape(match.group(2))
        resolved = html.escape(_resolve_link(target, source, baseline), quote=True)
        return f'<link href="{resolved}" color="#2F5597"><u>{label}</u></link>'

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
        lengths = [min(max(len(re.sub(r"[*`\[\]]", "", row[col])), 5), 80) for row in normalised]
        weights.append(max(15.0, sum(lengths) / len(lengths)))
    total = sum(weights)
    available = A4[0] - 34 * mm
    widths = [available * weight / total for weight in weights]
    cell_style = ParagraphStyle(
        "TableCell", parent=styles["small"], fontSize=7.35, leading=9.5, spaceAfter=0
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
        ("GRID", (0, 0), (-1, -1), 0.45, LIGHT_BORDER),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 4.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4.5),
    ]
    for row in range(1, len(data)):
        if row % 2 == 0:
            commands.append(("BACKGROUND", (0, row), (-1, row), PALE_BLUE))
    table.setStyle(TableStyle(commands))
    return table


def _image_flowable(path: Path, caption: str, styles: dict[str, ParagraphStyle]) -> list[Flowable]:
    with Image.open(path) as image:
        width_px, height_px = image.size
    max_width = A4[0] - 36 * mm
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
            story.append(Preformatted("\n".join(code_lines), styles["code"]))
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
            toc = TableOfContents()
            toc.levelStyles = [
                ParagraphStyle(
                    "TOC1",
                    parent=styles["body"],
                    fontSize=10,
                    leading=14,
                    leftIndent=0,
                    firstLineIndent=0,
                    spaceBefore=2,
                ),
                ParagraphStyle(
                    "TOC2",
                    parent=styles["small"],
                    fontSize=8.5,
                    leading=12,
                    leftIndent=12,
                    firstLineIndent=0,
                ),
                ParagraphStyle(
                    "TOC3",
                    parent=styles["small"],
                    fontSize=7.8,
                    leading=10,
                    leftIndent=24,
                    firstLineIndent=0,
                ),
            ]
            story.extend([Paragraph("Contents", styles["h1"]), toc, PageBreak()])
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
                story.append(Spacer(1, 34 * mm))
                story.append(Paragraph(_inline(title, source, baseline), styles["title"]))
            else:
                paragraph = Paragraph(_inline(title, source, baseline), styles[f"h{min(level, 3)}"])
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
    build_diagrams()
    output.parent.mkdir(parents=True, exist_ok=True)
    document = ReportDocTemplate(
        str(output),
        pagesize=A4,
        leftMargin=17 * mm,
        rightMargin=17 * mm,
        topMargin=18 * mm,
        bottomMargin=22 * mm,
        title="PropertyScope NSW Release 0 Technical Report",
        author="Group 20",
        subject="41026 Advanced Software Development Assessment 1",
    )
    story = parse_markdown(source, baseline)
    document.multiBuild(story)


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=REPORT_DIR / "release-0-technical-report.md")
    parser.add_argument("--output", type=Path, default=REPORT_DIR / "group20.pdf")
    parser.add_argument("--baseline", default="7d5350d19023fb1e978e85127a72e3500a1556f3")
    args = parser.parse_args(list(argv) if argv is not None else None)
    build(args.source.resolve(), args.output.resolve(), args.baseline)
    print(args.output.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
