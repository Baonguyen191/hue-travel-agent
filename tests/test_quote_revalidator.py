"""Quote revalidation against fresh provider prices, and mock price overrides."""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.providers.hotel_mock import MockHotelProvider  # noqa: E402
from app.providers.transport_mock import MockTransportProvider  # noqa: E402
from app.schemas.offer import HotelSearchRequest, TransportSearchRequest  # noqa: E402
from app.schemas.request import TripRequest  # noqa: E402
from app.services.quote_revalidator import QuoteRevalidator  # noqa: E402

REQUEST = TripRequest(
    origin="Da Nang",
    destination="Hue",
    start_date=date(2026, 12, 10),
    end_date=date(2026, 12, 12),
    people=2,
)
OUTBOUND_ID = "mock-transport-outbound-standard"
RETURN_ID = "mock-transport-return-standard"
HOMESTAY_ID = "mock-hotel-homestay"
DELUXE_ID = "mock-hotel-riverside-deluxe"


def _transport_entry(offer_id: str, price: int) -> dict:
    return {"kind": "TRANSPORT", "leg": "OUTBOUND", "id": offer_id, "price": price}


def _hotel_entry(offer_id: str, price: int) -> dict:
    return {"kind": "HOTEL", "leg": None, "id": offer_id, "price": price}


def _transport_request() -> TransportSearchRequest:
    return TransportSearchRequest(
        origin="Da Nang",
        destination="Hue",
        departure_date=date(2026, 12, 10),
        return_date=date(2026, 12, 12),
        passengers=2,
    )


def _hotel_request() -> HotelSearchRequest:
    return HotelSearchRequest(
        destination="Hue",
        check_in=date(2026, 12, 10),
        check_out=date(2026, 12, 12),
        rooms=1,
        guests=2,
    )


def test_unchanged_price_is_ok() -> None:
    revalidator = QuoteRevalidator(MockTransportProvider(), MockHotelProvider())

    checks = revalidator.check(REQUEST, [_transport_entry(OUTBOUND_ID, 400_000)])

    assert [check.status for check in checks] == ["OK"]


def test_changed_price_requires_reconfirmation_with_old_and_new_price() -> None:
    revalidator = QuoteRevalidator(
        MockTransportProvider(price_overrides={OUTBOUND_ID: 500_000}),
        MockHotelProvider(),
    )

    checks = revalidator.check(REQUEST, [_transport_entry(OUTBOUND_ID, 400_000)])

    assert checks[0].status == "RECONFIRM_REQUIRED"
    assert "400,000" in checks[0].message
    assert "500,000" in checks[0].message


def test_missing_offer_fails_with_spec_message() -> None:
    revalidator = QuoteRevalidator(MockTransportProvider(), MockHotelProvider())

    checks = revalidator.check(REQUEST, [_transport_entry("mock-transport-gone", 400_000)])

    assert checks[0].status == "FAILED"
    assert checks[0].message == "Offer no longer available"


def test_hotel_price_change_is_detected() -> None:
    revalidator = QuoteRevalidator(
        MockTransportProvider(),
        MockHotelProvider(price_overrides={HOMESTAY_ID: 999_000}),
    )

    checks = revalidator.check(REQUEST, [_hotel_entry(HOMESTAY_ID, 350_000)])

    assert checks[0].status == "RECONFIRM_REQUIRED"


def test_transport_price_override_changes_only_the_listed_offer() -> None:
    offers = MockTransportProvider(price_overrides={OUTBOUND_ID: 123_000}).search(_transport_request())
    prices = {offer.id: offer.price_vnd for offer in offers}

    assert prices[OUTBOUND_ID] == 123_000
    assert prices[RETURN_ID] == 400_000


def test_hotel_price_override_is_applied_to_listed_offer_only() -> None:
    offers = MockHotelProvider(price_overrides={HOMESTAY_ID: 999_000}).search(_hotel_request())
    prices = {offer.id: offer.price_per_room_night_vnd for offer in offers}

    assert prices[HOMESTAY_ID] == 999_000
    assert prices[DELUXE_ID] == 650_000
