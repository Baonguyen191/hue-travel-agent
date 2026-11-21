"""Deterministic transport fixtures. They never contact or book with a vendor."""

from __future__ import annotations

from typing import Literal

from app.providers.base import ProviderTimeoutError
from app.schemas.offer import TransportOffer, TransportSearchRequest

MockMode = Literal["normal", "empty", "timeout"]


class MockTransportProvider:
    """Return labelled mock bus offers for both legs of a Hue trip."""

    def __init__(self, mode: MockMode = "normal") -> None:
        self.mode = mode

    def search(self, request: TransportSearchRequest) -> list[TransportOffer]:
        if self.mode == "timeout":
            raise ProviderTimeoutError("Mock transport provider timed out")
        if self.mode == "empty":
            return []

        return [
            TransportOffer(
                id="mock-transport-outbound-standard",
                provider="Hue Express Demo",
                source="MOCK",
                origin=request.origin,
                destination=request.destination,
                departure_date=request.departure_date,
                leg="OUTBOUND",
                price_vnd=280_000,
                price_unit="VND_PER_PERSON_PER_LEG",
                seats_available=12,
            ),
            TransportOffer(
                id="mock-transport-return-standard",
                provider="Hue Express Demo",
                source="MOCK",
                origin=request.destination,
                destination=request.origin,
                departure_date=request.return_date,
                leg="RETURN",
                price_vnd=280_000,
                price_unit="VND_PER_PERSON_PER_LEG",
                seats_available=12,
            ),
        ]
