"""Settings: absolute CWD-independent defaults, URL validation and lifespan refusal."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.core import config  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("CHECKPOINT_URL", raising=False)
    return monkeypatch


def test_data_dir_is_the_backend_data_folder() -> None:
    assert config.BACKEND_DIR == BACKEND
    assert config.DATA_DIR == BACKEND / "data"


def test_default_database_url_is_absolute_and_independent_of_cwd(
    clean_env: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    clean_env.chdir(tmp_path)

    url = config.database_url()

    database_path = Path(make_url(url).database)
    assert url.startswith("sqlite:///")
    assert database_path.is_absolute()
    assert database_path == config.DATA_DIR / "travel_state.sqlite"


def test_default_checkpoint_url_is_absolute_and_independent_of_cwd(
    clean_env: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    clean_env.chdir(tmp_path)

    target = Path(config.checkpoint_url())

    assert target.is_absolute()
    assert target == config.DATA_DIR / "checkpoints.sqlite"


def test_environment_overrides_both_urls(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("DATABASE_URL", "postgresql+psycopg://u:p@db:5432/app")
    clean_env.setenv("CHECKPOINT_URL", "postgresql://u:p@db:5432/app")

    assert config.database_url() == "postgresql+psycopg://u:p@db:5432/app"
    assert config.checkpoint_url() == "postgresql://u:p@db:5432/app"


def test_defaults_pass_validation(clean_env: pytest.MonkeyPatch) -> None:
    assert config.validate_settings() == []


def test_unsupported_database_scheme_is_reported(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("DATABASE_URL", "mysql://u:p@db/app")

    problems = config.validate_settings()

    assert len(problems) == 1
    assert "DATABASE_URL" in problems[0]


def test_unparseable_database_url_is_reported(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("DATABASE_URL", "travel.db")

    problems = config.validate_settings()

    assert any("DATABASE_URL" in problem for problem in problems)


@pytest.mark.parametrize(
    "value",
    ["memory://", "postgresql://u:p@db/app", "sqlite:///C:/tmp/cp.sqlite", "C:/tmp/cp.sqlite"],
)
def test_accepted_checkpoint_forms(clean_env: pytest.MonkeyPatch, value: str) -> None:
    clean_env.setenv("CHECKPOINT_URL", value)

    assert config.validate_settings() == []


def test_unsupported_checkpoint_scheme_is_reported(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("CHECKPOINT_URL", "redis://cache:6379/0")

    problems = config.validate_settings()

    assert len(problems) == 1
    assert "CHECKPOINT_URL" in problems[0]


def test_openai_key_is_only_a_note(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.delenv("OPENAI_API_KEY", raising=False)

    assert config.validate_settings() == []
    assert any("OPENAI_API_KEY" in note for note in config.settings_notes())


def test_lifespan_refuses_to_start_on_invalid_settings(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("DATABASE_URL", "mysql://u:p@db/app")

    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        with TestClient(app):
            pass
