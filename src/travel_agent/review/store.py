"""Lưu kết quả duyệt tay trong cùng file SQLite với bảng `places`."""

from __future__ import annotations

import datetime as dt
import sqlite3
from pathlib import Path
from typing import Any

from travel_agent.data.place_repository import (
    PLACE_COLUMN_NAMES,
    ensure_places_schema,
    row_to_place,
)
from travel_agent.domain.models import Category
from travel_agent.review.models import Review, ReviewedPlace, ReviewInput, ReviewStatus

REVIEWS_SCHEMA = """
CREATE TABLE IF NOT EXISTS place_reviews (
    place_id TEXT PRIMARY KEY REFERENCES places (id),
    status TEXT NOT NULL,
    name_override TEXT,
    category_override TEXT,
    opening_hours_override TEXT,
    evidence TEXT,
    note TEXT,
    reviewed_at TEXT NOT NULL
);
"""

_PLACE_SELECT = ", ".join(f"p.{name}" for name in PLACE_COLUMN_NAMES)
_REVIEW_SELECT = (
    "r.status, r.name_override, r.category_override, r.opening_hours_override, "
    "r.evidence, r.note, r.reviewed_at"
)
_FROM = "FROM places p LEFT JOIN place_reviews r ON r.place_id = p.id"
# Thay cho `place_reviews` khi DB chưa có bảng này (chế độ chỉ đọc): không bản ghi nào.
_NO_REVIEWS = (
    "(SELECT NULL AS place_id, NULL AS status, NULL AS name_override, "
    "NULL AS category_override, NULL AS opening_hours_override, NULL AS evidence, "
    "NULL AS note, NULL AS reviewed_at WHERE 0)"
)
_FROM_NO_REVIEWS = f"FROM places p LEFT JOIN {_NO_REVIEWS} r ON r.place_id = p.id"
_UPSERT = (
    "INSERT INTO place_reviews (place_id, status, name_override, category_override, "
    "opening_hours_override, evidence, note, reviewed_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
    "ON CONFLICT(place_id) DO UPDATE SET status=excluded.status, "
    "name_override=excluded.name_override, category_override=excluded.category_override, "
    "opening_hours_override=excluded.opening_hours_override, evidence=excluded.evidence, "
    "note=excluded.note, reviewed_at=excluded.reviewed_at"
)


