"""Domain models cho lịch trình.

Schema Itinerary cố ý chỉ kiểm tra cấu trúc. Lỗi logic (thời gian, giờ mở cửa...)
do validator báo kèm vị trí để LLM sửa được.
"""

from __future__ import annotations

import datetime as dt
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Coordinates(BaseModel):
    model_config = ConfigDict(frozen=True)

    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)


class Category(StrEnum):
    ATTRACTION = "attraction"
    MUSEUM = "museum"
    HISTORIC = "historic"
    VIEWPOINT = "viewpoint"
    RESTAURANT = "restaurant"
    CAFE = "cafe"
    MARKET = "market"
    PARK = "park"
    RELIGIOUS = "religious"


class TravelMode(StrEnum):
    WALK = "walk"
    MOTORBIKE = "motorbike"
    CAR = "car"


class Pace(StrEnum):
    RELAXED = "relaxed"
    MODERATE = "moderate"
    PACKED = "packed"


class Place(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    category: Category
    coords: Coordinates
    opening_hours_raw: str | None = None
    source: str = Field(min_length=1)
    source_place_id: str = Field(min_length=1)
    license: str = Field(min_length=1)
    collected_at: dt.datetime


class PlanRequest(BaseModel):
    city: str = "hue"
    start_date: dt.date
    num_days: int = Field(ge=1, le=7)
    day_start: dt.time = dt.time(8, 0)
    day_end: dt.time = dt.time(21, 0)
    travel_mode: TravelMode = TravelMode.MOTORBIKE
    pace: Pace = Pace.MODERATE
    interests: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _day_window_is_positive(self) -> PlanRequest:
        if self.day_end <= self.day_start:
            raise ValueError("day_end must be after day_start")
        return self


class PlannedStop(BaseModel):
    place_id: str = Field(min_length=1)
    arrive: dt.time
    depart: dt.time
    note: str | None = None


class PlannedDay(BaseModel):
    date: dt.date
    stops: list[PlannedStop] = Field(min_length=1)


class Itinerary(BaseModel):
    days: list[PlannedDay] = Field(min_length=1)
