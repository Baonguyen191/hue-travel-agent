"""Dữ liệu giả cho test planning. Không phải dữ liệu thật của Huế."""

import datetime as dt
import math
import random
from collections.abc import Sequence

from travel_agent.domain.models import (
    Category,
    Coordinates,
    Pace,
    Place,
    PlanRequest,
    TravelMode,
)
from travel_agent.planning.candidates import CITY_CENTER

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
    travel_mode: TravelMode = TravelMode.MOTORBIKE,
) -> PlanRequest:
    return PlanRequest(
        start_date=START,
        num_days=num_days,
        pace=pace,
        travel_mode=travel_mode,
        interests=list(interests),
    )


KM_PER_DEGREE_LAT = 111.0

# Khung ngày giống các giá trị `training/requests.py` sinh ra.
DAY_WINDOWS = (
    (dt.time(7, 30), dt.time(21, 0)),
    (dt.time(8, 0), dt.time(20, 0)),
    (dt.time(9, 0), dt.time(18, 0)),
    (dt.time(8, 0), dt.time(21, 0)),
)
POOL_SIZES: dict[Category, int] = {
    Category.RESTAURANT: 16,
    Category.CAFE: 8,
    Category.HISTORIC: 8,
    Category.MUSEUM: 4,
    Category.RELIGIOUS: 5,
    Category.ATTRACTION: 5,
    Category.PARK: 4,
    Category.MARKET: 4,
    Category.VIEWPOINT: 4,
}
# Trộn giờ đã biết (có khung nghỉ trưa, có ngày đóng cửa) với giờ chưa rõ (None).
SIGHT_HOURS: tuple[str | None, ...] = (
    None,
    "07:30-17:30",
    "Mo-Su 08:00-11:30,13:30-17:00",
    "Tu-Su 07:00-17:00",
    "Mo-Tu,Th-Su 08:00-17:00",
    "24/7",
    "06:30-18:30",
    None,
)
# Nhà hàng nào cũng phục vụ được cả hai bữa: select_candidates chỉ giữ đúng 2 nhà hàng mỗi ngày,
# nên một quán chỉ bán sáng làm request thành bất khả thi (có test riêng cho ca đó).
RESTAURANT_HOURS: tuple[str | None, ...] = (
    None,
    "07:00-22:00",
    "10:00-22:00",
    "10:30-14:00,17:00-21:30",
    "06:30-21:00",
    "Mo-Su 10:00-23:00",
    "08:00-22:00",
)


def offset(km_north: float, km_east: float) -> tuple[float, float]:
    lat = CITY_CENTER.lat + km_north / KM_PER_DEGREE_LAT
    km_per_degree_lon = KM_PER_DEGREE_LAT * math.cos(math.radians(CITY_CENTER.lat))
    return lat, CITY_CENTER.lon + km_east / km_per_degree_lon


def spread_pool() -> list[Place]:
    """Khoảng 1/4 số điểm nằm ngoài bán kính đi bộ (3-9 km), còn lại trong 1,9 km."""
    rng = random.Random(7)
    pool: list[Place] = []
    for category, size in POOL_SIZES.items():
        hours = RESTAURANT_HOURS if category is Category.RESTAURANT else SIGHT_HOURS
        for index in range(size):
            radius = rng.uniform(3.0, 9.0) if index % 4 == 3 else rng.uniform(0.1, 1.9)
            angle = rng.uniform(0, 2 * math.pi)
            lat, lon = offset(radius * math.sin(angle), radius * math.cos(angle))
            pool.append(
                make_place(
                    f"t:{category.value}/{index}",
                    category,
                    hours=hours[index % len(hours)],
                    lat=lat,
                    lon=lon,
                )
            )
    return pool


def request_for(
    pace: Pace,
    num_days: int,
    mode: TravelMode,
    window: tuple[dt.time, dt.time] = DAY_WINDOWS[0],
    interests: Sequence[str] = ("history", "food"),
) -> PlanRequest:
    return PlanRequest(
        start_date=START,
        num_days=num_days,
        day_start=window[0],
        day_end=window[1],
        travel_mode=mode,
        pace=pace,
        interests=list(interests),
    )
