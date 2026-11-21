"""Checkpointer factory: URL routing and opening. No Postgres server is contacted."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.agents.checkpoint import (  # noqa: E402
    DEFAULT_CHECKPOINT_PATH,
    checkpoint_kind,
    open_checkpointer,
)


def test_url_routing_picks_memory_postgres_or_sqlite() -> None:
    assert checkpoint_kind("memory://") == "memory"
    assert checkpoint_kind("postgresql://user:pw@db/app") == "postgres"
    assert checkpoint_kind("postgres://user:pw@db/app") == "postgres"
    assert checkpoint_kind("sqlite:///C:/tmp/cp.sqlite") == "sqlite"
    assert checkpoint_kind("C:/tmp/cp.sqlite") == "sqlite"


def test_default_path_is_the_backend_data_checkpoint_file() -> None:
    assert DEFAULT_CHECKPOINT_PATH == BACKEND / "data" / "checkpoints.sqlite"


def test_memory_url_opens_an_in_memory_saver() -> None:
    async def scenario() -> type:
        async with open_checkpointer("memory://") as saver:
            return type(saver)

    assert asyncio.run(scenario()) is InMemorySaver


def test_file_url_opens_a_sqlite_saver_on_that_file(tmp_path: Path) -> None:
    target = tmp_path / "cp.sqlite"

    async def scenario() -> type:
        async with open_checkpointer(str(target)) as saver:
            return type(saver)

    assert asyncio.run(scenario()) is AsyncSqliteSaver
    assert target.is_file()
