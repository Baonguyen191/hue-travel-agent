"""Chọn candidate POI cho một PlanRequest. Hàm thuần, xác định theo seed.

Bảng sở thích và các hằng số là heuristic sản phẩm, chưa kiểm chứng bằng dữ liệu người dùng.
Chỉ lấy địa điểm trong bán kính quanh Đại Nội, bán kính tùy phương tiện.
"""

from __future__ import annotations

import random
from collections.abc import Collection, Sequence

from travel_agent.domain.models import (
    Category,
    Coordinates,
    Pace,
    Place,
    PlanRequest,
    TravelMode,
)
from travel_agent.routing.travel_time import haversine_m

# Đại Nội. Bán kính chọn ngày 2026-11-14 từ số đo trên 70 request dev: không lọc thì 19% cặp
# candidate đi xe và 47% cặp đi bộ cần hơn 60 phút di chuyển; với bán kính này còn khoảng 1%.
# 12 km giữ được khu lăng (lăng Minh Mạng cách khoảng 11 km).
CITY_CENTER = Coordinates(lat=16.4698, lon=107.5786)
MAX_RADIUS_KM: dict[TravelMode, float] = {
    TravelMode.WALK: 2.0,
    TravelMode.MOTORBIKE: 12.0,
    TravelMode.CAR: 12.0,
}

INTEREST_CATEGORIES: dict[str, tuple[Category, ...]] = {
    "history": (Category.HISTORIC, Category.MUSEUM),
    "culture": (Category.MUSEUM, Category.RELIGIOUS, Category.HISTORIC),
    "spiritual": (Category.RELIGIOUS,),
    "food": (Category.RESTAURANT, Category.MARKET),
    "coffee": (Category.CAFE,),
    "nature": (Category.PARK, Category.VIEWPOINT),
    "photography": (Category.VIEWPOINT, Category.HISTORIC, Category.PARK),
    "shopping": (Category.MARKET,),
    "sightseeing": (Category.ATTRACTION, Category.VIEWPOINT),
}

# Khớp ngưỡng `overloaded_day` của validator.
MAX_STOPS_PER_DAY: dict[Pace, int] = {Pace.RELAXED: 4, Pace.MODERATE: 6, Pace.PACKED: 8}

MIN_CANDIDATES = 12
MAX_CANDIDATES = 30
SPARE_CANDIDATES = 4
MEALS_PER_DAY = 2
PREFERRED_PICKS_PER_ROUND = 2


def candidate_limit(request: PlanRequest) -> int:
    """Đủ điểm cho ngày dày nhất (validator cấm lặp place_id), cộng vài điểm dự phòng."""
    wanted = MAX_STOPS_PER_DAY[request.pace] * request.num_days + SPARE_CANDIDATES
    return max(MIN_CANDIDATES, min(MAX_CANDIDATES, wanted))


def within_radius(place: Place, mode: TravelMode) -> bool:
    return haversine_m(CITY_CENTER, place.coords) <= MAX_RADIUS_KM[mode] * 1000


def preferred_categories(interests: Sequence[str]) -> set[Category]:
    found: set[Category] = set()
    for interest in interests:
        found.update(INTEREST_CATEGORIES.get(interest.strip().lower(), ()))
    return found


def select_candidates(
    request: PlanRequest,
    places: Sequence[Place],
    seed: int,
    *,
    must_include: Sequence[str] = (),
    exclude_ids: Collection[str] = (),
    exclude_categories: Collection[Category] = (),
) -> list[Place]:
    """Giữ chỗ cho bữa ăn, rồi lấy xoay vòng theo loại; loại khớp sở thích được lấy nhiều hơn.

    Mỗi vòng đi loại khớp sở thích trước, rồi tới các loại còn lại bắt đầu từ vị trí xoay theo seed,
    để khi limit nhỏ loại bị cắt không luôn là loại cuối enum.

    Tùy chọn (mặc định không đổi kết quả so với trước khi có tùy chọn):
    - `exclude_ids`, `exclude_categories`: bỏ trước khi chọn, kể cả khi điểm nằm trong
      `must_include`.
      Loại trừ thắng bắt buộc: điểm vừa bắt buộc vừa bị loại thì không vào candidate.
    - `must_include`: id địa điểm bắt buộc có mặt, bỏ qua bán kính. Id không có trong `places` bị
      bỏ qua lặng lẽ. Tổng số candidate giữ nguyên bằng `candidate_limit`: điểm bắt buộc chiếm chỗ
      của các điểm không bắt buộc xếp cuối (lấy sau). Nếu số điểm bắt buộc vượt limit thì giữ hết
      điểm bắt buộc và không lấy thêm điểm nào khác.
    """
    rng = random.Random(seed)
    excluded_ids = set(exclude_ids)
    excluded_categories = set(exclude_categories)
    by_id = {place.id: place for place in places}
    must_ids = list(dict.fromkeys(must_include))  # bỏ trùng, giữ thứ tự người dùng
    must_places = [
        by_id[place_id]
        for place_id in must_ids
        if place_id in by_id
        and place_id not in excluded_ids
        and by_id[place_id].category not in excluded_categories
    ]
    must_set = {place.id for place in must_places}

    queues: dict[Category, list[Place]] = {category: [] for category in Category}
    nearby = [
        place
        for place in places
        if within_radius(place, request.travel_mode)
        and place.id not in excluded_ids
        and place.category not in excluded_categories
        and place.id not in must_set
    ]
    for place in sorted(nearby, key=lambda item: item.id):
        queues[place.category].append(place)
    for queue in queues.values():
        rng.shuffle(queue)

    limit = candidate_limit(request)
    free = max(0, limit - len(must_places))  # chỗ còn lại cho điểm không bắt buộc
    meals = min(MEALS_PER_DAY * request.num_days, free // 2)
    restaurants = queues[Category.RESTAURANT]
    chosen = restaurants[:meals]
    del restaurants[:meals]

    preferred = preferred_categories(request.interests)
    first = [category for category in Category if category in preferred]
    rest = [category for category in Category if category not in preferred]
    start = rng.randrange(len(rest)) if rest else 0
    order = [*first, *rest[start:], *rest[:start]]
    # Mỗi vòng: một điểm cho mỗi loại khớp sở thích, một điểm cho mỗi loại còn lại, rồi các điểm
    # thêm của loại khớp sở thích. Nhờ vậy khi limit nhỏ, mọi loại khớp sở thích vẫn có mặt.
    passes = [(order, 1), (first, PREFERRED_PICKS_PER_ROUND - 1)]
    while len(chosen) < free and any(queues.values()):
        for categories, picks in passes:
            for category in categories:
                for _ in range(picks):
                    if queues[category] and len(chosen) < free:
                        chosen.append(queues[category].pop())
    chosen.extend(must_places)
    rng.shuffle(chosen)
    return chosen
