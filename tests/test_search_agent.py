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
from app.services.preferences import (  # noqa: E402
    is_hue_specialty,
    is_nature,
    is_view_cafe,
)


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


class _CountingTransport(MockTransportProvider):
    """Counts provider calls so a test can prove the provider was never reached."""

    def __init__(self) -> None:
        super().__init__()
        self.calls = 0

    def search(self, request):  # type: ignore[override]
        self.calls += 1
        return super().search(request)


def test_hue_origin_skips_the_transport_provider_and_reports_no_transport_gap() -> None:
    transport = _CountingTransport()
    agent = SearchAgent(HuePlacesRepository(BACKEND / "data" / "hue.sqlite"), transport, MockHotelProvider())

    result = asyncio.run(agent.search(_request(origin="Huế")))

    assert transport.calls == 0
    assert result.transport_offers == []
    assert not any("transport" in warning.lower() for warning in result.warnings)
    assert len(result.hotel_offers) == 3


def test_nature_theme_keeps_bridges_parks_and_malls_out_of_the_candidates() -> None:
    request = _request(
        keyword=None,
        categories=["restaurant", "cafe", "market", "attraction"],
        themes=["nature"],
        preferences=["ẩm thực", "thiên nhiên", "ngắm cảnh"],
    )
    result = asyncio.run(_agent().search(request))
    names = [normalize_vietnamese(item.place.name) for item in result.poi_candidates]
    attractions = [item.place for item in result.poi_candidates if item.place.category == "attraction"]
    cafes = [item.place for item in result.poi_candidates if item.place.category == "cafe"]

    assert result.poi_candidates
    assert "park" not in {item.place.category for item in result.poi_candidates}
    assert not [name for name in names if "vincom" in name or "sieu thi" in name or "go!" in name]
    flags = [is_nature(place) for place in attractions]
    assert flags and flags == sorted(flags, reverse=True)  # nature places first
    assert cafes and is_view_cafe(cafes[0])


def test_transport_mode_train_keeps_only_train_offers_on_both_legs() -> None:
    result = asyncio.run(_agent().search(_request(transport_mode="train")))

    assert result.transport_offers
    assert {offer.mode for offer in result.transport_offers} == {"TRAIN"}
    assert {offer.leg for offer in result.transport_offers} == {"OUTBOUND", "RETURN"}
    assert not any("mode" in warning for warning in result.warnings)


def test_hotel_tier_homestay_keeps_only_the_homestay() -> None:
    result = asyncio.run(_agent().search(_request(hotel_tier="homestay")))

    assert [offer.tier for offer in result.hotel_offers] == ["HOMESTAY"]


def test_unset_mode_and_tier_keep_every_provider_offer() -> None:
    result = asyncio.run(_agent().search(_request()))

    assert {offer.mode for offer in result.transport_offers} == {"BUS", "TRAIN", "FLIGHT"}
    assert len(result.hotel_offers) == 3


class _NoFlightTransportProvider:
    """A provider that offers bus and train only, so a flight choice has nothing to match."""

    def search(self, request):  # type: ignore[no-untyped-def]
        return [offer for offer in MockTransportProvider().search(request) if offer.mode != "FLIGHT"]


def test_mode_no_provider_offers_keeps_all_offers_and_warns() -> None:
    agent = SearchAgent(
        HuePlacesRepository(BACKEND / "data" / "hue.sqlite"),
        _NoFlightTransportProvider(),  # type: ignore[arg-type]
        MockHotelProvider(),
    )
    result = asyncio.run(agent.search(_request(transport_mode="flight")))

    assert {offer.mode for offer in result.transport_offers} == {"BUS", "TRAIN"}
    assert "No FLIGHT offer is available; showing all transport modes." in result.warnings
    assert result.status == "PARTIAL"


class _NoResortHotelProvider:
    """A provider with homestays and three-star hotels only."""

    def search(self, request):  # type: ignore[no-untyped-def]
        return [offer for offer in MockHotelProvider().search(request) if offer.tier != "FOUR_STAR"]


def test_tier_no_hotel_offers_keeps_all_hotels_and_warns() -> None:
    agent = SearchAgent(
        HuePlacesRepository(BACKEND / "data" / "hue.sqlite"),
        MockTransportProvider(),
        _NoResortHotelProvider(),  # type: ignore[arg-type]
    )
    result = asyncio.run(agent.search(_request(hotel_tier="resort")))

    assert {offer.tier for offer in result.hotel_offers} == {"HOMESTAY", "THREE_STAR"}
    assert "No FOUR_STAR offer is available; showing all hotel tiers." in result.warnings
