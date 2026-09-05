"""Compact private transport for fixed, database-owned export projections."""

from __future__ import annotations

from typing import Any


def columnar_export_page(page: dict[str, Any]) -> dict[str, Any]:
    """Encode field names once per page while retaining all record values and evidence."""
    items = page["items"]
    columns = list(items[0]) if items else []
    return {
        **{key: value for key, value in page.items() if key != "items"},
        "layout": "propertyscope.export-columns.v1",
        "columns": columns,
        "rows": [[item[column] for column in columns] for item in items],
    }
