"""Normalized, provenance-preserving representation of a Hue POI."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

PlaceCategory = Literal[
    "restaurant",
    "cafe",
    "historic",
    "attraction",
    "market",
    "religious",
    "park",
    "museum",
]
OpeningHoursConfidence = Literal["UNVERIFIED", "PARTIAL", "UNKNOWN"]
PriceStatus = Literal["REFERENCE_RANGE", "FREE_CLAIM", "UNKNOWN"]


class Place(BaseModel):
    """A POI read from the Hue SQLite source, with its source fields retained."""

    id: str
    name: str
    category: PlaceCategory
    lat: float
    lon: float
    address: str | None = None
    rating_value: float | None = Field(default=None, ge=0, le=5)
    rating_count: int | None = Field(default=None, ge=0)
    rating_source: str | None = None
    opening_hours_raw: str | None = None
    opening_hours_confidence: OpeningHoursConfidence
    visit_minutes: int | None = Field(default=None, gt=0)
    price_min_vnd: int | None = Field(default=None, ge=0)
    price_max_vnd: int | None = Field(default=None, ge=0)
    price_unit: str | None = None
    price_status: PriceStatus
    is_free_claim: bool = False
    summary: str | None = None
    photo_url: str | None = None
    source: str
    source_url: str | None = None
    source_place_id: str
    collected_at: datetime
    raw_attributes: dict[str, Any]


class PlacePage(BaseModel):
    """A page of source POIs."""

    items: list[Place]
    total: int = Field(ge=0)
    limit: int = Field(ge=1)
    offset: int = Field(ge=0)


class PlaceSearchResult(BaseModel):
    """A POI returned by local search with transparent ranking metadata."""

    place: Place
    score: float = Field(ge=0, le=100)
    distance_km: float | None = Field(default=None, ge=0)


class PlaceSearchPage(BaseModel):
    """A paginated local-search response; no external data is queried."""

    items: list[PlaceSearchResult]
    total: int = Field(ge=0)
    limit: int = Field(ge=1)
    offset: int = Field(ge=0)
