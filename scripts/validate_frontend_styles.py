"""Keep Shared and Feature 1 CSS aligned with the semantic design foundation."""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from collections.abc import Iterable
from pathlib import Path, PurePosixPath, PureWindowsPath

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
BASELINE_PATH = REPOSITORY_ROOT / "docs" / "ui" / "frontend-style-baseline.json"
STYLE_ROOTS = (
    REPOSITORY_ROOT / "shared" / "frontend",
    REPOSITORY_ROOT / "student-1" / "frontend",
)
EXCLUDED_PARTS = {"vendor"}
EXCLUDED_FILES = {Path("shared/frontend/design-system/tokens.css")}
CSS_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)
CSS_DECLARATION = re.compile(r"(?P<property>--?[\w-]+|[\w-]+)\s*:\s*(?P<value>[^;{}]+)(?:;|(?=\}))")
RAW_COLOUR = re.compile(
    r"#[0-9a-fA-F]{3,8}\b|(?:rgb|rgba|hsl|hsla|oklab|oklch|lab|lch|color|color-mix)\([^)]*\)",
)
COLOUR_WORD = re.compile(r"\b[a-zA-Z]+\b")
NON_LITERAL_VALUE = re.compile(r"(?:var|url)\([^)]*\)|(['\"]).*?\1", re.IGNORECASE)
CSS_NAMED_COLOURS = frozenset(
    """
    aliceblue antiquewhite aqua aquamarine azure beige bisque black blanchedalmond
    blue blueviolet brown burlywood cadetblue chartreuse chocolate coral cornflowerblue
    cornsilk crimson cyan darkblue darkcyan darkgoldenrod darkgray darkgreen darkgrey
    darkkhaki darkmagenta darkolivegreen darkorange darkorchid darkred darksalmon
    darkseagreen darkslateblue darkslategray darkslategrey darkturquoise darkviolet
    deeppink deepskyblue dimgray dimgrey dodgerblue firebrick floralwhite forestgreen
    fuchsia gainsboro ghostwhite gold goldenrod gray green greenyellow grey honeydew
    hotpink indianred indigo ivory khaki lavender lavenderblush lawngreen lemonchiffon
    lightblue lightcoral lightcyan lightgoldenrodyellow lightgray lightgreen lightgrey
    lightpink lightsalmon lightseagreen lightskyblue lightslategray lightslategrey
    lightsteelblue lightyellow lime limegreen linen magenta maroon mediumaquamarine
    mediumblue mediumorchid mediumpurple mediumseagreen mediumslateblue mediumspringgreen
    mediumturquoise mediumvioletred midnightblue mintcream mistyrose moccasin navajowhite
    navy oldlace olive olivedrab orange orangered orchid palegoldenrod palegreen
    paleturquoise palevioletred papayawhip peachpuff peru pink plum powderblue purple
    rebeccapurple red rosybrown royalblue saddlebrown salmon sandybrown seagreen seashell
    sienna silver skyblue slateblue slategray slategrey snow springgreen steelblue tan teal
    thistle tomato turquoise violet wheat white whitesmoke yellow yellowgreen
    """.split()  # noqa: SIM905 - the canonical keyword list is easier to audit in CSS order
)
SPACING_DECLARATION = re.compile(
    r"(?P<property>(?:margin|padding|gap|row-gap|column-gap)(?:-(?:top|right|bottom|left|inline|block))?)\s*:\s*(?P<value>[^;{}]+)",
)
DIMENSION = re.compile(r"(?<![\w.-])(?P<number>-?(?:\d*\.)?\d+)(?P<unit>rem|px)\b")
JUSTIFICATION = re.compile(r"style-check:\s*allow\((?P<reason>[^)]+)\)")

Finding = tuple[str, str, str, str]


def _relative(path: Path, root: Path = REPOSITORY_ROOT) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def iter_stylesheets(roots: Iterable[Path] = STYLE_ROOTS) -> list[Path]:
    """Return production CSS sources, excluding vendored code and the token source."""
    paths: list[Path] = []
    for root in roots:
        for path in root.rglob("*.css"):
            relative = path.resolve().relative_to(REPOSITORY_ROOT.resolve())
            if EXCLUDED_PARTS.intersection(relative.parts) or relative in EXCLUDED_FILES:
                continue
            paths.append(path)
    return sorted(paths)


def _is_scale_value(number: float, unit: str) -> bool:
    pixels = number * 16 if unit == "rem" else number
    return abs(pixels / 4 - round(pixels / 4)) < 0.0001


def _strip_comments(source: str) -> tuple[str, set[int]]:
    """Strip comments without moving declarations and retain valid inline allowance lines."""
    justified_lines: set[int] = set()

    def replace(match: re.Match[str]) -> str:
        justification = JUSTIFICATION.search(match.group(0))
        if justification and len(justification.group("reason").strip()) >= 8:
            justified_lines.add(source.count("\n", 0, match.start()))
        return "".join("\n" if character == "\n" else " " for character in match.group(0))

    return CSS_COMMENT.sub(replace, source), justified_lines


