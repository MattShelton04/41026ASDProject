"""Tests for the semantic-token CSS guard."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from scripts.validate_frontend_styles import (
    collect_findings,
    deserialize,
    render_baseline,
    serialize,
)


def test_style_findings_are_repository_relative_and_stable(tmp_path: Path) -> None:
    root = tmp_path / "repository"
    stylesheet = root / "shared" / "frontend" / "example.css"
    stylesheet.parent.mkdir(parents=True)
    stylesheet.write_text(".example { color: #abcdef; padding: .3rem; }\n", encoding="utf-8")

    findings = collect_findings([stylesheet], root=root)
    payload = serialize(findings)

    assert payload["entries"] == [
        {
            "path": "shared/frontend/example.css",
            "kind": "off-scale-spacing",
            "property": "padding",
            "value": ".3rem",
            "count": 1,
        },
        {
            "path": "shared/frontend/example.css",
            "kind": "raw-colour",
            "property": "",
            "value": "#abcdef",
            "count": 1,
        },
    ]
    assert str(tmp_path) not in json.dumps(payload)
    assert deserialize(payload) == findings
    rendered = render_baseline(payload)
    assert len(rendered.splitlines()) == 8
    assert json.loads(rendered) == payload


def test_four_pixel_spacing_and_explicit_justifications_do_not_need_exceptions(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repository"
    stylesheet = root / "student-1" / "frontend" / "example.css"
    stylesheet.parent.mkdir(parents=True)
    stylesheet.write_text(
        ".scale { gap: .25rem; padding: 8px 1rem; }\n"
        ".local { color: #abcdef; padding: .3rem; } "
        "/* style-check: allow(local map marker geometry) */\n",
        encoding="utf-8",
    )

    assert not collect_findings([stylesheet], root=root)


def test_named_and_modern_css_colours_need_review(tmp_path: Path) -> None:
    root = tmp_path / "repository"
    stylesheet = root / "shared" / "frontend" / "modern.css"
    stylesheet.parent.mkdir(parents=True)
    stylesheet.write_text(
        ".modern { color: oklch(70% .1 180); background: color(display-p3 0 1 0); "
        "border-color: white; outline-color: currentColor; caret-color: transparent; "
        "box-shadow: 0 0 var(--red); }\n",
        encoding="utf-8",
    )

    findings = collect_findings([stylesheet], root=root)

    assert findings[("shared/frontend/modern.css", "raw-colour", "", "oklch(70% .1 180)")] == 1
    assert (
        findings[("shared/frontend/modern.css", "raw-colour", "", "color(display-p3 0 1 0)")] == 1
    )
    assert findings[("shared/frontend/modern.css", "raw-colour", "", "white")] == 1
    assert not any(value in {"currentcolor", "transparent", "red"} for *_, value in findings)


@pytest.mark.parametrize(
    "unsafe_path",
    (
        "C:/Users/example/styles.css",
        "C:\\Users\\example\\styles.css",
        "/tmp/styles.css",
        "../styles.css",
        "shared/frontend/../styles.css",
    ),
)
def test_absolute_and_traversal_baseline_paths_are_rejected(unsafe_path: str) -> None:
    payload = {
        "schemaVersion": 1,
        "entries": [
            {
                "path": unsafe_path,
                "kind": "raw-colour",
                "property": "",
                "value": "#fff",
                "count": 1,
            }
        ],
    }

    with pytest.raises(ValueError, match="absolute-path"):
        deserialize(payload)
