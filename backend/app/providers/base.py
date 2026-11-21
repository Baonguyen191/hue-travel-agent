"""Interfaces and errors for transport, hotel and route providers."""

from __future__ import annotations

from typing import Protocol

from app.schemas.booking import BookingItem, BookingKind
from app.schemas.offer import (
    Coordinates,
    HotelOffer,
    HotelSearchRequest,
    RouteEstimate,
    TransportOffer,
    TransportSearchRequest,
)


class ProviderTimeoutError(TimeoutError):
    """A provider did not answer within the caller's allowed time."""


class TransportProvider(Protocol):
    def search(self, request: TransportSearchRequest) -> list[TransportOffer]: ...


class HotelProvider(Protocol):
    def search(self, request: HotelSearchRequest) -> list[HotelOffer]: ...


class RouteProvider(Protocol):
    def estimate(self, origin: Coordinates, destination: Coordinates) -> RouteEstimate: ...


class BookingProvider(Protocol):
    """Creates one booking per call and reads the status of an earlier attempt."""

    def book(self, offer_id: str, kind: BookingKind, intent_id: str) -> BookingItem: ...

    def get_status(self, offer_id: str, intent_id: str, kind: BookingKind) -> BookingItem: ...
