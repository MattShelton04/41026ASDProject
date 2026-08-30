from __future__ import annotations

from typing import Any, cast
from unittest.mock import MagicMock

from flask import Flask

from propertyscope_data_store.api import create_blueprint
from propertyscope_data_store.repository import PropertyScopeStore


def test_schema_fingerprint_response_identifies_the_digest_policy() -> None:
    store = MagicMock(spec=PropertyScopeStore)
    store.fingerprint.return_value = "a" * 64
    app = Flask(__name__)
    app.register_blueprint(create_blueprint(cast(Any, store), internal_token="internal-token"))

    response = app.test_client().get(
        "/internal/data-platform/v1/schema/fingerprint",
        headers={"X-PropertyScope-Internal-Token": "internal-token"},
    )

    assert response.status_code == 200
    assert response.get_json() == {
        "algorithm": "sha256",
        "fingerprint": "a" * 64,
        "policy_version": "propertyscope-postgresql-schema.v2",
    }
