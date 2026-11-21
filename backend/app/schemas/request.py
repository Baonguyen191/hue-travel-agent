"""Typed input for the deterministic Search Agent."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field, model_validator

from app.schemas.place import PlaceCategory


class TripRequest(BaseModel):
    """A minimal structured request; natural-language extraction comes in Phase 7."""

    origin: str = Field(min_length=1, max_length=120)
    destination: str = Field(min_length=1, max_length=120)
    start_date: date
    end_date: date
    people: int = Field(ge=1, le=20)
    rooms: int = Field(default=1, ge=1, le=10)
    budget_vnd: int | None = Field(default=None, gt=0)
    categories: list[PlaceCategory] = Field(default_factory=list)
    keyword: str | None = Field(default=None, min_length=1, max_length=200)
    preferences: list[str] = Field(default_factory=list, max_length=10)
    center_lat: float | None = Field(default=None, ge=-90, le=90)
    center_lon: float | None = Field(default=None, ge=-180, le=180)
    radius_km: float | None = Field(default=None, gt=0, le=100)
    must_include_poi_ids: list[str] = Field(default_factory=list, max_length=10)
    exclude_poi_ids: list[str] = Field(default_factory=list, max_length=50)
    exclude_categories: list[PlaceCategory] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_dates_and_coordinates(self) -> "TripRequest":
        if self.end_date < self.start_date:
            raise ValueError("end_date must not be before start_date")
        if set(self.must_include_poi_ids) & set(self.exclude_poi_ids):
            raise ValueError("a POI cannot be both must-include and excluded")
        if (self.center_lat is None) != (self.center_lon is None):
            raise ValueError("center_lat and center_lon must be supplied together")
        if self.radius_km is not None and self.center_lat is None:
            raise ValueError("radius_km requires center_lat and center_lon")
        return self

    @property
    def is_day_trip(self) -> bool:
        """A trip that starts and ends on the same date needs no hotel night."""
        return self.start_date == self.end_date
