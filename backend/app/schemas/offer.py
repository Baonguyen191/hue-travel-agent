"""Provider contracts used by later agents, with explicit price provenance."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, model_validator

ProviderSource = Literal["MOCK", "LIVE"]
RouteStatus = Literal["ESTIMATED", "QUOTED", "UNKNOWN"]


class TransportSearchRequest(BaseModel):
    origin: str = Field(min_length=1, max_length=120)
    destination: str = Field(min_length=1, max_length=120)
    departure_date: date
    return_date: date
    passengers: int = Field(ge=1, le=20)

    @model_validator(mode="after")
    def return_after_departure(self) -> "TransportSearchRequest":
        if self.return_date <= self.departure_date:
            raise ValueError("return_date must be after departure_date")
        return self


class HotelSearchRequest(BaseModel):
    destination: str = Field(min_length=1, max_length=120)
    check_in: date
    check_out: date
    rooms: int = Field(ge=1, le=10)
    guests: int = Field(ge=1, le=30)

    @model_validator(mode="after")
    def check_out_after_check_in(self) -> "HotelSearchRequest":
        if self.check_out <= self.check_in:
            raise ValueError("check_out must be after check_in")
        return self

    @property
    def nights(self) -> int:
        return (self.check_out - self.check_in).days


class TransportOffer(BaseModel):
    id: str
    provider: str
    source: ProviderSource
    origin: str
    destination: str
    departure_date: date
    leg: Literal["OUTBOUND", "RETURN"]
    price_vnd: int = Field(gt=0)
    price_unit: Literal["VND_PER_PERSON_PER_LEG"]
    seats_available: int = Field(ge=0)
    booking_url: str | None = None


class HotelOffer(BaseModel):
    id: str
    provider: str
    source: ProviderSource
    hotel_name: str
    destination: str
    check_in: date
    check_out: date
    rooms_available: int = Field(ge=0)
    price_per_room_night_vnd: int = Field(gt=0)
    price_unit: Literal["VND_PER_ROOM_PER_NIGHT"]
    booking_url: str | None = None

    @property
    def nights(self) -> int:
        return (self.check_out - self.check_in).days


class Coordinates(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)


class RouteEstimate(BaseModel):
    source: Literal["HAVERSINE"]
    status: RouteStatus
    origin: Coordinates
    destination: Coordinates
    distance_km: float = Field(ge=0)
    travel_time_minutes: None = None
    warning: str
