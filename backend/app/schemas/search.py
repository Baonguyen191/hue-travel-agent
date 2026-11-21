"""Output contract for Phase 4 Search Agent."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from app.schemas.offer import HotelOffer, TransportOffer
from app.schemas.place import PlaceSearchResult

SearchStatus = Literal["READY", "PARTIAL", "UNSUPPORTED_DESTINATION"]


class SearchResult(BaseModel):
    """Candidates and offers, preserving each item's source and uncertainty."""

    status: SearchStatus
    poi_candidates: list[PlaceSearchResult]
    transport_offers: list[TransportOffer]
    hotel_offers: list[HotelOffer]
    warnings: list[str]