def collect_findings(paths: Iterable[Path], root: Path = REPOSITORY_ROOT) -> Counter[Finding]:
    """Collect raw colours and off-scale spacing without retaining machine paths."""
    findings: Counter[Finding] = Counter()
    for path in paths:
        relative = _relative(path, root)
        source = path.read_text(encoding="utf-8")
        stylesheet, justified_lines = _strip_comments(source)
        for declaration in CSS_DECLARATION.finditer(stylesheet):
            declaration_end_line = stylesheet.count("\n", 0, declaration.end())
            if declaration_end_line in justified_lines:
                continue
            property_name = declaration.group("property").lower()
            value = declaration.group("value")
            for match in RAW_COLOUR.finditer(value):
                findings[(relative, "raw-colour", "", match.group(0).lower())] += 1
            colour_context = property_name.startswith("--") or any(
                part in property_name
                for part in (
                    "color",
                    "background",
                    "border",
                    "shadow",
                    "fill",
                    "stroke",
                    "outline",
                    "caret",
                    "accent",
                    "decoration",
                )
            )
            if colour_context:
                literal_value = NON_LITERAL_VALUE.sub("", value)
                for match in COLOUR_WORD.finditer(literal_value):
                    colour = match.group(0).lower()
                    if colour in CSS_NAMED_COLOURS:
                        findings[(relative, "raw-colour", "", colour)] += 1
            spacing = SPACING_DECLARATION.fullmatch(f"{property_name}:{value}")
            if spacing:
                for dimension in DIMENSION.finditer(value):
                    number = float(dimension.group("number"))
                    unit = dimension.group("unit")
                    if not _is_scale_value(number, unit):
                        findings[
                            (
                                relative,
                                "off-scale-spacing",
                                property_name,
                                dimension.group(0).lower(),
                            )
                        ] += 1
    return findings


def serialize(findings: Counter[Finding]) -> dict[str, object]:
    """Create a stable, repository-relative baseline document."""
    entries = [
        {"path": path, "kind": kind, "property": property_name, "value": value, "count": count}
        for (path, kind, property_name, value), count in sorted(findings.items())
    ]
    return {
        "schemaVersion": 1,
        "purpose": (
            "Reviewed legacy/local CSS exceptions; new occurrences require a token or an "
            "inline style-check justification."
        ),
        "entries": entries,
    }


def deserialize(payload: object) -> Counter[Finding]:
    """Load and validate the small checked-in exception baseline."""
    if not isinstance(payload, dict) or payload.get("schemaVersion") != 1:
        raise ValueError("frontend style baseline must use schemaVersion 1")
    entries = payload.get("entries")
    if not isinstance(entries, list):
        raise ValueError("frontend style baseline entries must be a list")
    findings: Counter[Finding] = Counter()
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("frontend style baseline entries must be objects")
        path = entry.get("path")
        kind = entry.get("kind")
        property_name = entry.get("property")
        value = entry.get("value")
        count = entry.get("count")
        posix_path = PurePosixPath(path) if isinstance(path, str) else None
        windows_path = PureWindowsPath(path) if isinstance(path, str) else None
        non_portable_path = (
            posix_path is None
            or windows_path is None
            or posix_path.is_absolute()
            or windows_path.is_absolute()
            or bool(windows_path.drive)
            or ".." in posix_path.parts
            or ".." in windows_path.parts
        )
        if (
            not isinstance(path, str)
            or non_portable_path
            or kind not in {"raw-colour", "off-scale-spacing"}
            or not isinstance(property_name, str)
            or not isinstance(value, str)
            or not isinstance(count, int)
            or count < 1
        ):
            raise ValueError("frontend style baseline contains an invalid or absolute-path entry")
        findings[(path, kind, property_name, value)] = count
    return findings


def render_baseline(payload: dict[str, object]) -> str:
    """Render one reviewed exception per line so baseline diffs stay compact."""
    entries = payload.get("entries")
    if not isinstance(entries, list):
        raise ValueError("frontend style baseline entries must be a list")
    lines = [
        "{",
        f'  "schemaVersion": {json.dumps(payload.get("schemaVersion"))},',
        f'  "purpose": {json.dumps(payload.get("purpose"))},',
        '  "entries": [',
    ]
    lines.extend(
        f"    {json.dumps(entry, separators=(',', ':'))}{',' if index < len(entries) - 1 else ''}"
        for index, entry in enumerate(entries)
    )
    lines.extend(("  ]", "}"))
    return "\n".join(lines) + "\n"


def validate(baseline_path: Path = BASELINE_PATH) -> list[str]:
    """Return actionable differences from the reviewed baseline."""
    actual = collect_findings(iter_stylesheets())
    reviewed = deserialize(json.loads(baseline_path.read_text(encoding="utf-8")))
    messages: list[str] = []
    for finding in sorted(actual.keys() | reviewed.keys()):
        actual_count = actual[finding]
        reviewed_count = reviewed[finding]
        if actual_count == reviewed_count:
            continue
        path, kind, property_name, value = finding
        context = f" {property_name}" if property_name else ""
        messages.append(
            f"{path}: {kind}{context} {value!r} occurs {actual_count} time(s); "
            f"reviewed baseline has {reviewed_count}."
        )
    return messages


def main() -> None:
    """Write the reviewed baseline explicitly or enforce it by default."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--write-baseline", action="store_true", help="replace the reviewed exception baseline"
    )
    args = parser.parse_args()
    if args.write_baseline:
        payload = serialize(collect_findings(iter_stylesheets()))
        BASELINE_PATH.write_text(render_baseline(payload), encoding="utf-8")
        print(f"Wrote {_relative(BASELINE_PATH)}")
        return
    messages = validate()
    if messages:
        raise SystemExit(
            "Frontend style validation failed. Use a semantic token, add a specific "
            "`style-check: allow(reason)` comment, or intentionally review and regenerate "
            "the baseline:\n" + "\n".join(messages)
        )
    print("Frontend styles match the reviewed semantic-token baseline.")


if __name__ == "__main__":
    main()
