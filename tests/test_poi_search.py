"""PHASE 2 local-search tests."""

from __future__ import annotations

import sys
from pathlib import Path

from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.main import app  # noqa: E402
from app.services.poi_search import haversine_km, normalize_vietnamese  # noqa: E402


def test_normalize_vietnamese_is_diacritic_insensitive() -> None:
    assert normalize_vietnamese("  ĐẠI  NỘI Huế ") == "dai noi hue"
    assert normalize_vietnamese("cà-phê") == "ca-phe"


def test_haversine_returns_zero_for_same_coordinate() -> None:
    assert haversine_km(16.47, 107.58, 16.47, 107.58) == 0


def test_search_finds_diacritic_insensitive_name_and_rejects_gibberish() -> None:
    client = TestClient(app)

    found = client.get("/api/v1/places/search", params={"q": "dai noi", "limit": 5})
    absent = client.get("/api/v1/places/search", params={"q": "zzzxqv impossible place"})

    assert found.status_code == 200
    assert found.json()["total"] >= 1
    assert found.json()["items"][0]["place"]["name"] == "Đại Nội Huế"
    assert found.json()["items"][0]["score"] > 70
    assert absent.status_code == 200
    assert absent.json()["items"] == []
    assert absent.json()["total"] == 0


def test_nearby_applies_radius_and_paginates_by_distance() -> None:
    client = TestClient(app)
    params = {"lat": 16.47, "lon": 107.58, "radius_km": 1, "limit": 3}

    response = client.get("/api/v1/places/nearby", params=params)
    second_page = client.get("/api/v1/places/nearby", params={**params, "offset": 3})

    assert response.status_code == 200
    body = response.json()
    assert body["total"] > 3
    assert len(body["items"]) == 3
    assert all(item["distance_km"] <= 1 for item in body["items"])
    assert body["items"] == sorted(body["items"], key=lambda item: item["distance_km"])
    assert second_page.status_code == 200
    assert second_page.json()["items"][0]["place"]["id"] != body["items"][0]["place"]["id"]


def test_search_rejects_incomplete_coordinate_pair() -> None:
    response = TestClient(app).get("/api/v1/places/search", params={"q": "dai noi", "lat": 16.47})

    assert response.status_code == 422
    assert "lat and lon" in response.json()["detail"]
