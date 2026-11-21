"""Mock booking provider: book once per call, reconcile without booking."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.providers.booking_mock import MockBookingProvider  # noqa: E402

TRANSPORT_ID = "mock-transport-outbound-standard"
HOTEL_ID = "mock-hotel-homestay"
INTENT = "intent-abcdef123456"


def test_success_books_with_mock_reference_built_from_intent_prefix() -> None:
    provider = MockBookingProvider()

    item = provider.book(TRANSPORT_ID, "TRANSPORT", INTENT)

    assert item.status == "BOOKED"
    assert item.source == "MOCK"
    assert item.reference == f"MOCK-{INTENT[:8]}-{TRANSPORT_ID}"


def test_fail_mode_returns_failed_without_reference() -> None:
    provider = MockBookingProvider(modes={HOTEL_ID: "fail"})

    item = provider.book(HOTEL_ID, "HOTEL", INTENT)

    assert item.status == "FAILED"
    assert item.reference is None


def test_timeout_mode_returns_unknown_with_reconcile_message() -> None:
    provider = MockBookingProvider(modes={HOTEL_ID: "timeout"})

    item = provider.book(HOTEL_ID, "HOTEL", INTENT)

    assert item.status == "UNKNOWN"
    assert item.message == "Provider timed out; status will be reconciled."


def test_book_records_every_call() -> None:
    provider = MockBookingProvider()

    provider.book(TRANSPORT_ID, "TRANSPORT", INTENT)
    provider.book(HOTEL_ID, "HOTEL", INTENT)

    assert provider.book_calls == [(TRANSPORT_ID, INTENT), (HOTEL_ID, INTENT)]


def test_get_status_reads_reconcile_map_without_creating_a_booking() -> None:
    provider = MockBookingProvider(
        modes={HOTEL_ID: "timeout"},
        reconcile={HOTEL_ID: "BOOKED"},
    )
    provider.book(HOTEL_ID, "HOTEL", INTENT)

    item = provider.get_status(HOTEL_ID, INTENT, "HOTEL")

    assert item.status == "BOOKED"
    assert item.reference == f"MOCK-{INTENT[:8]}-{HOTEL_ID}"
    assert provider.book_calls == [(HOTEL_ID, INTENT)]


def test_get_status_defaults_to_unknown_for_unreconciled_offer() -> None:
    provider = MockBookingProvider()

    item = provider.get_status(HOTEL_ID, INTENT, "HOTEL")

    assert item.status == "UNKNOWN"
    assert provider.book_calls == []
