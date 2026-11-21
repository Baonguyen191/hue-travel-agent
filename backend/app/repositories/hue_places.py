"""Read-only access to the supplied Hue SQLite POI source."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from app.schemas.place import Place, PlaceCategory
from app.services.normalize_hue import normalize_place

VALID_CATEGORIES = frozenset(
    {"restaurant", "cafe", "historic", "attraction", "market", "religious", "park", "museum"}
)


class HuePlacesRepository:
    """Repository that never opens the Hue source in write mode."""

    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        if not self.database_path.is_file():
            raise FileNotFoundError(f"Hue SQLite source file is missing: {self.database_path}")
        connection = sqlite3.connect(
            self.database_path.resolve().as_uri() + "?mode=ro", uri=True
        )
        connection.row_factory = sqlite3.Row
        try:
            yield connection
        finally:
            connection.close()

    def get_by_id(self, poi_id: str) -> Place | None:
        with self._connection() as connection:
            row = connection.execute("SELECT * FROM places WHERE id = ?", (poi_id,)).fetchone()
        return normalize_place(row) if row is not None else None

    def list_all(self) -> list[Place]:
        with self._connection() as connection:
            rows = connection.execute("SELECT * FROM places ORDER BY id").fetchall()
        return [normalize_place(row) for row in rows]

    def list_by_category(self, category: PlaceCategory) -> list[Place]:
        if category not in VALID_CATEGORIES:
            raise ValueError(f"Unsupported Hue POI category: {category}")
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT * FROM places WHERE category = ? ORDER BY id", (category,)
            ).fetchall()
        return [normalize_place(row) for row in rows]

    def count(self, category: PlaceCategory | None = None) -> int:
        if category is not None and category not in VALID_CATEGORIES:
            raise ValueError(f"Unsupported Hue POI category: {category}")
        with self._connection() as connection:
            if category is None:
                return connection.execute("SELECT COUNT(*) FROM places").fetchone()[0]
            return connection.execute(
                "SELECT COUNT(*) FROM places WHERE category = ?", (category,)
            ).fetchone()[0]

    def list_page(
        self, *, category: PlaceCategory | None, limit: int, offset: int
    ) -> list[Place]:
        if not 1 <= limit <= 200:
            raise ValueError("limit must be between 1 and 200")
        if offset < 0:
            raise ValueError("offset must be non-negative")
        if category is not None and category not in VALID_CATEGORIES:
            raise ValueError(f"Unsupported Hue POI category: {category}")
        with self._connection() as connection:
            if category is None:
                rows = connection.execute(
                    "SELECT * FROM places ORDER BY id LIMIT ? OFFSET ?", (limit, offset)
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT * FROM places WHERE category = ? ORDER BY id LIMIT ? OFFSET ?",
                    (category, limit, offset),
                ).fetchall()
        return [normalize_place(row) for row in rows]
