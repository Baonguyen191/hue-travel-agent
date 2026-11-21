"""Booking endpoint: 404 unknown plan, 403 other owner, 409 not approved, else 200."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException

from app.agents.booking import ApprovalRequiredError, BookingAgent
from app.api.plans import get_store, hue_places
from app.db.store import DEFAULT_OWNER, PlanStore
from app.providers.booking_mock import MockBookingProvider
from app.providers.hotel_mock import MockHotelProvider
from app.providers.transport_mock import MockTransportProvider
from app.schemas.booking import BookingRequest, BookingResult
from app.services.quote_revalidator import QuoteRevalidator

router = APIRouter(prefix="/api/v1/plans", tags=["bookings"])


def get_booking_agent(store: PlanStore = Depends(get_store)) -> BookingAgent:
    """Build the booking agent over the lifespan's plan store."""
    return BookingAgent(
        store,
        MockBookingProvider(),
        QuoteRevalidator(MockTransportProvider(), MockHotelProvider()),
        places=hue_places,
    )


@router.post("/{thread_id}/book", response_model=BookingResult)
def book(
    thread_id: str,
    body: BookingRequest,
    booking_agent: BookingAgent = Depends(get_booking_agent),
    x_user_id: str = Header(default=DEFAULT_OWNER),
):
    try:
        return booking_agent.book(thread_id, body.idempotency_key, x_user_id)
    except LookupError as error:
        raise HTTPException(404, str(error))
    except ApprovalRequiredError as error:
        raise HTTPException(409, str(error))
    except PermissionError as error:
        raise HTTPException(403, str(error))
