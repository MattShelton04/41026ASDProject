"""Static accessibility and boundary checks for the Buyer Case frontend."""

from __future__ import annotations

from pathlib import Path

FRONTEND = Path(__file__).parents[1] / "frontend"


def test_design_system_stylesheets_are_imported_in_required_order() -> None:
    html = (FRONTEND / "index.html").read_text(encoding="utf-8")
    expected = [
        "design-system/tokens.css",
        "design-system/base.css",
        "design-system/components.css",
        "styles.css",
    ]
    positions = [html.index(value) for value in expected]
    assert positions == sorted(positions)


def test_frontend_contains_accessible_crud_controls_and_confirm_dialog() -> None:
    html = (FRONTEND / "index.html").read_text(encoding="utf-8")
    assert 'href="#main-content"' in html
    assert 'id="case-form"' in html
    assert 'label for="case-name"' in html
    assert 'label for="dwelling-types"' in html
    assert 'label for="practical-priorities"' in html
    assert 'aria-describedby="case-name-error"' in html
    assert 'id="delete-dialog"' in html
    assert 'id="confirm-delete"' in html
    for form in ("property-form", "note-form", "task-form"):
        assert f'id="{form}"' in html
    for control in (
        "property-ref",
        "journey-stage",
        "property-rating",
        "property-priority",
        "note-content",
        "note-property",
        "task-title",
        "task-due-date",
        "task-property",
        "task-completed",
    ):
        assert f'id="{control}"' in html
    assert 'aria-live="polite"' in html
    assert 'type="module"' in html


def test_frontend_has_required_ui_states_and_responsive_floor() -> None:
    html = (FRONTEND / "index.html").read_text(encoding="utf-8")
    script = (FRONTEND / "app.js").read_text(encoding="utf-8")
    styles = (FRONTEND / "styles.css").read_text(encoding="utf-8")
    assert 'data-state="loading"' in html
    for state in ("loading", "empty", "invalid", "conflict", "unavailable", "success"):
        assert state in script or state in html
    assert "min-width: 320px" in styles
    assert ":focus-visible" in styles
    assert "@media" in styles


def test_frontend_never_contains_server_identity_or_internal_credentials() -> None:
    source = "\n".join(
        (FRONTEND / name).read_text(encoding="utf-8")
        for name in ("index.html", "styles.css", "app.js")
    )
    assert "owner_ref" not in source
    assert "release0-demo-owner" not in source
    assert "X-PropertyScope-Internal-Token" not in source
    assert "PROPERTYSCOPE_INTERNAL_TOKEN" not in source


def test_frontend_calls_only_the_public_buyer_case_api() -> None:
    script = (FRONTEND / "app.js").read_text(encoding="utf-8")
    assert 'API_BASE = "/api/buyer-workspaces/v1"' in script
    assert "/internal/" not in script
    assert "ai-mode" not in script.lower()
    assert "propertyscope_data" not in script
