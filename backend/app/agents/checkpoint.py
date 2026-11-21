"""Checkpointer factory: SQLite file (default), Postgres URL, or in-memory for tests.

URL forms:
- `memory://`                   in-memory saver (tests only; lost on restart)
- `postgresql://...`            AsyncPostgresSaver
- `sqlite:///path` or a path    AsyncSqliteSaver on that file
`CHECKPOINT_URL` selects the target; unset means the default file under backend/data.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

DEFAULT_CHECKPOINT_PATH = Path(__file__).resolve().parents[2] / "data" / "checkpoints.sqlite"
_SQLITE_PREFIX = "sqlite:///"


def checkpoint_url() -> str:
    """Return the configured checkpoint URL, or the default SQLite file path."""
    return os.environ.get("CHECKPOINT_URL") or str(DEFAULT_CHECKPOINT_PATH)


def checkpoint_kind(url: str) -> str:
    """Classify a checkpoint URL as `memory`, `postgres` or `sqlite`."""
    if url.startswith("memory://"):
        return "memory"
    if url.startswith(("postgresql://", "postgres://")):
        return "postgres"
    return "sqlite"


def _sqlite_path(url: str) -> str:
    return url[len(_SQLITE_PREFIX) :] if url.startswith(_SQLITE_PREFIX) else url


@asynccontextmanager
async def open_checkpointer(url: str | None = None) -> AsyncIterator[BaseCheckpointSaver]:
    """Open the checkpointer for the lifetime of the `async with` block; close it on exit."""
    target = url or checkpoint_url()
    kind = checkpoint_kind(target)
    if kind == "memory":
        yield InMemorySaver()
        return
    if kind == "postgres":
        async with AsyncPostgresSaver.from_conn_string(target) as saver:
            await saver.setup()
            yield saver
        return
    path = Path(_sqlite_path(target))
    path.parent.mkdir(parents=True, exist_ok=True)
    async with AsyncSqliteSaver.from_conn_string(str(path)) as saver:
        await saver.setup()
        yield saver
