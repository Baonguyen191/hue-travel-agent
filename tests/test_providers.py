"""PHASE 3 provider-contract and mock-fixture tests."""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.providers.base import ProviderTimeoutError  # noqa: E402
from app.providers.hotel_mock import MockHotelProvider  # noqa: E402
from app.providers.routes_estimator import HaversineRouteEstimator  # noqa: E402
from app.providers.transport_mock import MockTransportProvider  # noqa: E402
from app.schemas.offer import Coordinates, HotelSearchRequest, TransportSearchRequest  # noqa: E402


def _transport_request() -> TransportSearchRequest:
    return TransportSearchRequest(
        origin="Đà Nẵng", destination="Huế", departure_date=date(2026, 12, 10), return_date=date(2026, 12, 12), passengers=2
    )


def _hotel_request() -> HotelSearchRequest:
    return HotelSearchRequest(
        destination="Huế", check_in=date(2026, 12, 10), check_out=date(2026, 12, 12), rooms=1, guests=2
    )


def test_mock_transport_has_explicit_mock_provenance_and_per_leg_unit() -> None:
    offers = MockTransportProvider().search(_transport_request())

    modes_by_leg = {
        leg: {offer.mode for offer in offers if offer.leg == leg} for leg in ("OUTBOUND", "RETURN")
    }

    assert len(offers) == 6
    assert modes_by_leg == {
        "OUTBOUND": {"BUS", "TRAIN", "FLIGHT"},
        "RETURN": {"BUS", "TRAIN", "FLIGHT"},
    }
    assert all(offer.source == "MOCK" for offer in offers)
    assert all(offer.price_unit == "VND_PER_PERSON_PER_LEG" for offer in offers)
    bus_offers = [offer for offer in offers if offer.mode == "BUS"]
    assert sum(offer.price_vnd for offer in bus_offers) == 800_000


def test_mock_hotel_represents_two_nights_with_a_per_room_night_price() -> None:
    offers = MockHotelProvider().search(_hotel_request())
    offer = next(item for item in offers if item.tier == "THREE_STAR")

    assert {item.tier for item in offers} == {"HOMESTAY", "THREE_STAR", "FOUR_STAR"}
    assert len(offers) == 3
    assert offer.id == "mock-hotel-riverside-deluxe"
    assert offer.source == "MOCK"
    assert offer.nights == 2
    assert offer.price_unit == "VND_PER_ROOM_PER_NIGHT"
    assert offer.price_per_room_night_vnd * offer.nights == 1_300_000


@pytest.mark.parametrize("provider", [MockTransportProvider("empty"), MockHotelProvider("empty")])
def test_empty_mock_providers_return_no_offers(provider: object) -> None:
    request = _transport_request() if isinstance(provider, MockTransportProvider) else _hotel_request()
    assert provider.search(request) == []  # type: ignore[union-attr]


@pytest.mark.parametrize("provider", [MockTransportProvider("timeout"), MockHotelProvider("timeout")])
def test_timeout_mock_providers_raise_a_distinct_error(provider: object) -> None:
    request = _transport_request() if isinstance(provider, MockTransportProvider) else _hotel_request()
    with pytest.raises(ProviderTimeoutError):
        provider.search(request)  # type: ignore[union-attr]


def test_haversine_route_is_estimated_and_has_no_road_eta() -> None:
    estimate = HaversineRouteEstimator().estimate(
        Coordinates(lat=16.4637, lon=107.5909), Coordinates(lat=16.4700, lon=107.5780)
    )

    assert estimate.source == "HAVERSINE"
    assert estimate.status == "ESTIMATED"
    assert estimate.distance_km > 0
    assert estimate.travel_time_minutes is None
    assert "ETA" in estimate.warning
