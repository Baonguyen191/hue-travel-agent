"""Dữ liệu giả cho test validator. Không phải dữ liệu thật của Huế."""

import datetime as dt

from travel_agent.data.place_repository import InMemoryPlaceRepository
from travel_agent.domain.models import (
    Category,
    Coordinates,
    Itinerary,
    Pace,
    Place,
    PlannedDay,
    PlannedStop,
    PlanRequest,
    TravelMode,
)
from travel_agent.routing.travel_time import TravelLeg

DAY1 = dt.date(2026, 11, 4)
COLLECTED = dt.datetime(2026, 11, 3, tzinfo=dt.UTC)

StopSpec = tuple[str, str, str]  # (place_id, arrive "HH:MM", depart "HH:MM")

VALID_DAY: list[StopSpec] = [
    ("t:museum", "08:30", "10:30"),
    ("t:cafe", "10:45", "11:15"),
    ("t:lunch", "11:30", "12:30"),
    ("t:dinner", "18:00", "19:00"),
]


def _place(pid: str, category: Category, lat: float, lon: float, hours: str | None) -> Place:
    return Place(
        id=pid,
        name=pid,
        category=category,
        coords=Coordinates(lat=lat, lon=lon),
        opening_hours_raw=hours,
        source="test",
        source_place_id=pid,
        license="test-only",
        collected_at=COLLECTED,
    )


def sample_places() -> InMemoryPlaceRepository:
    return InMemoryPlaceRepository(
        [
            _place("t:museum", Category.MUSEUM, 16.4700, 107.5800, "Mo-Su 07:00-17:00"),
            _place("t:cafe", Category.CAFE, 16.4710, 107.5810, None),
            _place("t:lunch", Category.RESTAURANT, 16.4720, 107.5790, "Mo-Su 10:00-22:00"),
            _place("t:dinner", Category.RESTAURANT, 16.4690, 107.5820, "Mo-Su 16:00-22:00"),
            _place("t:viewpoint", Category.VIEWPOINT, 16.4680, 107.5830, "24/7"),
        ]
    )


def make_request(num_days: int = 1, pace: Pace = Pace.MODERATE) -> PlanRequest:
    return PlanRequest(
        start_date=DAY1, num_days=num_days, pace=pace, travel_mode=TravelMode.MOTORBIKE
    )


def make_day(stops: list[StopSpec], date: dt.date = DAY1) -> PlannedDay:
    return PlannedDay(
        date=date,
        stops=[
            PlannedStop(
                place_id=pid,
                arrive=dt.time.fromisoformat(arrive),
                depart=dt.time.fromisoformat(depart),
            )
            for pid, arrive, depart in stops
        ],
    )


def make_itinerary(*days: PlannedDay) -> Itinerary:
    return Itinerary(days=list(days))


class FixedTravelTime:
    """Stub: mọi chặng tốn đúng `minutes` phút."""

    def __init__(self, minutes: float = 10.0, estimated: bool = False) -> None:
        self.minutes = minutes
        self.estimated = estimated

    def travel_leg(
        self, origin: Coordinates, destination: Coordinates, mode: TravelMode
    ) -> TravelLeg:
        return TravelLeg(
            distance_m=1000.0, minutes=self.minutes, estimated=self.estimated, source="fixed_test"
        )
