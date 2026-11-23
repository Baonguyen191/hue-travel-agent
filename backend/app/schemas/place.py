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
PhotoKind = Literal["source", "commons_place", "commons_illustrative"]


class PlacePhoto(BaseModel):
    """Where the photo shown for a place comes from. `commons_illustrative` does not show the place itself."""

    url: str
    kind: PhotoKind
    author: str | None = None
    license: str | None = None
    credit_url: str | None = None


class GuideSection(BaseModel):
    """One short section of the article (a level-2 heading and its text), shown after the lead."""

    heading: str
    text: str


class PlaceGuide(BaseModel):
    """The lead of a Vietnamese Wikipedia article about the place (CC BY-SA 4.0), with its source.

    `sections` holds up to three short sections of the same article in article order; `text` stays the lead.
    """

    text: str
    title: str
    url: str
    license: str
    retrieved_at: str
    sections: list[GuideSection] = []


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
    photo: PlacePhoto | None = None
    guide: PlaceGuide | None = None
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
