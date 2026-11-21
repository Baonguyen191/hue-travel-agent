"""SQLite foreign-key enforcement and parent-before-child insert order in PlanStore."""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.db.store import PlanStore, PlanVersion  # noqa: E402


def _foreign_keys_pragma(store: PlanStore) -> int:
    with store.engine.connect() as connection:
        return int(connection.execute(text("PRAGMA foreign_keys")).scalar_one())


def test_fresh_in_memory_store_enforces_foreign_keys() -> None:
    store = PlanStore("sqlite://")

    assert _foreign_keys_pragma(store) == 1


def test_file_backed_store_enforces_foreign_keys(tmp_path: Path) -> None:
    store = PlanStore(f"sqlite:///{(tmp_path / 'fk.sqlite').as_posix()}", create_schema=True)

    assert _foreign_keys_pragma(store) == 1


def test_plan_version_with_unknown_trip_is_rejected() -> None:
    store = PlanStore("sqlite://")
    orphan = PlanVersion(
        id="orphan-plan",
        trip_id="no-such-trip",
        version=1,
        payload="{}",
        created_at=datetime.now(timezone.utc),
    )

    with Session(store.engine) as session:
        session.add(orphan)
        with pytest.raises(IntegrityError):
            session.commit()


def test_save_plan_on_a_new_thread_inserts_trip_before_plan_version() -> None:
    store = PlanStore("sqlite://")

    plan_id, version = store.save_plan("fk-thread", {"n": 1})

    assert version == 1
    assert store.latest("fk-thread")["plan_id"] == plan_id
