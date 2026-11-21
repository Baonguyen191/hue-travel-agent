"""Itinerary construction over real Hue POIs: area clusters, timed days, named meals."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from math import ceil

from app.repositories.hue_places import HuePlacesRepository
from app.schemas.itinerary import ItineraryDay, ItineraryEvent, ItineraryResult
from app.schemas.place import Place
from app.schemas.request import TripRequest
from app.schemas.search import SearchResult
from app.services.budget_optimizer import SIGHTSEEING_CATEGORIES
from app.services.itinerary_validator import validate_itinerary
from app.services.meal_picker import MealPicker
from app.services.poi_search import haversine_km, normalize_vietnamese
from app.services.preferences import map_preferences

_FOOD_CATEGORIES = ("restaurant", "cafe")
_OPENING_CHECK = "Opening hours require verification before the visit."
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


@dataclass(frozen=True)
class ItineraryConfig:
    """Scheduling assumptions. The hotel is assumed at the centre; times are local."""

    day_start: time = time(8, 0)
    sightseeing_end: time = time(17, 30)
    lunch_earliest: time = time(11, 30)
    lunch_minutes: int = 75
    dinner_earliest: time = time(18, 0)
    dinner_minutes: int = 75
    cafe_break: bool = True
    cafe_earliest: time = time(15, 0)
    cafe_latest: time = time(16, 30)
    cafe_minutes: int = 45
    buffer_minutes: int = 15
    travel_speed_kmh: float = 20.0
    max_visits_per_day: int = 4
    min_visit_minutes: int = 30
    max_visit_minutes: int = 180
    center_lat: float = 16.4698
    center_lon: float = 107.5786
    max_distance_km: float = 15.0
    meal_radius_km: float = 2.0
    landmark_ids: tuple[str, ...] = (
        "huetripo:531787",  # Đại Nội Huế
        "huetripo:197559",  # Chùa Thiên Mụ
        "huetripo:483480",  # Lăng vua Tự Đức
        "huetripo:627150",  # Lăng vua Khải Định
        "huetripo:424131",  # Lăng vua Minh Mạng
        "huetripo:759007",  # Chợ Đông Ba Huế
        "huetripo:664215",  # Cầu Trường Tiền
    )

    def __post_init__(self) -> None:
        if not self.day_start < self.sightseeing_end:
            raise ValueError("day_start must be before sightseeing_end")
        if not self.lunch_earliest < self.dinner_earliest:
            raise ValueError("lunch_earliest must be before dinner_earliest")
        if self.cafe_earliest > self.cafe_latest:
            raise ValueError("cafe_earliest must not be after cafe_latest")
        if not 0 < self.min_visit_minutes <= self.max_visit_minutes:
            raise ValueError("visit minutes must satisfy 0 < min <= max")
        if min(self.lunch_minutes, self.dinner_minutes, self.cafe_minutes) <= 0:
            raise ValueError("meal durations must be positive")
        if self.travel_speed_kmh <= 0 or self.max_visits_per_day <= 0:
            raise ValueError("travel speed and max visits per day must be positive")
        if self.buffer_minutes < 0 or self.meal_radius_km < 0 or self.max_distance_km <= 0:
            raise ValueError("buffer, meal radius and max distance are out of range")


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


def visit_duration_minutes(place: Place, config: ItineraryConfig) -> tuple[int, str | None]:
    """Return the clamped visit length and a warning when a source value was clamped."""
    source = place.visit_minutes
    if source is None:
        source = _DEFAULT_VISIT_MINUTES[place.category]
    minutes = min(max(source, config.min_visit_minutes), config.max_visit_minutes)
    if place.visit_minutes is None or minutes == source:
        return minutes, None
    return minutes, f"Visit duration clamped from {source} to {minutes} minutes."


@dataclass
class _DayState:
    """Mutable cursor for one day: where the traveller is and when they are free."""

    day: date
    current: datetime
    location: tuple[float, float]
    events: list[ItineraryEvent] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    skipped: list[Place] = field(default_factory=list)
    lunch_done: bool = False
    cafe_done: bool = False


class ItineraryAgent:
    """Create a feasible best-effort itinerary without claiming verified opening hours."""

    def __init__(
        self,
        config: ItineraryConfig | None = None,
        places: HuePlacesRepository | None = None,
    ) -> None:
        self.config = config or ItineraryConfig()
        self.places = places

    def plan(self, request: TripRequest, search: SearchResult) -> ItineraryResult:
        centre = self._centre(request)
        pool, excluded = self._build_pool(request, search, centre)
        meals = MealPicker(_food_candidates(search), self.places, self.config.meal_radius_km)
        days, unplanned = self._plan_days(request, pool, centre, meals)
        return ItineraryResult(
            days=days,
            unplanned_poi_ids=unplanned,
            excluded_poi_ids=excluded,
            warnings=self._global_warnings(excluded, unplanned),
            validation=validate_itinerary(days),
        )

    def _centre(self, request: TripRequest) -> tuple[float, float]:
        lat = request.center_lat if request.center_lat is not None else self.config.center_lat
        lon = request.center_lon if request.center_lon is not None else self.config.center_lon
        return lat, lon

    def _build_pool(
        self, request: TripRequest, search: SearchResult, centre: tuple[float, float]
    ) -> tuple[list[Place], list[str]]:
        """Landmarks first, then sightseeing candidates; deduped and distance-filtered."""
        candidates = [item.place for item in search.poi_candidates]
        sightseeing = [place for place in candidates if place.category in SIGHTSEEING_CATEGORIES]
        keyword = normalize_vietnamese(request.keyword) if request.keyword else ""
        kept: list[Place] = []
        excluded: list[str] = []
        seen_ids: set[str] = set()
        seen_names: set[str] = set()
        for place in self._landmarks(request, candidates) + sightseeing:
            name_key = normalize_vietnamese(place.name)
            if place.id in seen_ids or name_key in seen_names:
                continue
            seen_ids.add(place.id)
            seen_names.add(name_key)
            if self._is_too_far(place, name_key, centre, keyword):
                excluded.append(place.id)
            else:
                kept.append(place)
        return kept, excluded

    def _landmarks(self, request: TripRequest, candidates: list[Place]) -> list[Place]:
        if not self._landmarks_wanted(request):
            return []
        by_id = {place.id: place for place in candidates}
        found: list[Place] = []
        for poi_id in self.config.landmark_ids:
            place = by_id[poi_id] if poi_id in by_id else self._lookup(poi_id)
            if place is not None:
                found.append(place)
        return found

    @staticmethod
    def _landmarks_wanted(request: TripRequest) -> bool:
        preferred, _ = map_preferences(request.preferences)
        wanted = set(request.categories) | set(preferred)
        if wanted & {"historic", "religious"}:
            return True
        return not (request.categories or request.preferences or request.keyword)

    def _lookup(self, poi_id: str) -> Place | None:
        return self.places.get_by_id(poi_id) if self.places is not None else None

    def _is_too_far(
        self, place: Place, name_key: str, centre: tuple[float, float], keyword: str
    ) -> bool:
        if keyword and keyword in name_key:
            return False
        distance = haversine_km(centre[0], centre[1], place.lat, place.lon)
        return distance > self.config.max_distance_km

    def _plan_days(
        self,
        request: TripRequest,
        pool: list[Place],
        centre: tuple[float, float],
        meals: MealPicker,
    ) -> tuple[list[ItineraryDay], list[str]]:
        date_count = (request.end_date - request.start_date).days + 1
        remaining = list(pool)
        days: list[ItineraryDay] = []
        for offset in range(date_count):
            day_date = request.start_date + timedelta(days=offset)
            day_set = self._cluster_day(remaining)
            taken = {place.id for place in day_set}
            remaining = [place for place in remaining if place.id not in taken]
            route = self._nearest_route(day_set, centre)
            day, skipped = self._schedule_day(day_date, route, centre, meals)
            days.append(day)
            remaining = _in_priority_order(remaining + skipped, pool)
        return days, [place.id for place in remaining]

    def _cluster_day(self, remaining: list[Place]) -> list[Place]:
        """Seed with the highest-priority place, then add the nearest places to it."""
        if not remaining:
            return []
        seed, rest = remaining[0], remaining[1:]
        nearest = sorted(
            rest,
            key=lambda place: (haversine_km(seed.lat, seed.lon, place.lat, place.lon), place.id),
        )
        return [seed] + nearest[: self.config.max_visits_per_day - 1]

    @staticmethod
    def _nearest_route(places: list[Place], centre: tuple[float, float]) -> list[Place]:
        available = list(places)
        route: list[Place] = []
        current = centre
        while available:
            next_place = min(
                available,
                key=lambda place: (haversine_km(current[0], current[1], place.lat, place.lon), place.id),
            )
            route.append(next_place)
            available = [place for place in available if place.id != next_place.id]
            current = (next_place.lat, next_place.lon)
        return route

    def _schedule_day(
        self, day_date: date, route: list[Place], centre: tuple[float, float], meals: MealPicker
    ) -> tuple[ItineraryDay, list[Place]]:
        state = _DayState(
            day=day_date,
            current=datetime.combine(day_date, self.config.day_start),
            location=centre,
        )
        for place in route:
            self._meals_before_visit(state, place, meals)
            self._visit(state, place)
        self._meals_after_route(state, meals)
        day = ItineraryDay(date=day_date, events=state.events, warnings=state.warnings)
        return day, state.skipped

    def _meals_before_visit(self, state: _DayState, place: Place, meals: MealPicker) -> None:
        travel, _ = self._travel(state.location, place)
        duration, _ = visit_duration_minutes(place, self.config)
        arrival = state.current + timedelta(minutes=travel)
        lunch_at = self._at(state, self.config.lunch_earliest)
        if not state.lunch_done and arrival + timedelta(minutes=duration) > lunch_at:
            self._lunch(state, meals)
        if self._cafe_due(state):
            self._cafe(state, meals)

    def _cafe_due(self, state: _DayState) -> bool:
        return (
            self.config.cafe_break
            and not state.cafe_done
            and self.config.cafe_earliest <= state.current.time() <= self.config.cafe_latest
        )

    def _meals_after_route(self, state: _DayState, meals: MealPicker) -> None:
        if not state.lunch_done:
            self._lunch(state, meals)
        dinner_at = self._at(state, self.config.dinner_earliest)
        if not self._schedule_meal(state, meals, "DINNER", "restaurant", dinner_at, self.config.dinner_minutes):
            state.warnings.append("No restaurant candidate for dinner; no dinner is scheduled.")

    def _lunch(self, state: _DayState, meals: MealPicker) -> None:
        state.lunch_done = True
        earliest = self._at(state, self.config.lunch_earliest)
        if self._schedule_meal(state, meals, "LUNCH", "restaurant", earliest, self.config.lunch_minutes):
            return
        start = max(state.current, earliest)
        end = start + timedelta(minutes=self.config.lunch_minutes)
        state.events.append(
            ItineraryEvent(kind="MEAL_BREAK", start_at=start, end_at=end, name="Meal break (lunch)")
        )
        state.current = end
        state.warnings.append("No restaurant candidate for lunch; an anonymous meal break is scheduled.")

    def _cafe(self, state: _DayState, meals: MealPicker) -> None:
        state.cafe_done = True
        self._schedule_meal(state, meals, "CAFE", "cafe", None, self.config.cafe_minutes)

    def _schedule_meal(
        self,
        state: _DayState,
        meals: MealPicker,
        meal: str,
        category: str,
        earliest: datetime | None,
        minutes: int,
    ) -> bool:
        place = meals.pick(category, state.location[0], state.location[1])
        if place is None:
            return False
        travel, distance = self._travel(state.location, place)
        start = state.current + timedelta(minutes=travel)
        if earliest is not None:
            start = max(start, earliest)
        end = start + timedelta(minutes=minutes)
        state.events.append(
            ItineraryEvent(
                kind="MEAL", meal=meal, poi_id=place.id, name=place.name, category=place.category,
                lat=place.lat, lon=place.lon, start_at=start, end_at=end,
                travel_distance_km=round(distance, 3), travel_minutes_estimated=travel,
                warnings=[_OPENING_CHECK],
            )
        )
        meals.mark_used(place)
        state.current = end
        state.location = (place.lat, place.lon)
        return True

    def _visit(self, state: _DayState, place: Place) -> None:
        travel, distance = self._travel(state.location, place)
        duration, clamp_warning = visit_duration_minutes(place, self.config)
        window = parse_simple_opening_window(place.opening_hours_raw)
        arrival = state.current + timedelta(minutes=travel)
        closes_at = None
        if window is not None:
            arrival = max(arrival, self._at(state, window[0]))
            closes_at = self._at(state, window[1])
        visit_end = arrival + timedelta(minutes=duration)
        sightseeing_end = self._at(state, self.config.sightseeing_end)
        if visit_end > sightseeing_end or (closes_at is not None and visit_end > closes_at):
            state.skipped.append(place)
            if closes_at is not None and visit_end > closes_at:
                state.warnings.append(f"{place.name} did not fit its source opening-hour range.")
            return
        state.events.append(
            ItineraryEvent(
                kind="VISIT", poi_id=place.id, name=place.name, category=place.category,
                lat=place.lat, lon=place.lon, start_at=arrival, end_at=visit_end,
                visit_minutes=duration, travel_distance_km=round(distance, 3),
                travel_minutes_estimated=travel,
                warnings=_visit_warnings(place, window, clamp_warning),
            )
        )
        buffer_end = visit_end + timedelta(minutes=self.config.buffer_minutes)
        if self.config.buffer_minutes:
            state.events.append(
                ItineraryEvent(kind="BUFFER", start_at=visit_end, end_at=buffer_end, name="Travel buffer")
            )
        state.current = buffer_end
        state.location = (place.lat, place.lon)

    def _travel(self, origin: tuple[float, float], place: Place) -> tuple[int, float]:
        """Return (estimated minutes, straight-line km) from origin to place."""
        distance = haversine_km(origin[0], origin[1], place.lat, place.lon)
        return ceil(distance / self.config.travel_speed_kmh * 60), distance

    @staticmethod
    def _at(state: _DayState, value: time) -> datetime:
        return datetime.combine(state.day, value)

    def _global_warnings(self, excluded: list[str], unplanned: list[str]) -> list[str]:
        warnings: list[str] = []
        if excluded:
            warnings.append(
                f"{len(excluded)} places farther than {self.config.max_distance_km:g} km from the centre were skipped."
            )
        if unplanned:
            warnings.append("Some selected POIs did not fit in the available itinerary time.")
        warnings.append(
            "The hotel is assumed at the city centre; travel times are straight-line estimates, not road routes or ETAs."
        )
        warnings.append("Opening hours are source-provided or absent and require confirmation.")
        return warnings


def _food_candidates(search: SearchResult) -> list[Place]:
    return [item.place for item in search.poi_candidates if item.place.category in _FOOD_CATEGORIES]


def _in_priority_order(places: list[Place], pool: list[Place]) -> list[Place]:
    order = {place.id: index for index, place in enumerate(pool)}
    return sorted(places, key=lambda place: order[place.id])


def _visit_warnings(place: Place, window: tuple[time, time] | None, clamp_warning: str | None) -> list[str]:
    warnings = [_OPENING_CHECK]
    if window is not None:
        warnings.append("A same-day source hour range was applied; days of operation remain unverified.")
    else:
        warnings.append("No safely parseable opening-hour range was available.")
    if place.visit_minutes is None:
        warnings.append("Visit duration is a category-based assumption.")
    if clamp_warning is not None:
        warnings.append(clamp_warning)
    return warnings
