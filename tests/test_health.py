from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from app.main import app  # noqa: E402


def test_health_reports_every_component_ok(monkeypatch) -> None:
    monkeypatch.delenv("HUE_SQLITE_PATH", raising=False)

    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["components"]["hue_source"] == {
        "ok": True,
        "detail": None,
        "database": "hue.sqlite",
        "access": "read-only",
    }
    assert body["components"]["state_db"] == {"ok": True, "detail": None}
    assert body["components"]["checkpoint"] == {"ok": True, "detail": None}


def test_health_reports_missing_database(monkeypatch) -> None:
    missing_path = ROOT / "backend" / "data" / "missing-for-health-test.sqlite"
    monkeypatch.setenv("HUE_SQLITE_PATH", str(missing_path))

    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "unavailable"
    assert body["components"]["hue_source"]["ok"] is False
    assert "missing" in body["components"]["hue_source"]["detail"].lower()
    assert body["components"]["state_db"]["ok"] is True


def test_health_is_503_when_the_state_database_is_unreachable(monkeypatch) -> None:
    monkeypatch.delenv("HUE_SQLITE_PATH", raising=False)
    unreachable = create_engine("sqlite:///" + str(ROOT / "no-such-dir" / "state.sqlite").replace("\\", "/"))

    with TestClient(app) as client:
        monkeypatch.setattr(app.state.store, "engine", unreachable)
        response = client.get("/health")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "unavailable"
    assert body["components"]["state_db"]["ok"] is False
    assert body["components"]["state_db"]["detail"]
    assert body["components"]["hue_source"]["ok"] is True
    unreachable.dispose()


def test_health_is_503_when_the_checkpointer_is_not_open(monkeypatch) -> None:
    monkeypatch.delenv("HUE_SQLITE_PATH", raising=False)
    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 503
    assert response.json()["components"]["checkpoint"]["ok"] is False
