"""Tests for the semantic-token CSS guard."""

from __future__ import annotations

import json
from pathlib import Path

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


def test_absolute_baseline_paths_are_rejected() -> None:
    payload = {
        "schemaVersion": 1,
        "entries": [
            {
                "path": "C:/Users/example/styles.css",
                "kind": "raw-colour",
                "property": "",
                "value": "#fff",
                "count": 1,
            }
        ],
    }

    try:
        deserialize(payload)
    except ValueError as error:
        assert "absolute-path" in str(error)
    else:
        raise AssertionError("absolute baseline path should be rejected")
