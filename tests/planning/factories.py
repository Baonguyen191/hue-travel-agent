"""Dữ liệu giả cho test planning. Không phải dữ liệu thật của Huế."""

import datetime as dt
from collections.abc import Sequence

from travel_agent.domain.models import (
    Category,
    Coordinates,
    Pace,
    Place,
    PlanRequest,
    TravelMode,
)

COLLECTED = dt.datetime(2026, 11, 3, tzinfo=dt.UTC)
START = dt.date(2026, 12, 1)  # thứ Ba


def make_place(
    pid: str,
    category: Category,
    hours: str | None = None,
    name: str | None = None,
    lat: float = 16.47,
    lon: float = 107.58,
) -> Place:
    return Place(
        id=pid,
        name=name or pid,
        category=category,
        coords=Coordinates(lat=lat, lon=lon),
        opening_hours_raw=hours,
        source="test",
        source_place_id=pid,
        license="test-only",
        collected_at=COLLECTED,
    )


def make_pool(per_category: int = 10) -> list[Place]:
    return [
        make_place(f"t:{category.value}/{index}", category)
        for category in Category
        for index in range(per_category)
    ]


def make_request(
    num_days: int = 1,
    pace: Pace = Pace.MODERATE,
    interests: Sequence[str] = (),
) -> PlanRequest:
    return PlanRequest(
        start_date=START,
        num_days=num_days,
        pace=pace,
        travel_mode=TravelMode.MOTORBIKE,
        interests=list(interests),
    )
