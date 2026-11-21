"""Greedy nearest-neighbour itinerary construction over actual Hue POIs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta
from math import ceil
import re

from app.schemas.itinerary import ItineraryDay, ItineraryEvent, ItineraryResult
from app.schemas.place import Place, PlaceSearchResult
from app.schemas.request import TripRequest
from app.schemas.search import SearchResult
from app.services.itinerary_validator import validate_itinerary
from app.services.poi_search import haversine_km


@dataclass(frozen=True)
class ItineraryConfig:
    day_start: time = time(9, 0)
    day_end: time = time(18, 0)
    meal_start: time = time(12, 0)
    meal_end: time = time(13, 0)
    buffer_minutes: int = 15
    travel_speed_kmh: float = 20.0
    max_visits_per_day: int = 4
    default_start_lat: float = 16.4637
    default_start_lon: float = 107.5909

    def __post_init__(self) -> None:
        if self.day_end <= self.day_start or self.meal_end <= self.meal_start:
            raise ValueError("day and meal time ranges must be positive")
        if self.travel_speed_kmh <= 0 or self.max_visits_per_day <= 0 or self.buffer_minutes < 0:
            raise ValueError("invalid itinerary configuration")


_DEFAULT_VISIT_MINUTES = {
    "historic": 120,
    "attraction": 90,
    "museum": 90,
    "religious": 60,
    "park": 60,
    "market": 60,
    "restaurant": 60,
    "cafe": 45,
}
_HOURS_RANGE = re.compile(r"^(?P<open>\d{2}:\d{2})\s*-\s*(?P<close>\d{2}:\d{2})$")


def parse_simple_opening_window(value: str | None) -> tuple[time, time] | None:
    """Parse only an unambiguous same-day HH:MM-HH:MM source range.

    The source often omits days of week, so this supports scheduling bounds but
    never upgrades the POI's opening-hours confidence.
    """
    if not value:
        return None
    match = _HOURS_RANGE.fullmatch(value.strip())
    if match is None:
        return None
    try:
        opens, closes = time.fromisoformat(match["open"]), time.fromisoformat(match["close"])
    except ValueError:
        return None
    return (opens, closes) if closes > opens else None


class ItineraryAgent:
    """Create a feasible best-effort itinerary without claiming verified opening hours."""

    def __init__(self, config: ItineraryConfig | None = None) -> None:
        self.config = config or ItineraryConfig()

    def plan(self, request: TripRequest, search: SearchResult) -> ItineraryResult:
        selected = self._select_candidates(search.poi_candidates, request)
        date_count = (request.end_date - request.start_date).days + 1
        remaining = [candidate.place for candidate in selected]
        days: list[ItineraryDay] = []
        unplanned: list[str] = []
        global_warnings: list[str] = []
        start_lat = request.center_lat if request.center_lat is not None else self.config.default_start_lat
        start_lon = request.center_lon if request.center_lon is not None else self.config.default_start_lon

        for day_offset in range(date_count):
            day_date = request.start_date + timedelta(days=day_offset)
            days_left = date_count - day_offset
            target_count = min(self.config.max_visits_per_day, ceil(len(remaining) / days_left)) if remaining else 0
            route = self._nearest_route(remaining, start_lat, start_lon, target_count)
            for place in route:
                remaining.remove(place)
            itinerary_day, day_unplanned = self._schedule_day(day_date, route, start_lat, start_lon)
            unplanned.extend(day_unplanned)
            days.append(itinerary_day)

        unplanned.extend(place.id for place in remaining)
        if unplanned:
            global_warnings.append("Some selected POIs did not fit in the available itinerary time.")
        global_warnings.append("Travel distances are straight-line estimates, not road routes or ETAs.")
        global_warnings.append("Opening hours are source-provided or absent and require confirmation.")
        validation = validate_itinerary(days)
        return ItineraryResult(
            days=days,
            unplanned_poi_ids=unplanned,
            warnings=global_warnings,
            validation=validation,
        )

    def _select_candidates(
        self, candidates: list[PlaceSearchResult], request: TripRequest
    ) -> list[PlaceSearchResult]:
        limit = ((request.end_date - request.start_date).days + 1) * self.config.max_visits_per_day
        return sorted(candidates, key=lambda item: (-item.score, item.place.id))[:limit]

    @staticmethod
    def _nearest_route(places: list[Place], lat: float, lon: float, count: int) -> list[Place]:
        available = list(places)
        route: list[Place] = []
        current_lat, current_lon = lat, lon
        while available and len(route) < count:
            next_place = min(
                available,
                key=lambda place: (haversine_km(current_lat, current_lon, place.lat, place.lon), place.id),
            )
            route.append(next_place)
            available.remove(next_place)
            current_lat, current_lon = next_place.lat, next_place.lon
        return route

    def _schedule_day(
        self, day_date, route: list[Place], start_lat: float, start_lon: float
    ) -> tuple[ItineraryDay, list[str]]:
        current = datetime.combine(day_date, self.config.day_start)
        day_end = datetime.combine(day_date, self.config.day_end)
        meal_start = datetime.combine(day_date, self.config.meal_start)
        meal_end = datetime.combine(day_date, self.config.meal_end)
        current_lat, current_lon = start_lat, start_lon
        events: list[ItineraryEvent] = []
        unplanned: list[str] = []
        day_warnings: list[str] = []
        meal_taken = False

        for place in route:
            distance = haversine_km(current_lat, current_lon, place.lat, place.lon)
            travel_minutes = ceil(distance / self.config.travel_speed_kmh * 60)
            arrival = current + timedelta(minutes=travel_minutes)
            duration = place.visit_minutes or _DEFAULT_VISIT_MINUTES[place.category]
            if arrival < meal_end and arrival + timedelta(minutes=duration) > meal_start:
                break_start = max(arrival, meal_start)
                if break_start < meal_end:
                    if not meal_taken:
                        events.append(ItineraryEvent(kind="MEAL_BREAK", start_at=break_start, end_at=meal_end, name="Meal break"))
                        meal_taken = True
                    arrival = meal_end
            opening_window = parse_simple_opening_window(place.opening_hours_raw)
            if opening_window is not None:
                opens_at = datetime.combine(day_date, opening_window[0])
                closes_at = datetime.combine(day_date, opening_window[1])
                arrival = max(arrival, opens_at)
            else:
                closes_at = None
            visit_end = arrival + timedelta(minutes=duration)
            buffer_end = visit_end + timedelta(minutes=self.config.buffer_minutes)
            if buffer_end > day_end or (closes_at is not None and visit_end > closes_at):
                unplanned.append(place.id)
                if closes_at is not None and visit_end > closes_at:
                    day_warnings.append(f"{place.name} did not fit its source opening-hour range.")
                continue
            warnings = ["Opening hours require verification before the visit."]
            if opening_window is not None:
                warnings.append("A same-day source hour range was applied; days of operation remain unverified.")
            else:
                warnings.append("No safely parseable opening-hour range was available.")
            if place.visit_minutes is None:
                warnings.append("Visit duration is a category-based assumption.")
            events.append(
                ItineraryEvent(
                    kind="VISIT", poi_id=place.id, name=place.name, category=place.category,
                    lat=place.lat, lon=place.lon, start_at=arrival, end_at=visit_end,
                    visit_minutes=duration, travel_distance_km=round(distance, 3),
                    travel_minutes_estimated=travel_minutes, warnings=warnings,
                )
            )
            if self.config.buffer_minutes:
                events.append(ItineraryEvent(kind="BUFFER", start_at=visit_end, end_at=buffer_end, name="Travel buffer"))
            current = buffer_end
            current_lat, current_lon = place.lat, place.lon
        return ItineraryDay(date=day_date, events=events, warnings=day_warnings), unplanned
