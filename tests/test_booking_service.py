from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from booking_fixtures import approve, make_plan, places  # noqa: E402

from app.db.store import PlanStore  # noqa: E402
from app.providers.booking_mock import MockBookingProvider  # noqa: E402
from app.providers.hotel_mock import MockHotelProvider  # noqa: E402
from app.providers.transport_mock import MockTransportProvider  # noqa: E402
from app.services.booking_service import BookingService  # noqa: E402
from app.services.quote_revalidator import QuoteRevalidator  # noqa: E402


def test_booking_requires_approval_and_idempotency():
    store = PlanStore("sqlite://")
    plan = make_plan(store, "b")
    service = BookingService(
        store,
        MockBookingProvider(),
        QuoteRevalidator(MockTransportProvider(), MockHotelProvider()),
        places=places(),
    )

    with pytest.raises(PermissionError):
        service.book("b", "idempotency-1")

    approve(store, plan, "BUDGET")
    first = service.book("b", "idempotency-1")
    second = service.book("b", "idempotency-1")

    assert first.status == "BOOKED" and first.model_dump() == second.model_dump()
