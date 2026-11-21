"""Re-check approved offers against fresh provider quotes before anything is booked.

Each approved offer is compared by id: a missing offer is FAILED, a changed price
is RECONFIRM_REQUIRED, and anything else is OK.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from app.providers.base import HotelProvider, TransportProvider
from app.schemas.offer import HotelSearchRequest, TransportSearchRequest
from app.schemas.request import TripRequest

CheckStatus = Literal["OK", "FAILED", "RECONFIRM_REQUIRED"]
MISSING_OFFER_MESSAGE = "Offer no longer available"


@dataclass(frozen=True)
class OfferCheck:
    """The verdict for one approved offer entry."""

    offer: dict[str, Any]
    status: CheckStatus
    message: str | None = None


class QuoteRevalidator:
    """Run the provider searches again with the plan's request and compare prices."""

    def __init__(self, transport_provider: TransportProvider, hotel_provider: HotelProvider) -> None:
        self.transport_provider = transport_provider
        self.hotel_provider = hotel_provider

    def check(self, request: TripRequest, approved: list[dict[str, Any]]) -> list[OfferCheck]:
        fresh = self._fresh_prices(request)
        return [self._compare(offer, fresh) for offer in approved]

    def _fresh_prices(self, request: TripRequest) -> dict[str, int]:
        transport = self.transport_provider.search(
            TransportSearchRequest(
                origin=request.origin,
                destination=request.destination,
                departure_date=request.start_date,
                return_date=request.end_date,
                passengers=request.people,
            )
        )
        prices = {offer.id: offer.price_vnd for offer in transport}
        if not request.is_day_trip:
            hotels = self.hotel_provider.search(
                HotelSearchRequest(
                    destination=request.destination,
                    check_in=request.start_date,
                    check_out=request.end_date,
                    rooms=request.rooms,
                    guests=request.people,
                )
            )
            prices.update({offer.id: offer.price_per_room_night_vnd for offer in hotels})
        return prices

    @staticmethod
    def _compare(offer: dict[str, Any], fresh: dict[str, int]) -> OfferCheck:
        if offer["id"] not in fresh:
            return OfferCheck(offer, "FAILED", MISSING_OFFER_MESSAGE)
        new_price = fresh[offer["id"]]
        if new_price != offer["price"]:
            message = (
                f"Giá đã đổi từ {offer['price']:,} VND thành {new_price:,} VND; "
                "cần xác nhận lại."
            )
            return OfferCheck(offer, "RECONFIRM_REQUIRED", message)
        return OfferCheck(offer, "OK")
