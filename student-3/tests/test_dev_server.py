"""The loopback developer server must not expose repository source or credentials."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "suburb_dev_server", Path(__file__).parents[1] / "frontend" / "dev_server.py"
)
assert SPEC and SPEC.loader
server = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(server)


@pytest.mark.parametrize(
    "path",
    [
        "/../../.env",
        "/%2e%2e/%2e%2e/pyproject.toml",
        "/browser/../../../pyproject.toml",
        "/nginx.conf",
        "/dev_server.py",
        "/.env",
        "/browser/missing.js",
        "/missing.js",
        "/browser/%2e%2e/%2e%2e/README.md",
        "/api/other",
        "/..\\..\\.env",
    ],
)
def test_unsafe_or_missing_asset_is_not_served(path: str) -> None:
    assert server.static_path(path) is None


@pytest.mark.parametrize(
    "path", ["/", "/app.js", "/styles.css", "/browser/index.js", "/design-system/shell.css"]
)
def test_approved_assets_resolve_inside_asset_roots(path: str) -> None:
    result = server.static_path(path)
    assert result is not None and result.is_file()
    assert result.is_relative_to(server.FRONTEND) or result.is_relative_to(
        server.REPOSITORY / "shared" / "frontend"
    )


def test_symlink_escape_is_not_served(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    frontend = tmp_path / "public"
    frontend.mkdir()
    (tmp_path / "secret.js").write_text("secret", encoding="utf-8")
    try:
        (frontend / "linked.js").symlink_to(tmp_path / "secret.js")
    except OSError as exc:
        if getattr(exc, "winerror", None) == 1314:
            pytest.skip("Windows symlink creation requires Developer Mode or elevated privileges")
        raise
    monkeypatch.setattr(server, "FRONTEND", frontend)
    assert server.static_path("/linked.js") is None


def test_proxy_does_not_forward_arbitrary_mutations() -> None:
    assert server.proxy_path("/api/suburb-analytics/v1/suburbs")
    assert server.proxy_path("/health/ready")
    assert not server.proxy_path("/api/buyer-workspaces/v1/buyer-cases")
    assert not server.proxy_path("/index.html")
