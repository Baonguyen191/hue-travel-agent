"""Configuration: data paths, database and checkpoint URLs, and startup validation.

Every default path is absolute and built from `BACKEND_DIR`, so the app behaves the
same whatever the current working directory is.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

PROJECT_ROOT = Path(__file__).resolve().parents[3]
BACKEND_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = BACKEND_DIR / "data"
# Root `.env` is intentionally local-only (`.gitignore` excludes it). Existing
# process environment variables take precedence, which is safer for deployment.
load_dotenv(PROJECT_ROOT / ".env")

SUPPORTED_DATABASE_DRIVERS = frozenset({"sqlite", "postgresql+psycopg"})
SUPPORTED_CHECKPOINT_PREFIXES = ("memory://", "postgresql://", "sqlite:///")


def hue_database_path() -> Path:
    """Return the configured POI database path without creating it."""
    configured_path = os.environ.get("HUE_SQLITE_PATH")
    if configured_path:
        return Path(configured_path).expanduser()
    return DATA_DIR / "hue.sqlite"


def database_url() -> str:
    """Return the state database URL: `DATABASE_URL`, or the absolute default SQLite file."""
    configured = os.environ.get("DATABASE_URL")
    if configured:
        return configured
    return f"sqlite:///{(DATA_DIR / 'travel_state.sqlite').as_posix()}"


def checkpoint_url() -> str:
    """Return the checkpoint target: `CHECKPOINT_URL`, or the absolute default SQLite file."""
    return os.environ.get("CHECKPOINT_URL") or str(DATA_DIR / "checkpoints.sqlite")


def openai_api_key() -> str | None:
    """Return the optional OpenAI key without exposing it in API responses."""
    return os.environ.get("OPENAI_API_KEY") or None


def _database_problem(url: str) -> str | None:
    try:
        driver = make_url(url).drivername
    except ArgumentError:
        return "DATABASE_URL is not a valid SQLAlchemy URL."
    if driver in SUPPORTED_DATABASE_DRIVERS:
        return None
    return f"DATABASE_URL scheme '{driver}' is unsupported; use sqlite:///... or postgresql+psycopg://..."


def _checkpoint_problem(url: str) -> str | None:
    if url.startswith(SUPPORTED_CHECKPOINT_PREFIXES) or "://" not in url:
        return None
    return "CHECKPOINT_URL must be memory://, postgresql://, sqlite:///<file> or a file path."


def validate_settings() -> list[str]:
    """Return every configuration problem; an empty list means the settings are usable."""
    problems = [_database_problem(database_url()), _checkpoint_problem(checkpoint_url())]
    return [problem for problem in problems if problem is not None]


def settings_notes() -> list[str]:
    """Return informational notes that never stop the app from starting."""
    if openai_api_key() is None:
        return ["OPENAI_API_KEY is not set; the request parser uses rules only."]
    return []


def ollama_url() -> str:
    """Base URL of the local Ollama server used by the query understanding step."""
    return os.environ.get("OLLAMA_URL") or "http://localhost:11434"


def qu_model() -> str:
    """Ollama model that extracts phrases from user messages."""
    return os.environ.get("QU_MODEL") or "qwen3.5:4b"


def qu_enabled() -> bool:
    """False turns the LLM step off so the rule parser answers alone (tests and offline use)."""
    value = os.environ.get("QU_ENABLED")
    if value is None or not value.strip():
        return True
    return value.strip().lower() not in {"0", "false", "no", "off"}
