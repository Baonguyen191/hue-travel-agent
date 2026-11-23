"""Structured, provenance-preserving itinerary contracts."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

ItineraryEventKind = Literal["VISIT", "MEAL", "MEAL_BREAK", "REST", "BUFFER"]
MealKind = Literal["LUNCH", "DINNER", "CAFE"]
# Slot labels shown to the user: morning, lunch, rest, afternoon, cafe, sunset, dinner.
SlotKind = Literal["morning", "lunch", "rest", "afternoon", "cafe", "sunset", "dinner"]
TravelMode = Literal["BUS", "TRAIN", "FLIGHT"]


class ItineraryEvent(BaseModel):
    kind: ItineraryEventKind
    start_at: datetime
    end_at: datetime
    poi_id: str | None = None
    name: str
    category: str | None = None
    meal: MealKind | None = None
    slot: SlotKind | None = None
    reason: str | None = None
    intro: str | None = None
    lat: float | None = None
    lon: float | None = None
    visit_minutes: int | None = Field(default=None, gt=0)
    travel_distance_km: float | None = Field(default=None, ge=0)
    travel_minutes_estimated: int | None = Field(default=None, ge=0)
    warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_time_and_poi(self) -> "ItineraryEvent":
        if self.end_at <= self.start_at:
            raise ValueError("end_at must be after start_at")
        if self.kind == "VISIT" and self.poi_id is None:
            raise ValueError("VISIT events require poi_id")
        if self.kind == "MEAL" and self.poi_id is None:
            raise ValueError("MEAL events require poi_id")
        return self


class ItineraryDay(BaseModel):
    date: date
    events: list[ItineraryEvent]
    warnings: list[str] = Field(default_factory=list)


class ItineraryValidation(BaseModel):
    valid: bool
    warnings: list[str]


class TravelLeg(BaseModel):
    """Inter-city leg outside the day list: times are fixed estimates for the chosen mode."""

    direction: Literal["OUTBOUND", "RETURN"]
    mode: TravelMode
    origin: str
    destination: str
    depart_at: datetime
    arrive_at: datetime
    estimated: bool = True
    mock: bool = True


class ItineraryResult(BaseModel):
    days: list[ItineraryDay]
    unplanned_poi_ids: list[str]
    excluded_poi_ids: list[str] = Field(default_factory=list)
    merged_poi_ids: list[str] = Field(default_factory=list)
    warnings: list[str]
    validation: ItineraryValidation
    travel_legs: list[TravelLeg] = Field(default_factory=list)
    sunset_estimate: str | None = None

    def poi_ids(self) -> list[str]:
        """Return VISIT and MEAL poi_ids in time order, each id once."""
        scheduled = sorted(
            (
                event
                for day in self.days
                for event in day.events
                if event.kind in ("VISIT", "MEAL") and event.poi_id is not None
            ),
            key=lambda event: event.start_at,
        )
        return list(dict.fromkeys(event.poi_id for event in scheduled))
