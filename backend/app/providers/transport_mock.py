"""Deterministic transport fixtures. They never contact or book with a vendor."""

from __future__ import annotations

from datetime import date
from typing import Literal

from app.providers.base import ProviderTimeoutError
from app.schemas.offer import TransportOffer, TransportSearchRequest

MockMode = Literal["normal", "empty", "timeout"]

# (mode, provider name, price per person per leg in VND, id slug for "standard" bus)
_FIXTURES: tuple[tuple[str, str, int, str], ...] = (
    ("BUS", "Hue Sleeper Bus Demo", 400_000, "standard"),
    ("TRAIN", "Reunification Train Demo", 800_000, "train"),
    ("FLIGHT", "Hue Air Demo", 1_600_000, "flight"),
)


class MockTransportProvider:
    """Return labelled mock bus, train and flight offers for both legs of a Hue trip."""

    def __init__(self, mode: MockMode = "normal") -> None:
        self.mode = mode

    def search(self, request: TransportSearchRequest) -> list[TransportOffer]:
        if self.mode == "timeout":
            raise ProviderTimeoutError("Mock transport provider timed out")
        if self.mode == "empty":
            return []

        offers: list[TransportOffer] = []
        for leg, origin, destination, departure in (
            ("OUTBOUND", request.origin, request.destination, request.departure_date),
            ("RETURN", request.destination, request.origin, request.return_date),
        ):
            offers.extend(
                _offer(request, leg, origin, destination, departure, mode, provider, price, slug)
                for mode, provider, price, slug in _FIXTURES
            )
        return offers


def _offer(
    request: TransportSearchRequest,
    leg: str,
    origin: str,
    destination: str,
    departure: date,
    mode: str,
    provider: str,
    price: int,
    slug: str,
) -> TransportOffer:
    leg_slug = "outbound" if leg == "OUTBOUND" else "return"
    return TransportOffer(
        id=f"mock-transport-{leg_slug}-{slug}",
        provider=provider,
        source="MOCK",
        origin=origin,
        destination=destination,
        departure_date=departure,
        leg=leg,
        price_vnd=price,
        price_unit="VND_PER_PERSON_PER_LEG",
        seats_available=12,
        mode=mode,
    )
