"""Remove the seeded demonstration baseline from a production database.

``002_seed.sql`` seeds a deterministic showcase: ten market cases over three fixture properties
and twenty-six synthetic sale observations attributed to ``fixture-2026-r1``. Local stacks, CI
and the tests all rely on it.

A production database (``PROPERTYSCOPE_DEMONSTRATION_DATA=false``, the Azure deployment) must
start empty instead, for the same reason Feature 1's does. Leaving the seed in place there is
worse than useless: Feature 1 publishes only real reviewed releases, and importing one sets the
accepted generation pointer, after which ``list_sales`` reads that release alone. The seeded sale
rows stay in the table but stop being consulted, so every seeded case resolves to zero eligible
sales, no exclusions and no source releases - a case that looks broken rather than empty.

Only demonstration rows are removed, so the purge is idempotent and safe beside real data:

- market cases with the seed identifiers (``60000000-...``);
- sale observations with the seed identifiers (``50000000-...``), which are exactly the rows
  ``002_seed.sql`` attributes to the synthetic ``fixture-2026-r1`` release.

Imported generations are never touched: a real release and its records are not demonstration
data, and a production database may already hold one.
"""

from __future__ import annotations

import sqlite3

# Plain literals throughout: nothing here is built from input.
_PURGE: tuple[str, ...] = (
    "DELETE FROM market_case WHERE id LIKE '60000000-0000-4000-8000-%'",
    "DELETE FROM sale_observation WHERE id LIKE '50000000-0000-4000-8000-%'",
)


def purge_demonstration_data(connection: sqlite3.Connection) -> dict[str, int]:
    """Delete the seeded showcase rows, returning how many of each were removed."""
    removed: dict[str, int] = {}
    for statement in _PURGE:
        table = statement.split("FROM ", 1)[1].split(" ", 1)[0]
        removed[table] = connection.execute(statement).rowcount
    connection.commit()
    return removed
