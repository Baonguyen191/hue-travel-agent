"""Deterministic hotel fixtures. They never contact or book with a vendor."""

from __future__ import annotations

from typing import Literal

from app.providers.base import ProviderTimeoutError
from app.schemas.offer import HotelOffer, HotelSearchRequest

MockMode = Literal["normal", "empty", "timeout"]


class MockHotelProvider:
    """Return a clearly-labelled per-room-per-night fixture for Hue."""

    def __init__(self, mode: MockMode = "normal") -> None:
        self.mode = mode

    def search(self, request: HotelSearchRequest) -> list[HotelOffer]:
        if self.mode == "timeout":
            raise ProviderTimeoutError("Mock hotel provider timed out")
        if self.mode == "empty":
            return []

        return [
            HotelOffer(
                id="mock-hotel-riverside-deluxe",
                provider="Hue Stay Demo",
                source="MOCK",
                hotel_name="Riverside Hue Demo Hotel",
                destination=request.destination,
                check_in=request.check_in,
                check_out=request.check_out,
                rooms_available=5,
                price_per_room_night_vnd=650_000,
                price_unit="VND_PER_ROOM_PER_NIGHT",
            )
        ]
