from __future__ import annotations

from typing import Any, cast
from unittest.mock import MagicMock

import pytest
from flask import Flask

from propertyscope_data_store.api import create_blueprint
from propertyscope_data_store.repository import PropertyScopeStore

_FINGERPRINT_PATH = "/internal/data-platform/v1/schema/fingerprint"


def _client() -> Any:
    store = MagicMock(spec=PropertyScopeStore)
    store.fingerprint.return_value = "a" * 64
    store.ready.return_value = True
    app = Flask(__name__)
    app.register_blueprint(create_blueprint(cast(Any, store), internal_token="internal-token"))
    return app.test_client()


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"X-PropertyScope-Internal-Token": ""},
        {"X-PropertyScope-Internal-Token": "internal-toke"},
        {"X-PropertyScope-Internal-Token": "internal-token "},
        {"X-PropertyScope-Internal-Token": "intérnal-token"},
    ],
)
def test_private_routes_reject_missing_or_mismatched_credentials(headers: dict[str, str]) -> None:
    response = _client().get(_FINGERPRINT_PATH, headers=headers)

    assert response.status_code == 401
    assert response.content_type == "application/problem+json"
    assert response.get_json()["code"] == "unauthorised"


def test_private_routes_accept_the_configured_credential() -> None:
    response = _client().get(
        _FINGERPRINT_PATH, headers={"X-PropertyScope-Internal-Token": "internal-token"}
    )

    assert response.status_code == 200


def test_health_routes_do_not_require_credentials() -> None:
    assert _client().get("/health/live").status_code == 200
