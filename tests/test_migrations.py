"""Alembic: models match head, downgrade/upgrade round trip, PlanStore on a migrated file DB."""

from __future__ import annotations

import sys
from pathlib import Path

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.db.migrate import downgrade_to_base, upgrade_to_head  # noqa: E402
from app.db.store import Base, PlanStore  # noqa: E402

APP_TABLES = {"trips", "plan_versions", "approvals", "booking_intents"}


def _file_url(tmp_path: Path, name: str = "migrated.sqlite") -> str:
    return f"sqlite:///{(tmp_path / name).as_posix()}"


def _table_names(url: str) -> set[str]:
    engine = create_engine(url)
    try:
        return set(inspect(engine).get_table_names())
    finally:
        engine.dispose()


def test_empty_file_migrated_to_head_matches_the_models(tmp_path: Path) -> None:
    url = _file_url(tmp_path)

    upgrade_to_head(url)

    engine = create_engine(url)
    try:
        with engine.connect() as connection:
            differences = compare_metadata(MigrationContext.configure(connection), Base.metadata)
    finally:
        engine.dispose()
    assert differences == []


def test_upgrade_creates_exactly_the_four_app_tables(tmp_path: Path) -> None:
    url = _file_url(tmp_path)

    upgrade_to_head(url)

    assert _table_names(url) == APP_TABLES | {"alembic_version"}


def test_upgrade_twice_is_a_no_op(tmp_path: Path) -> None:
    url = _file_url(tmp_path)
    upgrade_to_head(url)

    upgrade_to_head(url)

    assert _table_names(url) == APP_TABLES | {"alembic_version"}


def test_downgrade_to_base_then_upgrade_to_head_round_trips(tmp_path: Path) -> None:
    url = _file_url(tmp_path)
    upgrade_to_head(url)

    downgrade_to_base(url)
    assert _table_names(url) <= {"alembic_version"}

    upgrade_to_head(url)
    assert APP_TABLES <= _table_names(url)


def test_plan_store_without_create_schema_leaves_an_empty_file_untouched(tmp_path: Path) -> None:
    url = _file_url(tmp_path, "bare.sqlite")

    PlanStore(url)

    assert _table_names(url) == set()


def test_plan_store_create_schema_true_builds_the_tables(tmp_path: Path) -> None:
    url = _file_url(tmp_path, "created.sqlite")

    PlanStore(url, create_schema=True)

    assert APP_TABLES <= _table_names(url)


def test_plan_store_works_on_a_migrated_file_db(tmp_path: Path) -> None:
    url = _file_url(tmp_path, "store.sqlite")
    upgrade_to_head(url)

    store = PlanStore(url)
    plan_id, version = store.save_plan("migrated-thread", {"budget": {"options": []}})
    latest = store.latest("migrated-thread")

    assert version == 1
    assert latest is not None
    assert latest["plan_id"] == plan_id
    assert latest["version"] == 1
    assert latest["owner_id"] == "anonymous"
