"""End-to-end checks for PHASE 1 read-only POI retrieval."""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
DATABASE_PATH = BACKEND / "data" / "hue.sqlite"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.main import app  # noqa: E402
from app.repositories.hue_places import HuePlacesRepository  # noqa: E402
from app.services.normalize_hue import (  # noqa: E402
    parse_attributes,
    parse_rating,
    parse_reference_price_range,
    parse_visit_minutes,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_repository_normalizes_every_source_record_without_mutating_database() -> None:
    before = _sha256(DATABASE_PATH)
    repository = HuePlacesRepository(DATABASE_PATH)

    places = repository.list_all()

    assert len(places) == 1587
    assert len({place.id for place in places}) == 1587
    assert {place.category for place in places} == {
        "attraction",
        "cafe",
        "historic",
        "market",
        "museum",
        "park",
        "religious",
        "restaurant",
    }
    assert all(place.source == "huetripo.hue.gov.vn" for place in places)
    assert all(isinstance(place.raw_attributes, dict) for place in places)
    assert _sha256(DATABASE_PATH) == before


def test_repository_retrieves_exact_source_id_and_category_page() -> None:
    repository = HuePlacesRepository(DATABASE_PATH)

    place = repository.get_by_id("huetripo:032904")
    restaurants = repository.list_page(category="restaurant", limit=3, offset=0)

    assert place is not None
    assert place.id == "huetripo:032904"
    assert place.rating_value == 4.9
    assert place.rating_count == 132
    assert place.price_min_vnd == 100_000
    assert place.price_max_vnd == 200_000
    assert repository.get_by_id("huetripo:not-present") is None
    assert len(restaurants) == 3
    assert all(item.category == "restaurant" for item in restaurants)
    assert repository.count(category="restaurant") == 826


def test_normalizers_leave_malformed_or_missing_source_values_unknown() -> None:
    assert parse_attributes("{") == {}
    assert parse_attributes("[]") == {}
    assert parse_rating("not a rating") == (None, None, None)
    assert parse_rating("6.0/5 (3 lượt, Google)") == (None, None, None)
    assert parse_visit_minutes("0") is None
    assert parse_visit_minutes("about 60") is None
    assert parse_reference_price_range("liên hệ") == (None, None, None)
    assert parse_reference_price_range("50.000đ – 100.000đ") == (
        50_000,
        100_000,
        "UNKNOWN",
    )


def test_places_api_lists_filters_and_returns_not_found() -> None:
    client = TestClient(app)

    listing = client.get("/api/v1/places", params={"category": "museum", "limit": 2})
    detail = client.get("/api/v1/places/huetripo:032904")
    missing = client.get("/api/v1/places/huetripo:not-present")
    invalid_category = client.get("/api/v1/places", params={"category": "beach"})

    assert listing.status_code == 200
    assert listing.json()["total"] == 8
    assert len(listing.json()["items"]) == 2
    assert all(item["category"] == "museum" for item in listing.json()["items"])
    assert detail.status_code == 200
    assert detail.json()["id"] == "huetripo:032904"
    assert missing.status_code == 404
    assert invalid_category.status_code == 422
