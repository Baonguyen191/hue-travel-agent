"""Configuration for the local, read-only Hue POI source."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[3]
# Root `.env` is intentionally local-only (`.gitignore` excludes it). Existing
# process environment variables take precedence, which is safer for deployment.
load_dotenv(PROJECT_ROOT / ".env")


def hue_database_path() -> Path:
    """Return the configured POI database path without creating it."""
    configured_path = os.environ.get("HUE_SQLITE_PATH")
    if configured_path:
        return Path(configured_path).expanduser()
    return Path(__file__).resolve().parents[2] / "data" / "hue.sqlite"


def openai_api_key() -> str | None:
    """Return the optional OpenAI key without exposing it in API responses."""
    return os.environ.get("OPENAI_API_KEY") or None
