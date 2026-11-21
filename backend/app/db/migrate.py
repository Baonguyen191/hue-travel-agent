"""Run Alembic migrations programmatically against a database URL."""

from __future__ import annotations

from alembic import command
from alembic.config import Config

from app.core.config import BACKEND_DIR

ALEMBIC_INI = BACKEND_DIR / "alembic.ini"


def alembic_config(url: str) -> Config:
    """Build an Alembic Config for `alembic.ini` pointing at the given database URL."""
    config = Config(str(ALEMBIC_INI))
    # Escape `%` so configparser does not treat a URL-encoded password as interpolation.
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    config.attributes["configure_logger"] = False
    return config


def upgrade_to_head(url: str) -> None:
    """Bring the database at `url` up to the latest revision; safe to run on every start."""
    command.upgrade(alembic_config(url), "head")


def downgrade_to_base(url: str) -> None:
    """Remove every revision's schema (used by the round-trip test)."""
    command.downgrade(alembic_config(url), "base")
