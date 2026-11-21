"""Compatibility wrapper: the booking logic lives in `app.agents.booking.BookingAgent`."""

from __future__ import annotations

from app.agents.booking import BookingAgent
from app.db.store import DEFAULT_OWNER, PlanStore
from app.providers.base import BookingProvider
from app.repositories.hue_places import HuePlacesRepository
from app.schemas.booking import BookingResult
from app.services.quote_revalidator import QuoteRevalidator


class BookingService:
    """Keeps the older `BookingService(store, provider).book(...)` import path working."""

    def __init__(
        self,
        store: PlanStore,
        provider: BookingProvider,
        revalidator: QuoteRevalidator,
        places: HuePlacesRepository | None = None,
    ) -> None:
        self.agent = BookingAgent(store, provider, revalidator, places)

    def book(
        self, thread_id: str, idempotency_key: str, user_id: str = DEFAULT_OWNER
    ) -> BookingResult:
        return self.agent.book(thread_id, idempotency_key, user_id)
