"""Alembic environment: the app's database URL and the models' metadata."""

from __future__ import annotations

import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import create_engine, pool

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.chat import models as chat_models  # noqa: E402, F401  (registers the chat tables)
from app.core.config import database_url  # noqa: E402
from app.db.store import Base, enable_sqlite_foreign_keys  # noqa: E402

config = context.config
# Logging is configured from alembic.ini only for the CLI; the app opts out so that
# migrating at startup does not reset uvicorn's loggers.
if config.config_file_name is not None and config.attributes.get("configure_logger", True):
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def _database_url() -> str:
    return config.get_main_option("sqlalchemy.url") or database_url()


def run_migrations_offline() -> None:
    """Emit SQL without a connection (`alembic upgrade --sql`)."""
    url = _database_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        render_as_batch=url.startswith("sqlite"),
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run the migrations on one connection; SQLite uses batch mode for ALTERs."""
    engine = create_engine(_database_url(), poolclass=pool.NullPool)
    if engine.dialect.name == "sqlite":
        enable_sqlite_foreign_keys(engine)
    try:
        with engine.connect() as connection:
            context.configure(
                connection=connection,
                target_metadata=target_metadata,
                render_as_batch=connection.dialect.name == "sqlite",
            )
            with context.begin_transaction():
                context.run_migrations()
    finally:
        engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