class ReviewStore:
    def __init__(self, path: str | Path, *, read_only: bool = False) -> None:
        """`read_only=True` mở file ở chế độ `mode=ro` và không chạy DDL nào, nên không đổi byte
        của file (eval dùng để file DVC dependency giữ nguyên). Thiếu bảng `place_reviews` thì
        coi như chưa địa điểm nào được duyệt. Không gọi `save`/`clear` ở chế độ này.
        """
        # check_same_thread=False: FastAPI có thể mở và dùng connection ở hai thread khác nhau
        # trong cùng một request; mỗi request có connection riêng nên không dùng chung.
        if read_only:
            uri = f"{Path(path).resolve().as_uri()}?mode=ro"
            self._conn = sqlite3.connect(uri, uri=True, check_same_thread=False)
            has_reviews = self._conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'place_reviews'"
            ).fetchone()
            self._from = _FROM if has_reviews else _FROM_NO_REVIEWS
        else:
            self._conn = sqlite3.connect(str(path), check_same_thread=False)
            ensure_places_schema(self._conn)
            self._conn.executescript(REVIEWS_SCHEMA)
            self._from = _FROM

    def close(self) -> None:
        self._conn.close()

    def query(
        self,
        status: ReviewStatus | None = None,
        category: Category | None = None,
        search: str | None = None,
        offset: int = 0,
        limit: int = 50,
        source: str | None = None,
    ) -> tuple[list[ReviewedPlace], int]:
        where, params = _where(status, category, search, source)
        total = self._conn.execute(f"SELECT COUNT(*) {self._from} {where}", params).fetchone()[0]
        rows = self._conn.execute(
            f"SELECT {_PLACE_SELECT}, {_REVIEW_SELECT} {self._from} {where} "
            "ORDER BY p.name, p.id LIMIT ? OFFSET ?",
            [*params, limit, offset],
        ).fetchall()
        return [_to_reviewed(row) for row in rows], int(total)

    def get(self, place_id: str) -> ReviewedPlace | None:
        row = self._conn.execute(
            f"SELECT {_PLACE_SELECT}, {_REVIEW_SELECT} {self._from} WHERE p.id = ?", (place_id,)
        ).fetchone()
        return None if row is None else _to_reviewed(row)

    def sources(self) -> dict[str, int]:
        rows = self._conn.execute(
            "SELECT source, COUNT(*) FROM places GROUP BY source ORDER BY source"
        ).fetchall()
        return {str(source): int(count) for source, count in rows}

    def stats(self, source: str | None = None) -> dict[str, int]:
        where, params = _where(None, None, None, source)
        rows = self._conn.execute(
            f"SELECT COALESCE(r.status, 'pending'), COUNT(*) {self._from} {where} GROUP BY 1",
            params,
        ).fetchall()
        counts = {status.value: 0 for status in ReviewStatus}
        counts.update({str(status): int(count) for status, count in rows})
        counts["total"] = sum(counts.values())
        return counts

    def save(self, review: ReviewInput, now: dt.datetime) -> Review:
        exists = self._conn.execute(
            "SELECT 1 FROM places WHERE id = ?", (review.place_id,)
        ).fetchone()
        if exists is None:
            raise KeyError(review.place_id)
        saved = Review(**review.model_dump(), reviewed_at=now)
        with self._conn:
            self._conn.execute(
                _UPSERT,
                (
                    saved.place_id,
                    saved.status.value,
                    saved.name_override,
                    None if saved.category_override is None else saved.category_override.value,
                    saved.opening_hours_override,
                    saved.evidence,
                    saved.note,
                    saved.reviewed_at.isoformat(),
                ),
            )
        return saved

    def clear(self, place_id: str) -> None:
        with self._conn:
            self._conn.execute("DELETE FROM place_reviews WHERE place_id = ?", (place_id,))

    def approved(self) -> list[ReviewedPlace]:
        items, _ = self.query(status=ReviewStatus.APPROVED, limit=-1)  # LIMIT -1 = không giới hạn
        return items


def _where(
    status: ReviewStatus | None,
    category: Category | None,
    search: str | None,
    source: str | None = None,
) -> tuple[str, list[Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if source:
        clauses.append("p.source = ?")
        params.append(source)
    if status is ReviewStatus.PENDING:
        clauses.append("r.place_id IS NULL")
    elif status is not None:
        clauses.append("r.status = ?")
        params.append(status.value)
    if category is not None:
        clauses.append("COALESCE(r.category_override, p.category) = ?")
        params.append(category.value)
    if search:
        like = f"%{search.strip()}%"
        clauses.append("(p.name LIKE ? OR r.name_override LIKE ? OR p.id = ?)")
        params.extend([like, like, search.strip()])
    return ("WHERE " + " AND ".join(clauses)) if clauses else "", params


def _to_reviewed(row: tuple[Any, ...]) -> ReviewedPlace:
    split = len(PLACE_COLUMN_NAMES)
    place = row_to_place(row[:split])
    status, name_o, category_o, hours_o, evidence, note, reviewed_at = row[split:]
    if status is None:
        return ReviewedPlace(place=place, status=ReviewStatus.PENDING)
    review = Review(
        place_id=place.id,
        status=ReviewStatus(status),
        name_override=name_o,
        category_override=None if category_o is None else Category(category_o),
        opening_hours_override=hours_o,
        evidence=evidence,
        note=note,
        reviewed_at=dt.datetime.fromisoformat(reviewed_at),
    )
    return ReviewedPlace(place=place, status=review.status, review=review)
