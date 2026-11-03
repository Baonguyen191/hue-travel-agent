"""Lưu trữ Place. Validator chỉ phụ thuộc Protocol `PlaceLookup`."""

from __future__ import annotations

import datetime as dt
import sqlite3
from collections.abc import Iterable
from pathlib import Path
from typing import Any, Protocol

from travel_agent.domain.models import Category, Coordinates, Place

_SCHEMA = """
CREATE TABLE IF NOT EXISTS places (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    category TEXT NOT NULL,
    lat REAL NOT NULL,
    lon REAL NOT NULL,
    opening_hours_raw TEXT,
    source TEXT NOT NULL,
    source_place_id TEXT NOT NULL,
    license TEXT NOT NULL,
    collected_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_places_category ON places (category);
"""

_COLUMNS = (
    "id, name, category, lat, lon, opening_hours_raw, "
    "source, source_place_id, license, collected_at"
)

_UPSERT = (
    f"INSERT INTO places ({_COLUMNS}) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
    "ON CONFLICT(id) DO UPDATE SET name=excluded.name, category=excluded.category, "
    "lat=excluded.lat, lon=excluded.lon, opening_hours_raw=excluded.opening_hours_raw, "
    "source=excluded.source, source_place_id=excluded.source_place_id, "
    "license=excluded.license, collected_at=excluded.collected_at"
)


class PlaceLookup(Protocol):
    def get(self, place_id: str) -> Place | None: ...


class InMemoryPlaceRepository:
    def __init__(self, places: Iterable[Place]) -> None:
        self._by_id = {place.id: place for place in places}

    def get(self, place_id: str) -> Place | None:
        return self._by_id.get(place_id)


class SqlitePlaceRepository:
    def __init__(self, path: str | Path) -> None:
        self._conn = sqlite3.connect(str(path))
        self._conn.executescript(_SCHEMA)

    def close(self) -> None:
        self._conn.close()

    def upsert_many(self, places: Iterable[Place]) -> int:
        rows = [_to_row(place) for place in places]
        with self._conn:
            self._conn.executemany(_UPSERT, rows)
        return len(rows)

    def get(self, place_id: str) -> Place | None:
        row = self._conn.execute(
            f"SELECT {_COLUMNS} FROM places WHERE id = ?", (place_id,)
        ).fetchone()
        return None if row is None else _from_row(row)

    def list_places(self, category: Category | None = None, limit: int = 50) -> list[Place]:
        if category is None:
            cursor = self._conn.execute(
                f"SELECT {_COLUMNS} FROM places ORDER BY name LIMIT ?", (limit,)
            )
        else:
            cursor = self._conn.execute(
                f"SELECT {_COLUMNS} FROM places WHERE category = ? ORDER BY name LIMIT ?",
                (category.value, limit),
            )
        return [_from_row(row) for row in cursor.fetchall()]

    def count_by_category(self) -> dict[Category, int]:
        rows = self._conn.execute(
            "SELECT category, COUNT(*) FROM places GROUP BY category"
        ).fetchall()
        return {Category(category): count for category, count in rows}


def _to_row(place: Place) -> tuple[Any, ...]:
    return (
        place.id,
        place.name,
        place.category.value,
        place.coords.lat,
        place.coords.lon,
        place.opening_hours_raw,
        place.source,
        place.source_place_id,
        place.license,
        place.collected_at.isoformat(),
    )


def _from_row(row: tuple[Any, ...]) -> Place:
    (pid, name, category, lat, lon, hours, source, source_place_id, license_, collected) = row
    return Place(
        id=pid,
        name=name,
        category=Category(category),
        coords=Coordinates(lat=lat, lon=lon),
        opening_hours_raw=hours,
        source=source,
        source_place_id=source_place_id,
        license=license_,
        collected_at=dt.datetime.fromisoformat(collected),
    )
