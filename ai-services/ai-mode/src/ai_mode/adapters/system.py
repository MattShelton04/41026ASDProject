"""Production clock and identifier adapters."""

from datetime import UTC, datetime
from uuid import UUID, uuid4


class SystemClock:
    """Aware UTC wall clock."""

    def now(self) -> datetime:
        return datetime.now(UTC)


class UUID4Generator:
    """Portable random UUID source."""

    def new(self) -> UUID:
        return uuid4()
