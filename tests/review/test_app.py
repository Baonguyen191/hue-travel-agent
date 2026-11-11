from pathlib import Path

from fastapi.testclient import TestClient

from travel_agent.review.app import create_app


def client(db_path: Path) -> TestClient:
    return TestClient(create_app(db_path))


def test_index_serves_review_page(db_path: Path) -> None:
    response = client(db_path).get("/")
    assert response.status_code == 200
    assert "Duyệt địa điểm" in response.text


def test_list_pending_places_with_links(db_path: Path) -> None:
    body = client(db_path).get("/api/places", params={"status": "pending"}).json()
    assert body["total"] == 3
    museum = next(item for item in body["items"] if item["place"]["id"] == "osm:node/1")
    assert museum["status"] == "pending"
    assert museum["osm_url"] == "https://www.openstreetmap.org/node/1"
    assert museum["hours_parsed"] is True
    cafe = next(item for item in body["items"] if item["place"]["id"] == "osm:way/2")
    assert cafe["hours_parsed"] is None


def test_save_get_and_clear_review(db_path: Path) -> None:
    api = client(db_path)
    saved = api.put("/api/reviews", json={"place_id": "osm:node/1", "status": "approved"})
    assert saved.status_code == 200
    assert saved.json()["status"] == "approved"
    assert api.get("/api/stats").json()["approved"] == 1
    item = api.get("/api/place", params={"place_id": "osm:node/1"}).json()
    assert item["status"] == "approved"
    assert api.delete("/api/reviews", params={"place_id": "osm:node/1"}).status_code == 204
    assert api.get("/api/stats").json()["pending"] == 3


def test_unknown_place_is_404(db_path: Path) -> None:
    api = client(db_path)
    response = api.put("/api/reviews", json={"place_id": "osm:node/404", "status": "approved"})
    assert response.status_code == 404
    assert api.get("/api/place", params={"place_id": "osm:node/404"}).status_code == 404


def test_invalid_hours_override_is_422(db_path: Path) -> None:
    response = client(db_path).put(
        "/api/reviews",
        json={
            "place_id": "osm:node/1",
            "status": "approved",
            "opening_hours_override": "7h-17h",
            "evidence": "website",
        },
    )
    assert response.status_code == 422


def test_meta_lists_categories(db_path: Path) -> None:
    meta = client(db_path).get("/api/meta").json()
    assert "museum" in meta["categories"]
    assert meta["sources"] == {"osm": 3}
    assert meta["attribution"] == "© OpenStreetMap contributors"
