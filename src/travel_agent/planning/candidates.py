"""Chọn candidate POI cho một PlanRequest. Hàm thuần, xác định theo seed.

Bảng sở thích và các hằng số là heuristic sản phẩm, chưa kiểm chứng bằng dữ liệu người dùng.
"""

from __future__ import annotations

import random
from collections.abc import Sequence

from travel_agent.domain.models import Category, Pace, Place, PlanRequest

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


def preferred_categories(interests: Sequence[str]) -> set[Category]:
    found: set[Category] = set()
    for interest in interests:
        found.update(INTEREST_CATEGORIES.get(interest.strip().lower(), ()))
    return found


def select_candidates(request: PlanRequest, places: Sequence[Place], seed: int) -> list[Place]:
    """Giữ chỗ cho bữa ăn, rồi lấy xoay vòng theo loại; loại khớp sở thích được lấy nhiều hơn."""
    rng = random.Random(seed)
    queues: dict[Category, list[Place]] = {category: [] for category in Category}
    for place in sorted(places, key=lambda item: item.id):
        queues[place.category].append(place)
    for queue in queues.values():
        rng.shuffle(queue)

    limit = candidate_limit(request)
    meals = min(MEALS_PER_DAY * request.num_days, limit // 2)
    restaurants = queues[Category.RESTAURANT]
    chosen = restaurants[:meals]
    del restaurants[:meals]

    preferred = preferred_categories(request.interests)
    while len(chosen) < limit and any(queues.values()):
        for category in Category:
            picks = PREFERRED_PICKS_PER_ROUND if category in preferred else 1
            for _ in range(picks):
                if queues[category] and len(chosen) < limit:
                    chosen.append(queues[category].pop())
    rng.shuffle(chosen)
    return chosen
