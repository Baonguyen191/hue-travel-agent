from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

import app.main as main  # noqa: E402

INDEX_HTML = "<!doctype html><html><body><div id=root>SPA</div></body></html>"


@pytest.fixture
def dist(tmp_path: Path, monkeypatch) -> Path:
    """A temporary frontend build: index.html plus one hashed asset, and a secret outside dist."""
    build = tmp_path / "dist"
    (build / "assets").mkdir(parents=True)
    (build / "index.html").write_text(INDEX_HTML, encoding="utf-8")
    (build / "assets" / "app-abc123.js").write_text("console.log('asset');", encoding="utf-8")
    (tmp_path / "secret.txt").write_text("TOP SECRET", encoding="utf-8")
    monkeypatch.setattr(main, "FRONTEND_DIST", build)
    return build


def test_root_serves_index(dist: Path) -> None:
    with TestClient(main.app) as client:
        response = client.get("/")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "SPA" in response.text


def test_deep_link_serves_index_html(dist: Path) -> None:
    with TestClient(main.app) as client:
        response = client.get("/explore/huetripo:531787")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "SPA" in response.text


def test_asset_file_is_served_from_dist(dist: Path) -> None:
    with TestClient(main.app) as client:
        response = client.get("/assets/app-abc123.js")

    assert response.status_code == 200
    assert "console.log('asset');" in response.text


def test_path_traversal_does_not_leave_dist(dist: Path) -> None:
    with TestClient(main.app) as client:
        response = client.get("/..%2Fsecret.txt")

    assert response.status_code == 200
    assert "TOP SECRET" not in response.text
    assert "SPA" in response.text


def test_unknown_api_path_stays_json_404(dist: Path) -> None:
    with TestClient(main.app) as client:
        response = client.get("/api/v1/does-not-exist")

    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/json")
    assert response.json() == {"detail": "Not Found"}


def test_api_root_stays_json_404(dist: Path) -> None:
    with TestClient(main.app) as client:
        response = client.get("/api")

    assert response.status_code == 404
    assert response.json() == {"detail": "Not Found"}


def test_health_is_not_shadowed_by_the_fallback(dist: Path) -> None:
    with TestClient(main.app) as client:
        response = client.get("/health")

    assert response.headers["content-type"].startswith("application/json")
    assert set(response.json()) >= {"status", "components"}


def test_api_routers_still_answer_before_the_fallback(dist: Path) -> None:
    with TestClient(main.app) as client:
        response = client.get("/api/v1/plans/no-such-thread")

    assert response.status_code == 404
    assert response.json() == {"detail": "Plan thread was not found."}


def test_missing_dist_gives_json_404_for_client_routes(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(main, "FRONTEND_DIST", tmp_path / "no-build-here")

    with TestClient(main.app) as client:
        response = client.get("/explore")

    assert response.status_code == 404
    assert response.json() == {"detail": "Not Found"}


def test_dist_without_index_gives_json_404(tmp_path: Path, monkeypatch) -> None:
    empty = tmp_path / "dist"
    empty.mkdir()
    monkeypatch.setattr(main, "FRONTEND_DIST", empty)

    with TestClient(main.app) as client:
        response = client.get("/plan/abc")

    assert response.status_code == 404
    assert response.json() == {"detail": "Not Found"}
