"""Component checks behind `GET /health`: Hue source, state database and checkpointer.

Each check returns `{"ok": bool, "detail": str | None, ...}`. Details are fixed,
human-readable messages; they never echo connection strings or credentials.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import psycopg
from langgraph.checkpoint.base import BaseCheckpointSaver
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.agents.checkpoint import checkpoint_kind
from app.db.store import PlanStore

POSTGRES_CONNECT_TIMEOUT_SECONDS = 3


def component(ok: bool, detail: str | None = None, **extra: Any) -> dict[str, Any]:
    """Build one component entry; `extra` carries component-specific keys."""
    return {"ok": ok, "detail": detail, **extra}


def can_open_read_only(database_path: Path) -> tuple[bool, str | None]:
    """Confirm that SQLite can read the database without creating side files."""
    if not database_path.is_file():
        return False, "Hue SQLite source file is missing."

    try:
        connection = sqlite3.connect(database_path.resolve().as_uri() + "?mode=ro", uri=True)
        try:
            connection.execute("SELECT 1").fetchone()
        finally:
            connection.close()
    except sqlite3.Error:
        return False, "Hue SQLite source file cannot be opened read-only."
    return True, None


def hue_source_status(database_path: Path) -> dict[str, Any]:
    """The read-only POI source; keeps the original `database` and `access` keys."""
    available, detail = can_open_read_only(database_path)
    return component(available, detail, database="hue.sqlite", access="read-only")


def state_db_status(store: PlanStore | None) -> dict[str, Any]:
    """Run `SELECT 1` through the plan store's engine; a store that is not open is down."""
    if store is None:
        return component(False, "State database is not open.")
    engine = store.engine
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except SQLAlchemyError:
        return component(False, "State database is unreachable.")
    return component(True)


def checkpoint_status(checkpointer: BaseCheckpointSaver | None, url: str | None) -> dict[str, Any]:
    """The lifespan checkpointer must be open; Postgres also answers `SELECT 1`."""
    if checkpointer is None or url is None:
        return component(False, "Checkpointer is not open.")
    if checkpoint_kind(url) == "postgres":
        return _postgres_ping(url)
    return component(True)


def _postgres_ping(url: str) -> dict[str, Any]:
    try:
        with psycopg.connect(url, connect_timeout=POSTGRES_CONNECT_TIMEOUT_SECONDS) as connection:
            connection.execute("SELECT 1")
    except psycopg.Error:
        return component(False, "Checkpoint database is unreachable.")
    return component(True)
