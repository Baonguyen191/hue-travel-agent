from pathlib import Path

from fastapi.testclient import TestClient

from travel_agent.review.app import create_app


def client(tmp_path: Path) -> TestClient:
    return TestClient(create_app(tmp_path / "hue.sqlite"))


def test_links_page_is_served(tmp_path: Path) -> None:
    response = client(tmp_path).get("/links")
    assert response.status_code == 200
    assert "Nguồn dữ liệu" in response.text


def test_add_list_and_delete_links(tmp_path: Path) -> None:
    api = client(tmp_path)
    created = api.post(
        "/api/links",
        json={"urls": ["https://example.com/a", "https://example.com/b"], "topic": "sights"},
    )
    assert created.status_code == 201
    assert len(created.json()["added"]) == 2
    again = api.post("/api/links", json={"urls": ["https://example.com/a"]})
    assert again.json()["duplicates"] == ["https://example.com/a"]
    body = api.get("/api/links").json()
    assert body["counts"]["total"] == 2
    link_id = body["items"][0]["id"]
    assert api.delete(f"/api/links/{link_id}").status_code == 204
    assert api.delete(f"/api/links/{link_id}").status_code == 404
    assert api.get("/api/links").json()["counts"]["total"] == 1


def test_invalid_url_is_422(tmp_path: Path) -> None:
    response = client(tmp_path).post("/api/links", json={"urls": ["not a url"]})
    assert response.status_code == 422
