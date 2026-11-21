from __future__ import annotations

import sys
from pathlib import Path

from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from app.main import app  # noqa: E402


def test_health_reports_read_only_database_available(monkeypatch) -> None:
    monkeypatch.delenv("HUE_SQLITE_PATH", raising=False)

    response = TestClient(app).get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "database": "hue.sqlite",
        "access": "read-only",
    }


def test_health_reports_missing_database(monkeypatch) -> None:
    missing_path = ROOT / "backend" / "data" / "missing-for-health-test.sqlite"
    monkeypatch.setenv("HUE_SQLITE_PATH", str(missing_path))

    response = TestClient(app).get("/health")

    assert response.status_code == 503
    assert response.json()["status"] == "unavailable"
    assert "missing" in response.json()["detail"].lower()
