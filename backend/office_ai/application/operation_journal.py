"""Use case for reading the local operation journal."""

from office_ai.infrastructure.database import LocalDatabase


def read_recent_operations(database: LocalDatabase, limit: int = 50) -> list[dict[str, object]]:
    return database.list_operations(limit)
