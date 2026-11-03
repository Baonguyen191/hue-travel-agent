"""Lưu link nguồn dữ liệu trong SQLite."""

from __future__ import annotations

import builtins
import datetime as dt
import sqlite3
from pathlib import Path
from typing import Any

from travel_agent.sources.models import AddResult, LinkInput, LinkStatus, LinkTopic, SourceLink

LINKS_SCHEMA = """
CREATE TABLE IF NOT EXISTS source_links (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url TEXT NOT NULL UNIQUE,
    topic TEXT NOT NULL,
    note TEXT,
    status TEXT NOT NULL,
    added_at TEXT NOT NULL
);
"""

_COLUMNS = "id, url, topic, note, status, added_at"


class LinkStore:
    def __init__(self, path: str | Path) -> None:
        # Mỗi request có connection riêng; FastAPI có thể dùng nó ở thread khác thread tạo ra.
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.executescript(LINKS_SCHEMA)

    def close(self) -> None:
        self._conn.close()

    def add(self, links: LinkInput, now: dt.datetime) -> AddResult:
        added: builtins.list[SourceLink] = []
        duplicates: builtins.list[str] = []
        with self._conn:
            for url in links.urls:
                cursor = self._conn.execute(
                    "INSERT OR IGNORE INTO source_links (url, topic, note, status, added_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (url, links.topic.value, links.note, LinkStatus.NEW.value, now.isoformat()),
                )
                if cursor.rowcount == 0 or cursor.lastrowid is None:
                    duplicates.append(url)
                    continue
                added.append(
                    SourceLink(
                        id=cursor.lastrowid,
                        url=url,
                        topic=links.topic,
                        note=links.note,
                        status=LinkStatus.NEW,
                        added_at=now,
                    )
                )
        return AddResult(added=added, duplicates=duplicates)

    def list(self, status: LinkStatus | None = None) -> builtins.list[SourceLink]:
        if status is None:
            cursor = self._conn.execute(
                f"SELECT {_COLUMNS} FROM source_links ORDER BY added_at DESC, id DESC"
            )
        else:
            cursor = self._conn.execute(
                f"SELECT {_COLUMNS} FROM source_links WHERE status = ? "
                "ORDER BY added_at DESC, id DESC",
                (status.value,),
            )
        return [_to_link(row) for row in cursor.fetchall()]

    def counts(self) -> dict[str, int]:
        rows = self._conn.execute(
            "SELECT status, COUNT(*) FROM source_links GROUP BY status"
        ).fetchall()
        counts = {status.value: 0 for status in LinkStatus}
        counts.update({str(status): int(count) for status, count in rows})
        counts["total"] = sum(counts.values())
        return counts

    def set_status(self, link_id: int, status: LinkStatus) -> bool:
        with self._conn:
            cursor = self._conn.execute(
                "UPDATE source_links SET status = ? WHERE id = ?", (status.value, link_id)
            )
        return cursor.rowcount > 0

    def delete(self, link_id: int) -> bool:
        with self._conn:
            cursor = self._conn.execute("DELETE FROM source_links WHERE id = ?", (link_id,))
        return cursor.rowcount > 0


def _to_link(row: tuple[Any, ...]) -> SourceLink:
    link_id, url, topic, note, status, added_at = row
    return SourceLink(
        id=link_id,
        url=url,
        topic=LinkTopic(topic),
        note=note,
        status=LinkStatus(status),
        added_at=dt.datetime.fromisoformat(added_at),
    )
