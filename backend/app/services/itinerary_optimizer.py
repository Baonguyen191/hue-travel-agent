"""Itinerary construction over real Hue POIs: area clusters, timed days, named meals."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field, replace
from datetime import date, datetime, time, timedelta
from math import ceil

from app.repositories.hue_places import HuePlacesRepository
from app.schemas.itinerary import (
    ItineraryDay,
    ItineraryEvent,
    ItineraryResult,
    TravelLeg,
    TravelMode,
)
from app.schemas.place import Place
from app.schemas.request import TripRequest
from app.schemas.search import SearchResult
from app.services.budget_optimizer import SIGHTSEEING_CATEGORIES
from app.services.guide import intro_for
from app.services.constraints import ConstraintConflictError, UnknownPoiError, is_allowed
from app.services.itinerary_validator import validate_itinerary
from app.services.meal_picker import MealPicker
from app.services.origin import starts_in_hue
from app.services.poi_search import haversine_km, normalize_vietnamese
from app.services.preferences import (
    NATURE_THEME,
    is_hue_specialty,
    is_nature,
    is_view_cafe,
    map_preferences,
    request_themes,
    source_type,
)

_FOOD_CATEGORIES = ("restaurant", "cafe")
# From this time a visit that would straddle the café window takes the café break first.
_CAFE_EARLY_CUTOFF = time(14, 30)
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
# Longest visit a stop is scheduled for, and the shorter cap for nature strolls.
_VISIT_CAP_MINUTES = 90
_STROLL_CAP_MINUTES = 60
_STROLL_PREFIXES = ("sông", "hồ", "cồn", "biển", "phá")
_HOURS_RANGE = re.compile(r"^(?P<open>\d{2}:\d{2})\s*-\s*(?P<close>\d{2}:\d{2})$")

# Visits per full day by pace; the sunset stop counts as a visit (S6, Q2).
PACE_VISITS: dict[str, int] = {"relaxed": 3, "moderate": 4, "packed": 5}
# Sunset in Huế by month, local time (S8). An estimate, labelled as such in the output.
SUNSET_TIMES: dict[int, time] = {
    1: time(17, 25), 2: time(17, 45), 3: time(17, 55), 4: time(18, 0),
    5: time(18, 10), 6: time(18, 20), 7: time(18, 20), 8: time(18, 5),
    9: time(17, 45), 10: time(17, 25), 11: time(17, 10), 12: time(17, 10),
}
_SUNSET_LEAD = timedelta(minutes=30)
_SUNSET_MINUTES = 45
_SUNSET_SLACK = timedelta(minutes=30)
_SUNSET_NOTE = "Sunset time is an estimate for the month (Huế, local time)."
# Lowercase name terms, with diacritics, that make a nature place a sunset stop.
_SUNSET_NAME_TERMS = ("sông", "hồ", "đồi", "cồn", "biển", "phá")
_REST_MINUTES = 60
_REST_NAME = "Nghỉ trưa"
# Extra candidate stops per day, so the schedule can fill its slots with the stops that fit.
_SPARE_STOPS = 3
# Time kept free before the sunset stop for the travel to the café, which is placed after the stops.
_TRAVEL_ALLOWANCE_MINUTES = 15
# A stop may run this long past the earliest lunch before lunch is taken; keeps a short overrun
# from pushing lunch, the rest and every later stop out of the day.
_LUNCH_GRACE = timedelta(minutes=30)
_EARLY_DINNER_MIN_MINUTES = 30  # a light meal before the return departure
_ARRIVAL_LEAD = timedelta(minutes=60)
_RETURN_SIGHTSEEING_LEAD = timedelta(hours=2)
_RETURN_DINNER_LEAD = timedelta(minutes=60)
_HUE = "Huế"
_MEAL_SLOTS = {"LUNCH": "lunch", "DINNER": "dinner", "CAFE": "cafe"}
_MODE_CODES: dict[str, TravelMode] = {"bus": "BUS", "train": "TRAIN", "flight": "FLIGHT"}

# Reason lines (Q4). Built by code only, Vietnamese, one short fact per stop.
_REASON_MUST = "bạn muốn đến"
_REASON_SUNSET = "điểm ngắm hoàng hôn"
_REASON_VIEW_CAFE = "cà phê có view"
_REASON_SPECIALTY = "đặc sản Huế"
_REASON_NATURE = "hợp sở thích thiên nhiên"
_REASON_RATING_MIN = 4.3
_REASON_REVIEWS_MIN = 50
_CATEGORY_REASON_NAMES: dict[str, str] = {
    "restaurant": "ẩm thực",
    "cafe": "cà phê",
    "market": "chợ",
    "historic": "di tích",
    "religious": "chùa chiền",
    "attraction": "tham quan",
    "park": "công viên",
    "museum": "bảo tàng",
}


@dataclass(frozen=True)
class _LegTimes:
    """Fixed estimates per mode: outbound departs `depart_offset` days from day 1."""

    depart_offset: int
    depart: time
    arrive: time
    return_depart: time
    return_journey: timedelta


_LEG_TIMES: dict[str, _LegTimes] = {
    "BUS": _LegTimes(-1, time(19, 0), time(7, 30), time(19, 0), timedelta(hours=12, minutes=30)),
    "TRAIN": _LegTimes(-1, time(19, 30), time(9, 0), time(19, 30), timedelta(hours=13, minutes=30)),
    "FLIGHT": _LegTimes(0, time(6, 0), time(7, 20), time(18, 30), timedelta(hours=1, minutes=20)),
}


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
    # None: the visit limit follows request.pace (see PACE_VISITS). A number caps it (retries).
    max_visits_per_day: int | None = None
    min_visit_minutes: int = 30
    max_visit_minutes: int = 180
    center_lat: float = 16.4698
    center_lon: float = 107.5786
    max_distance_km: float = 15.0
    meal_radius_km: float = 2.0
    min_separation_km: float = 0.3
    cluster_radius_km: float = 6.0
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
        if self.travel_speed_kmh <= 0:
            raise ValueError("travel speed must be positive")
        if self.max_visits_per_day is not None and self.max_visits_per_day <= 0:
            raise ValueError("max visits per day must be positive when set")
        if self.buffer_minutes < 0 or self.meal_radius_km < 0 or self.max_distance_km <= 0:
            raise ValueError("buffer, meal radius and max distance are out of range")
        if self.min_separation_km < 0 or self.cluster_radius_km <= 0:
            raise ValueError("min separation must be non-negative and cluster radius positive")


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
    """Return the visit length (capped for a stop) and a warning when a source value was clamped.

    A stop is at most 90 minutes; a nature stroll ("Sông", "Hồ", "Cồn", "Biển", "Phá") at most 60.
    A shorter source duration is kept. The cap never goes below the configured minimum.
    """
    minutes, warning = _source_duration_minutes(place, config)
    cap = _STROLL_CAP_MINUTES if _is_stroll(place) else _VISIT_CAP_MINUTES
    return min(minutes, max(cap, config.min_visit_minutes)), warning


def _source_duration_minutes(place: Place, config: ItineraryConfig) -> tuple[int, str | None]:
    default = min(max(_DEFAULT_VISIT_MINUTES[place.category], config.min_visit_minutes), config.max_visit_minutes)
    source = place.visit_minutes
    if source is None:
        return default, None
    if source > config.max_visit_minutes:
        return default, f"Source visit duration {source} min looks wrong; category default used."
    minutes = max(source, config.min_visit_minutes)
    if minutes == source:
        return minutes, None
    return minutes, f"Visit duration clamped from {source} to {minutes} minutes."


def _is_stroll(place: Place) -> bool:
    """A nature place named for water, a dune, a lagoon or a sea: a short walk, 60 minutes at most."""
    if not is_nature(place):
        return False
    return unicodedata.normalize("NFC", place.name).lower().startswith(_STROLL_PREFIXES)


@dataclass(frozen=True)
class _DayWindow:
    """What one calendar day allows: start, sightseeing end, dinner bounds and the sunset stop."""

    day: date
    start: datetime
    sightseeing_end: datetime
    # False on the return day (and on a same-day trip with travel): no rest, no forced café.
    full: bool
    dinner_earliest: datetime | None
    dinner_deadline: datetime | None
    # Sunset estimate minus 30 min; None when no sunset stop fits this day.
    sunset_start: datetime | None
    sunset: Place | None = None
    # Sightseeing stops this day may schedule: the pace limit, minus one when a sunset stop is planned.
    visit_slots: int = 0


@dataclass
class _DayState:
    """Mutable cursor for one day: where the traveller is and when they are free."""

    day: date
    current: datetime
    location: tuple[float, float]
    window: _DayWindow
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
        pool, excluded, merged = self._build_pool(request, search, centre)
        nature = NATURE_THEME in request_themes(request)
        meals = MealPicker(
            _food_candidates(search),
            self.places,
            self.config.meal_radius_km,
            allowed=lambda place: is_allowed(place, request),
            prefer=is_view_cafe if nature else None,
        )
        legs = self._travel_legs(request, search)
        days, unplanned = self._plan_days(request, pool, centre, meals, legs)
        days = self._with_reasons(days, request, search, nature)
        return ItineraryResult(
            days=days,
            unplanned_poi_ids=unplanned,
            excluded_poi_ids=excluded,
            merged_poi_ids=merged,
            warnings=self._global_warnings(excluded, merged, unplanned, request.must_include_poi_ids),
            validation=validate_itinerary(days),
            travel_legs=legs,
            sunset_estimate=f"{SUNSET_TIMES[request.start_date.month]:%H:%M}",
        )

    def _centre(self, request: TripRequest) -> tuple[float, float]:
        lat = request.center_lat if request.center_lat is not None else self.config.center_lat
        lon = request.center_lon if request.center_lon is not None else self.config.center_lon
        return lat, lon

    def _visit_limit(self, request: TripRequest) -> int:
        """Sightseeing stops per full day, sunset included: the pace, capped by the config if set."""
        limit = PACE_VISITS[request.pace]
        if self.config.max_visits_per_day is not None:
            limit = min(limit, self.config.max_visits_per_day)
        return limit

    def _build_pool(
        self, request: TripRequest, search: SearchResult, centre: tuple[float, float]
    ) -> tuple[list[Place], list[str], list[str]]:
        """Must-include POIs, then landmarks, then sightseeing candidates.

        Deduped by id and name, filtered by distance from the centre (never for a
        must-include POI), and thinned so every kept place is at least `min_separation_km`
        from the others. Excluded POIs and categories are skipped before anything else.
        """
        candidates = [item.place for item in search.poi_candidates]
        keyword = normalize_vietnamese(request.keyword) if request.keyword else ""
        # A market is a sightseeing stop only when it is a real market (or the user asked by keyword).
        sightseeing = [
            place
            for place in candidates
            if place.category in SIGHTSEEING_CATEGORIES
            and (place.category != "market" or keyword or _is_real_market(place))
        ]
        must = self._must_include(request, candidates)
        must_ids = set(request.must_include_poi_ids)
        # At most one market visit per trip day; must-include markets are kept and count toward it.
        market_cap = (request.end_date - request.start_date).days + 1
        market_count = 0
        kept: list[Place] = []
        excluded: list[str] = []
        merged: list[str] = []
        seen_ids: set[str] = set()
        seen_names: set[str] = set()
        for place in must + self._landmarks(request, candidates) + sightseeing:
            if not is_allowed(place, request):
                continue
            name_key = normalize_vietnamese(place.name)
            if place.id in seen_ids or name_key in seen_names:
                continue
            is_market = place.category == "market"
            if is_market and place.id not in must_ids and market_count >= market_cap:
                continue
            seen_ids.add(place.id)
            seen_names.add(name_key)
            if place.id not in must_ids and self._is_too_far(place, name_key, centre, keyword):
                excluded.append(place.id)
            elif self._too_close(place, kept):
                merged.append(place.id)
            else:
                kept.append(place)
                if is_market:
                    market_count += 1
        return kept, excluded, merged

    def _must_include(self, request: TripRequest, candidates: list[Place]) -> list[Place]:
        """Resolve each must-include id from Search's candidates, else from the POI source."""
        by_id = {place.id: place for place in candidates}
        found: list[Place] = []
        for poi_id in request.must_include_poi_ids:
            place = by_id[poi_id] if poi_id in by_id else self._lookup(poi_id)
            if place is None:
                raise UnknownPoiError(f"Unknown poi_id in must_include_poi_ids: {poi_id}")
            if not is_allowed(place, request):
                raise ConstraintConflictError(f"{place.name} is excluded and cannot be included.")
            found.append(place)
        return found

    def _too_close(self, place: Place, kept: list[Place]) -> bool:
        return any(
            haversine_km(place.lat, place.lon, other.lat, other.lon) < self.config.min_separation_km
            for other in kept
        )

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

    def _travel_legs(self, request: TripRequest, search: SearchResult) -> list[TravelLeg]:
        """Outbound the evening before day 1 and return on the last day; none when starting in Huế (S9)."""
        if starts_in_hue(request) or not search.transport_offers:
            return []
        mode = _leg_mode(request, search)
        times = _LEG_TIMES[mode]
        outbound_depart = datetime.combine(
            request.start_date + timedelta(days=times.depart_offset), times.depart
        )
        outbound_arrive = datetime.combine(request.start_date, times.arrive)
        return_depart = datetime.combine(request.end_date, times.return_depart)
        return [
            TravelLeg(
                direction="OUTBOUND", mode=mode, origin=request.origin, destination=_HUE,
                depart_at=outbound_depart, arrive_at=outbound_arrive,
            ),
            TravelLeg(
                direction="RETURN", mode=mode, origin=_HUE, destination=request.origin,
                depart_at=return_depart, arrive_at=return_depart + times.return_journey,
            ),
        ]

    def _plan_days(
        self,
        request: TripRequest,
        pool: list[Place],
        centre: tuple[float, float],
        meals: MealPicker,
        legs: list[TravelLeg],
    ) -> tuple[list[ItineraryDay], list[str]]:
        date_count = (request.end_date - request.start_date).days + 1
        protected = _protected_ids(request, self.config)
        limit = self._visit_limit(request)
        arrival = _leg_time(legs, "OUTBOUND", "arrive_at")
        departure = _leg_time(legs, "RETURN", "depart_at")
        remaining = list(pool)
        days: list[ItineraryDay] = []
        for offset in range(date_count):
            day_date = request.start_date + timedelta(days=offset)
            window = self._day_window(day_date, arrival, departure)
            # The sunset stop is picked first, near the day's first stop, and kept out of the
            # sightseeing candidates. One visit slot is reserved for it; without a sunset place the
            # slot goes back to sightseeing. The candidate list is wider than the slots so that
            # shorter stops can fill time that a long one does not fit.
            sunset = self._pick_sunset(remaining, remaining[0] if remaining else None, centre) if window.sunset_start else None
            candidates = [place for place in remaining if sunset is None or place.id != sunset.id]
            slots = limit - 1 if sunset is not None else limit
            day_set = self._cluster_day(candidates, protected, slots + _SPARE_STOPS)
            window = replace(window, sunset=sunset, visit_slots=slots)
            day, skipped, scheduled_set = self._schedule_with_landmarks(
                window, day_set, pool, centre, meals, protected
            )
            days.append(day)
            taken = {place.id for place in scheduled_set}
            taken |= {event.poi_id for event in day.events if event.kind == "VISIT" and event.poi_id}
            remaining = [place for place in remaining if place.id not in taken]
            remaining = _in_priority_order(remaining + skipped, pool)
        return days, [place.id for place in remaining]

    def _day_window(self, day_date: date, arrival: datetime | None, departure: datetime | None) -> _DayWindow:
        config = self.config
        start = datetime.combine(day_date, config.day_start)
        if arrival is not None and arrival.date() == day_date:
            start = max(start, arrival + _ARRIVAL_LEAD)
        sightseeing_end = datetime.combine(day_date, config.sightseeing_end)
        dinner_earliest: datetime | None = datetime.combine(day_date, config.dinner_earliest)
        dinner_deadline = None
        full = True
        if departure is not None and departure.date() == day_date:
            full = False
            sightseeing_end = min(sightseeing_end, departure - _RETURN_SIGHTSEEING_LEAD)
            dinner_deadline = departure - _RETURN_DINNER_LEAD
            dinner_earliest = None
        sunset_start = None
        candidate = datetime.combine(day_date, SUNSET_TIMES[day_date.month]) - _SUNSET_LEAD
        sunset_end = candidate + timedelta(minutes=_SUNSET_MINUTES)
        if sunset_end <= sightseeing_end and (dinner_earliest is None or sunset_end <= dinner_earliest):
            sunset_start = candidate
        return _DayWindow(
            day=day_date,
            start=start,
            sightseeing_end=sightseeing_end,
            full=full,
            dinner_earliest=dinner_earliest,
            dinner_deadline=dinner_deadline,
            sunset_start=sunset_start,
        )

    def _cluster_day(self, remaining: list[Place], protected: frozenset[str], capacity: int) -> list[Place]:
        """Seed with the highest-priority place; take nearby protected places, then nearest others.

        `capacity` is the number of sightseeing stops for the route (the sunset stop is not included).
        """
        if not remaining:
            return []
        seed, rest = remaining[0], remaining[1:]
        limit = capacity - 1

        def distance(place: Place) -> float:
            return haversine_km(seed.lat, seed.lon, place.lat, place.lon)

        by_distance = sorted(rest, key=lambda place: (distance(place), place.id))
        near_protected = [
            place for place in by_distance
            if place.id in protected and distance(place) <= self.config.cluster_radius_km
        ][:limit]
        # At most one market per day: a protected market counts too, a filler market is skipped.
        has_market = any(place.category == "market" for place in [seed, *near_protected])
        fillers: list[Place] = []
        for place in by_distance:
            if place.id in protected:
                continue
            if place.category == "market":
                if has_market:
                    continue
                has_market = True
            fillers.append(place)
        return [seed] + near_protected + fillers[: limit - len(near_protected)]

    @staticmethod
    def _pick_sunset(remaining: list[Place], anchor_place: Place | None, centre: tuple[float, float]) -> Place | None:
        """Nature place with water or a hill in its name, else a bridge; nearest to the day's first stop."""
        anchor = (anchor_place.lat, anchor_place.lon) if anchor_place is not None else centre
        natural = [place for place in remaining if is_nature(place) and _has_sunset_name(place.name)]
        bridges = [place for place in remaining if _is_bridge(place)]
        for tier in (natural, bridges):
            if tier:
                return min(tier, key=lambda place: (haversine_km(anchor[0], anchor[1], place.lat, place.lon), place.id))
        return None

    def _schedule_with_landmarks(
        self,
        window: _DayWindow,
        day_set: list[Place],
        pool: list[Place],
        centre: tuple[float, float],
        meals: MealPicker,
        protected: frozenset[str],
    ) -> tuple[ItineraryDay, list[Place], list[Place]]:
        """Schedule a day; while a protected place is skipped, drop the lowest-priority filler and retry."""
        used_before = meals.used_ids()
        while True:
            # Protected stops come first, in pool priority (must-include, then landmarks), so the
            # visit slots never go to a filler ahead of them; the rest follow nearest-first.
            nearest = self._nearest_route(day_set, centre)
            guarded = _in_priority_order([place for place in nearest if place.id in protected], pool)
            route = guarded + [place for place in nearest if place.id not in protected]
            day, skipped = self._schedule_day(window, route, centre, meals)
            filler = self._droppable_filler(day, day_set, skipped, pool, protected)
            if filler is None:
                return day, skipped, day_set
            meals.restore(used_before)
            day_set = [place for place in day_set if place.id != filler.id]

    def _droppable_filler(
        self,
        day: ItineraryDay,
        day_set: list[Place],
        skipped: list[Place],
        pool: list[Place],
        protected: frozenset[str],
    ) -> Place | None:
        if not any(place.id in protected for place in skipped):
            return None
        visited = {event.poi_id for event in day.events if event.kind == "VISIT"}
        fillers = [place for place in day_set if place.id in visited and place.id not in protected]
        if not fillers:
            return None
        return _in_priority_order(fillers, pool)[-1]

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
        self, window: _DayWindow, route: list[Place], centre: tuple[float, float], meals: MealPicker
    ) -> tuple[ItineraryDay, list[Place]]:
        state = _DayState(day=window.day, current=window.start, location=centre, window=window)
        for place in route:
            if sum(1 for event in state.events if event.kind == "VISIT") >= window.visit_slots:
                state.skipped.append(place)
                continue
            # Checked before any meal is placed, so a skipped stop does not pull lunch forward.
            if not self._fits_before_sunset(state, place):
                state.skipped.append(place)
                continue
            self._meals_before_visit(state, place, meals)
            self._visit(state, place)
        self._meals_after_route(state, meals)
        day = ItineraryDay(date=window.day, events=state.events, warnings=state.warnings)
        return day, state.skipped

    def _fits_before_sunset(self, state: _DayState, place: Place) -> bool:
        """True when this visit, its buffer and the still-due café end before the sunset stop."""
        window = state.window
        if window.sunset is None or window.sunset_start is None:
            return True
        travel, _ = self._travel(state.location, place)
        duration, _ = visit_duration_minutes(place, self.config)
        start = state.current + timedelta(minutes=travel)
        lunch_at = self._at(state, self.config.lunch_earliest) + _LUNCH_GRACE
        if not state.lunch_done and start + timedelta(minutes=duration) > lunch_at:
            # Lunch (and the rest after it on full days) comes before this stop.
            rest = _REST_MINUTES if window.full else 0
            start = max(start, lunch_at) + timedelta(minutes=self.config.lunch_minutes + rest)
        reserve = self.config.cafe_minutes + _TRAVEL_ALLOWANCE_MINUTES if self._cafe_due_later(state) else 0
        end = start + timedelta(minutes=duration + self.config.buffer_minutes + reserve)
        return end <= window.sunset_start

    def _cafe_due_later(self, state: _DayState) -> bool:
        return state.window.full and self.config.cafe_break and not state.cafe_done

    def _meals_before_visit(self, state: _DayState, place: Place, meals: MealPicker) -> None:
        travel, _ = self._travel(state.location, place)
        duration, _ = visit_duration_minutes(place, self.config)
        arrival = state.current + timedelta(minutes=travel)
        visit_end = arrival + timedelta(minutes=duration)
        lunch_at = self._at(state, self.config.lunch_earliest) + _LUNCH_GRACE
        if not state.lunch_done and visit_end > lunch_at:
            self._lunch(state, meals)
        if self._cafe_due(state, arrival, visit_end):
            self._cafe(state, meals, None)

    def _cafe_due(self, state: _DayState, arrival: datetime, visit_end: datetime) -> bool:
        # On the return day the café is optional and must not take a slot a stop needs.
        if not self.config.cafe_break or state.cafe_done or not state.window.full:
            return False
        if self.config.cafe_earliest <= state.current.time() <= self.config.cafe_latest:
            return True
        # A visit that starts late and runs into the café window: the café comes first.
        return (
            arrival.time() >= _CAFE_EARLY_CUTOFF
            and visit_end > self._at(state, self.config.cafe_earliest)
        )

    def _meals_after_route(self, state: _DayState, meals: MealPicker) -> None:
        """Lunch if still due, the café on full days, the sunset stop, then dinner (or the early dinner)."""
        window = state.window
        if not state.lunch_done:
            self._lunch(state, meals)
        if self._cafe_due_later(state):
            self._cafe(state, meals, self._cafe_start(state))
        if window.sunset is not None:
            self._sunset(state)
        if not self._schedule_meal(
            state, meals, "DINNER", "restaurant", window.dinner_earliest, self.config.dinner_minutes,
            deadline=window.dinner_deadline,
        ):
            if window.dinner_deadline is not None:
                state.warnings.append("No dinner fits before the return departure; no dinner is scheduled.")
            else:
                state.warnings.append("No restaurant candidate for dinner; no dinner is scheduled.")

    def _cafe_start(self, state: _DayState) -> datetime:
        """The café goes right before the sunset stop, inside the 15:00–16:30 window, not at 15:00 by default."""
        earliest = self._at(state, self.config.cafe_earliest)
        latest = self._at(state, self.config.cafe_latest)
        sunset_start = state.window.sunset_start
        if sunset_start is None:
            return earliest
        before_sunset = sunset_start - timedelta(minutes=self.config.cafe_minutes + _TRAVEL_ALLOWANCE_MINUTES)
        return max(earliest, min(before_sunset, latest))

    def _lunch(self, state: _DayState, meals: MealPicker) -> None:
        state.lunch_done = True
        earliest = self._at(state, self.config.lunch_earliest)
        if self._schedule_meal(state, meals, "LUNCH", "restaurant", earliest, self.config.lunch_minutes):
            self._rest(state)
            return
        start = max(state.current, earliest)
        end = start + timedelta(minutes=self.config.lunch_minutes)
        state.events.append(
            ItineraryEvent(
                kind="MEAL_BREAK", start_at=start, end_at=end, name="Meal break (lunch)", slot="lunch",
            )
        )
        state.current = end
        state.warnings.append("No restaurant candidate for lunch; an anonymous meal break is scheduled.")
        self._rest(state)

    def _rest(self, state: _DayState) -> None:
        """The 60-minute rest after lunch on full days (Q1)."""
        if not state.window.full:
            return
        end = state.current + timedelta(minutes=_REST_MINUTES)
        state.events.append(
            ItineraryEvent(kind="REST", start_at=state.current, end_at=end, name=_REST_NAME, slot="rest")
        )
        state.current = end

    def _cafe(self, state: _DayState, meals: MealPicker, earliest: datetime | None) -> None:
        state.cafe_done = True
        self._schedule_meal(state, meals, "CAFE", "cafe", earliest, self.config.cafe_minutes)

    def _schedule_meal(
        self,
        state: _DayState,
        meals: MealPicker,
        meal: str,
        category: str,
        earliest: datetime | None,
        minutes: int,
        deadline: datetime | None = None,
    ) -> bool:
        place = meals.pick(category, state.location[0], state.location[1])
        if place is None:
            return False
        travel, distance = self._travel(state.location, place)
        start = state.current + timedelta(minutes=travel)
        if earliest is not None:
            start = max(start, earliest)
        if deadline is not None:
            # The early dinner ends at the deadline (an hour before the return departure), not
            # straight after the last stop: a 15:30 "dinner" for a 19:00 bus is lunch-time food.
            start = max(start, deadline - timedelta(minutes=minutes))
            # It is shortened to fit before the deadline, or dropped.
            minutes = min(minutes, int((deadline - start).total_seconds() // 60))
            if minutes < _EARLY_DINNER_MIN_MINUTES:
                return False
        end = start + timedelta(minutes=minutes)
        state.events.append(
            ItineraryEvent(
                kind="MEAL", meal=meal, poi_id=place.id, name=place.name, category=place.category,
                slot=_MEAL_SLOTS[meal], lat=place.lat, lon=place.lon, start_at=start, end_at=end,
                travel_distance_km=round(distance, 3), travel_minutes_estimated=travel,
                warnings=[_OPENING_CHECK],
            )
        )
        meals.mark_used(place)
        state.current = end
        state.location = (place.lat, place.lon)
        return True

    def _sunset(self, state: _DayState) -> None:
        """The sunset stop: 45 minutes starting 30 minutes before the estimated sunset (S8)."""
        window = state.window
        place = window.sunset
        if place is None or window.sunset_start is None:
            return
        travel, distance = self._travel(state.location, place)
        hours = parse_simple_opening_window(place.opening_hours_raw)
        start = max(window.sunset_start, state.current + timedelta(minutes=travel))
        if hours is not None:
            start = max(start, self._at(state, hours[0]))
        if start > window.sunset_start + _SUNSET_SLACK:
            return
        end = start + timedelta(minutes=_SUNSET_MINUTES)
        if end > window.sightseeing_end:
            return
        if hours is not None and end > self._at(state, hours[1]):
            return
        state.events.append(
            ItineraryEvent(
                kind="VISIT", poi_id=place.id, name=place.name, category=place.category, slot="sunset",
                lat=place.lat, lon=place.lon, start_at=start, end_at=end, visit_minutes=_SUNSET_MINUTES,
                travel_distance_km=round(distance, 3), travel_minutes_estimated=travel,
                intro=intro_for(place.id), warnings=[*_visit_warnings(place, hours, None), _SUNSET_NOTE],
            )
        )
        state.current = end
        state.location = (place.lat, place.lon)

    def _visit(self, state: _DayState, place: Place) -> None:
        travel, distance = self._travel(state.location, place)
        duration, clamp_warning = visit_duration_minutes(place, self.config)
        hours = parse_simple_opening_window(place.opening_hours_raw)
        arrival = state.current + timedelta(minutes=travel)
        closes_at = None
        if hours is not None:
            arrival = max(arrival, self._at(state, hours[0]))
            closes_at = self._at(state, hours[1])
        visit_end = arrival + timedelta(minutes=duration)
        sightseeing_end = state.window.sightseeing_end
        if visit_end > sightseeing_end or (closes_at is not None and visit_end > closes_at):
            state.skipped.append(place)
            if closes_at is not None and visit_end > closes_at:
                state.warnings.append(f"{place.name} did not fit its source opening-hour range.")
            return
        state.events.append(
            ItineraryEvent(
                kind="VISIT", poi_id=place.id, name=place.name, category=place.category,
                slot="afternoon" if state.lunch_done else "morning",
                lat=place.lat, lon=place.lon, start_at=arrival, end_at=visit_end,
                visit_minutes=duration, travel_distance_km=round(distance, 3),
                travel_minutes_estimated=travel,
                intro=intro_for(place.id), warnings=_visit_warnings(place, hours, clamp_warning),
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

    def _with_reasons(
        self, days: list[ItineraryDay], request: TripRequest, search: SearchResult, nature: bool
    ) -> list[ItineraryDay]:
        """Attach the one-line reason to VISIT and MEAL events; facts only, never free text (Q4)."""
        by_id = {item.place.id: item.place for item in search.poi_candidates}
        result: list[ItineraryDay] = []
        for day in days:
            events: list[ItineraryEvent] = []
            for event in day.events:
                if event.kind in ("VISIT", "MEAL") and event.poi_id is not None:
                    place = by_id[event.poi_id] if event.poi_id in by_id else self._lookup(event.poi_id)
                    event = event.model_copy(update={"reason": _reason(event, place, request, nature)})
                events.append(event)
            result.append(day.model_copy(update={"events": events}))
        return result

    def _global_warnings(
        self,
        excluded: list[str],
        merged: list[str],
        unplanned: list[str],
        must_include: list[str],
    ) -> list[str]:
        warnings: list[str] = []
        if set(must_include) & set(unplanned):
            warnings.append("A must-include POI did not fit the itinerary time and is not scheduled.")
        if excluded:
            warnings.append(
                f"{len(excluded)} places farther than {self.config.max_distance_km:g} km from the centre were skipped."
            )
        if merged:
            warnings.append(
                f"{len(merged)} places sharing a location with an already chosen site were merged "
                "(for example inside Đại Nội)."
            )
        if unplanned:
            warnings.append("Some selected POIs did not fit in the available itinerary time.")
        warnings.append(
            "The hotel is assumed at the city centre; travel times are straight-line estimates, not road routes or ETAs."
        )
        warnings.append("Opening hours are source-provided or absent and require confirmation.")
        return warnings


def _leg_mode(request: TripRequest, search: SearchResult) -> TravelMode:
    """The requested mode; else the cheapest outbound offer's mode; else bus."""
    if request.transport_mode is not None:
        return _MODE_CODES[request.transport_mode]
    outbound = [offer for offer in search.transport_offers if offer.leg == "OUTBOUND"]
    if outbound:
        cheapest = min(outbound, key=lambda offer: (offer.price_vnd, offer.id))
        if cheapest.mode is not None:
            return cheapest.mode
    return "BUS"


def _leg_time(legs: list[TravelLeg], direction: str, attribute: str) -> datetime | None:
    for leg in legs:
        if leg.direction == direction:
            return getattr(leg, attribute)
    return None


def _has_sunset_name(name: str) -> bool:
    text = unicodedata.normalize("NFC", name).lower()
    return any(term in text for term in _SUNSET_NAME_TERMS)


def _is_bridge(place: Place) -> bool:
    return place.category == "park" and unicodedata.normalize("NFC", place.name).lower().startswith("cầu")


def _reason(event: ItineraryEvent, place: Place | None, request: TripRequest, nature: bool) -> str | None:
    """The first matching fact, in the order of Q4; None when no fact applies."""
    if event.poi_id in request.must_include_poi_ids:
        return _REASON_MUST
    if event.slot == "sunset":
        return _REASON_SUNSET
    if place is None:
        return None
    if is_view_cafe(place):
        return _REASON_VIEW_CAFE
    if is_hue_specialty(place):
        return _REASON_SPECIALTY
    if nature and is_nature(place):
        return _REASON_NATURE
    if place.category in request.categories and place.category in _CATEGORY_REASON_NAMES:
        return f"hợp sở thích {_CATEGORY_REASON_NAMES[place.category]}"
    rating, reviews = place.rating_value, place.rating_count
    if rating is not None and reviews is not None and rating >= _REASON_RATING_MIN and reviews >= _REASON_REVIEWS_MIN:
        return f"{rating:.1f}".replace(".", ",") + f"/5, {reviews} lượt"
    return None


def _protected_ids(request: TripRequest, config: ItineraryConfig) -> frozenset[str]:
    """POIs that fillers may never displace: the must-include ids and the landmarks."""
    return frozenset(request.must_include_poi_ids) | frozenset(config.landmark_ids)


def _is_real_market(place: Place) -> bool:
    """A "Chợ" by source type or by name ("Chợ ..."); specialty shops are not visited as markets."""
    kind = source_type(place)
    if kind is not None and normalize_vietnamese(kind) == "cho":
        return True
    return normalize_vietnamese(place.name).startswith("cho ")


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
