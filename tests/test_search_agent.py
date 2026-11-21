"""PHASE 4 Search Agent tests."""

from __future__ import annotations

import asyncio
import sys
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.agents.search import SearchAgent, is_hue_destination  # noqa: E402
from app.providers.hotel_mock import MockHotelProvider  # noqa: E402
from app.providers.transport_mock import MockTransportProvider  # noqa: E402
from app.repositories.hue_places import HuePlacesRepository  # noqa: E402
from app.schemas.request import TripRequest  # noqa: E402
from app.services.poi_search import normalize_vietnamese  # noqa: E402
from app.services.preferences import is_hue_specialty  # noqa: E402


def _request(**changes: object) -> TripRequest:
    values: dict[str, object] = {
        "origin": "Đà Nẵng",
        "destination": "Huế",
        "start_date": date(2026, 12, 10),
        "end_date": date(2026, 12, 12),
        "people": 2,
        "categories": ["historic"],
        "keyword": "dai noi",
    }
    values.update(changes)
    return TripRequest(**values)


def _agent(transport_mode: str = "normal", hotel_mode: str = "normal") -> SearchAgent:
    return SearchAgent(
        HuePlacesRepository(BACKEND / "data" / "hue.sqlite"),
        MockTransportProvider(transport_mode),  # type: ignore[arg-type]
        MockHotelProvider(hotel_mode),  # type: ignore[arg-type]
    )


def test_hue_scope_accepts_diacritics_but_rejects_another_destination() -> None:
    assert is_hue_destination("Huế")
    assert is_hue_destination("THÀNH PHỐ HUẾ")
    assert not is_hue_destination("Đà Nẵng")


def test_search_agent_combines_real_pois_with_mock_provider_offers() -> None:
    result = asyncio.run(_agent().search(_request()))

    assert result.status == "READY"
    assert result.poi_candidates[0].place.name == "Đại Nội Huế"
    assert all(item.place.category == "historic" for item in result.poi_candidates)
    assert len(result.transport_offers) == 6
    assert len(result.hotel_offers) == 3
    assert {offer.mode for offer in result.transport_offers} == {"BUS", "TRAIN", "FLIGHT"}
    assert {offer.tier for offer in result.hotel_offers} == {"HOMESTAY", "THREE_STAR", "FOUR_STAR"}
    assert all(offer.source == "MOCK" for offer in result.transport_offers + result.hotel_offers)
    assert result.warnings == []


def test_empty_and_timeout_providers_yield_warnings_not_invented_quotes() -> None:
    result = asyncio.run(_agent("timeout", "empty").search(_request()))

    assert result.status == "PARTIAL"
    assert result.poi_candidates
    assert result.transport_offers == []
    assert result.hotel_offers == []
    assert any("timed out" in warning for warning in result.warnings)
    assert any("No hotel quote" in warning for warning in result.warnings)


def test_unsupported_destination_returns_no_poi_or_provider_data() -> None:
    result = asyncio.run(_agent().search(_request(destination="Đà Nẵng")))

    assert result.status == "UNSUPPORTED_DESTINATION"
    assert result.poi_candidates == []
    assert result.transport_offers == []
    assert result.hotel_offers == []


def test_dod_preferences_return_historic_and_restaurant_candidates() -> None:
    request = _request(categories=[], keyword=None, preferences=["di tích", "đặc sản"])
    result = asyncio.run(_agent().search(request))

    categories = [item.place.category for item in result.poi_candidates]
    assert "historic" in categories
    assert "restaurant" in categories
    assert categories[0] != categories[1]


def test_explicit_categories_are_all_represented() -> None:
    request = _request(categories=["historic", "restaurant"], keyword=None)
    result = asyncio.run(_agent().search(request))

    categories = {item.place.category for item in result.poi_candidates}
    assert {"historic", "restaurant"} <= categories


def test_keyword_hint_quan_ca_phe_ranks_cafes_first() -> None:
    result = asyncio.run(_agent().search(_request(categories=[], keyword="quan ca phe")))

    top = result.poi_candidates[:3]
    assert len(top) == 3
    assert all(item.place.category == "cafe" for item in top)


def test_no_filters_put_a_hue_specialty_restaurant_first_among_restaurants() -> None:
    result = asyncio.run(_agent().search(_request(categories=[], keyword=None)))

    restaurants = [item for item in result.poi_candidates if item.place.category == "restaurant"]
    assert restaurants
    assert is_hue_specialty(restaurants[0].place)


def test_dod_candidates_have_no_duplicate_normalized_names() -> None:
    request = _request(categories=[], keyword=None, preferences=["di tích", "đặc sản"])
    result = asyncio.run(_agent().search(request))

    names = [normalize_vietnamese(item.place.name) for item in result.poi_candidates]
    assert len(names) == len(set(names))
