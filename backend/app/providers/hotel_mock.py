"""Deterministic hotel fixtures. They never contact or book with a vendor."""

from __future__ import annotations

from typing import Literal

from app.providers.base import ProviderTimeoutError
from app.schemas.offer import HotelOffer, HotelSearchRequest

MockMode = Literal["normal", "empty", "timeout"]

# (id, hotel name, tier, price per room per night in VND)
_FIXTURES: tuple[tuple[str, str, str, int], ...] = (
    ("mock-hotel-homestay", "Old Quarter Homestay Demo", "HOMESTAY", 350_000),
    ("mock-hotel-riverside-deluxe", "Riverside Hue Demo Hotel", "THREE_STAR", 650_000),
    ("mock-hotel-perfume-river", "Perfume River Demo Resort", "FOUR_STAR", 1_400_000),
)


class MockHotelProvider:
    """Return clearly-labelled per-room-per-night fixtures for Hue."""

    def __init__(
        self,
        mode: MockMode = "normal",
        price_overrides: dict[str, int] | None = None,
    ) -> None:
        self.mode = mode
        # Tests and the demo only: replace the fixture price of listed offer ids.
        self.price_overrides: dict[str, int] = dict(price_overrides or {})

    def search(self, request: HotelSearchRequest) -> list[HotelOffer]:
        if self.mode == "timeout":
            raise ProviderTimeoutError("Mock hotel provider timed out")
        if self.mode == "empty":
            return []

        return [self._offer(request, offer_id, hotel_name, tier, price) for offer_id, hotel_name, tier, price in _FIXTURES]

    def _offer(
        self,
        request: HotelSearchRequest,
        offer_id: str,
        hotel_name: str,
        tier: str,
        price: int,
    ) -> HotelOffer:
        return HotelOffer(
            id=offer_id,
            provider="Hue Stay Demo",
            source="MOCK",
            hotel_name=hotel_name,
            destination=request.destination,
            check_in=request.check_in,
            check_out=request.check_out,
            rooms_available=5,
            price_per_room_night_vnd=self.price_overrides.get(offer_id, price),
            price_unit="VND_PER_ROOM_PER_NIGHT",
            tier=tier,
        )
