from __future__ import annotations

import httpx

from propertyscope_data_platform.app import create_app
from propertyscope_data_platform.clients import AiModeClient, DataStoreClient


def test_activity_download_is_bounded_ordered_and_excludes_private_evidence() -> None:
    run_id = "30000000-0000-0000-0000-000000000001"

    def database(request: httpx.Request) -> httpx.Response:
        assert request.url.path == f"/internal/data-platform/v1/runs/{run_id}/activity"
        assert request.url.params["limit"] == "1000"
        return httpx.Response(
            200,
            json={
                "items": [
                    {
                        "stage": "import",
                        "phase": "new\nphase",
                        "rows_processed": 12,
                        "lease_token": "PRIVATE_TOKEN",
                        "error_json": {"message": "PRIVATE_ERROR"},
                    },
                    {"stage": "acquire", "rows_processed": 0},
                ]
            },
        )

    app = create_app(
        store_client=DataStoreClient(
            "http://database", "test", client=httpx.Client(transport=httpx.MockTransport(database))
        ),
        ai_mode_client=AiModeClient(
            "http://ai", client=httpx.Client(transport=httpx.MockTransport(database))
        ),
    )
    response = app.test_client().get(
        f"/api/data-platform/v1/ingestion-runs/{run_id}/activity/download"
    )
    assert response.status_code == 200
    assert response.mimetype == "text/plain"
    assert "attachment;" in response.headers["Content-Disposition"]
    assert response.headers["Cache-Control"] == "no-store"
    text = response.get_data(as_text=True)
    assert "PRIVATE" not in text
    assert len(text.splitlines()) == 3
    assert "acquire" in text.splitlines()[1] and " | 0 | " in text.splitlines()[1]
    assert "newphase" in text.splitlines()[2]
