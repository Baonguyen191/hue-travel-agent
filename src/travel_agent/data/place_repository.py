"""Lưu trữ Place. Validator chỉ phụ thuộc Protocol `PlaceLookup`."""

from __future__ import annotations

import datetime as dt
import json
import sqlite3
from collections.abc import Iterable
from pathlib import Path
from typing import Any, Protocol

from travel_agent.domain.models import Category, Coordinates, Place

PLACES_SCHEMA = """
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
    collected_at TEXT NOT NULL,
    attributes_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_places_category ON places (category);
"""

PLACE_COLUMN_NAMES = (
    "id",
    "name",
    "category",
    "lat",
    "lon",
    "opening_hours_raw",
    "source",
    "source_place_id",
    "license",
    "collected_at",
    "attributes_json",
)
_COLUMNS = ", ".join(PLACE_COLUMN_NAMES)

_UPSERT = (
    f"INSERT INTO places ({_COLUMNS}) VALUES ({', '.join('?' for _ in PLACE_COLUMN_NAMES)}) "
    "ON CONFLICT(id) DO UPDATE SET name=excluded.name, category=excluded.category, "
    "lat=excluded.lat, lon=excluded.lon, opening_hours_raw=excluded.opening_hours_raw, "
    "source=excluded.source, source_place_id=excluded.source_place_id, "
    "license=excluded.license, collected_at=excluded.collected_at, "
    "attributes_json=excluded.attributes_json"
)


def ensure_places_schema(conn: sqlite3.Connection) -> None:
    """Tạo bảng `places` và nâng cấp DB cũ (trước khi có cột `attributes_json`)."""
    conn.executescript(PLACES_SCHEMA)
    columns = {row[1] for row in conn.execute("PRAGMA table_info(places)")}
    if "attributes_json" not in columns:
        with conn:
            conn.execute("ALTER TABLE places ADD COLUMN attributes_json TEXT NOT NULL DEFAULT '{}'")


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
        ensure_places_schema(self._conn)

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
        return None if row is None else row_to_place(row)

    def list_places(
        self,
        category: Category | None = None,
        limit: int = 50,
        source: str | None = None,
    ) -> list[Place]:
        clauses: list[str] = []
        params: list[Any] = []
        if category is not None:
            clauses.append("category = ?")
            params.append(category.value)
        if source is not None:
            clauses.append("source = ?")
            params.append(source)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        cursor = self._conn.execute(
            f"SELECT {_COLUMNS} FROM places {where} ORDER BY name LIMIT ?", [*params, limit]
        )
        return [row_to_place(row) for row in cursor.fetchall()]

    def count_by_category(self, source: str | None = None) -> dict[Category, int]:
        if source is None:
            rows = self._conn.execute(
                "SELECT category, COUNT(*) FROM places GROUP BY category"
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT category, COUNT(*) FROM places WHERE source = ? GROUP BY category",
                (source,),
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
        json.dumps(place.attributes, ensure_ascii=False),
    )


def row_to_place(row: tuple[Any, ...]) -> Place:
    """`row` theo thứ tự `PLACE_COLUMN_NAMES`."""
    (
        pid,
        name,
        category,
        lat,
        lon,
        hours,
        source,
        source_place_id,
        license_,
        collected,
        attributes_json,
    ) = row
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
        attributes=json.loads(attributes_json or "{}"),
    )
