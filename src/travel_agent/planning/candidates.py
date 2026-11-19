"""Chọn candidate POI cho một PlanRequest. Hàm thuần, xác định theo seed.

Bảng sở thích và các hằng số là heuristic sản phẩm, chưa kiểm chứng bằng dữ liệu người dùng.
Chỉ lấy địa điểm trong bán kính quanh Đại Nội, bán kính tùy phương tiện.
"""

from __future__ import annotations

import math
import random
import re
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

# Điểm tham quan nổi tiếng (landmark) thêm vào candidate khi `landmarks > 0` và không đi bộ.
# Không lấy nhà hàng và quán cà phê: chúng đã có chỗ riêng qua giữ chỗ bữa ăn và sở thích.
LANDMARK_EXCLUDED_CATEGORIES: frozenset[Category] = frozenset({Category.RESTAURANT, Category.CAFE})
# Số landmark mặc định của lệnh `plan` và `ask` (thư viện mặc định 0 để giữ eval không đổi).
DEFAULT_LANDMARKS = 6
# Khi không có sở thích khớp: lịch sử (di tích, bảo tàng), tâm linh (chùa, nhà thờ), điểm tham quan.
DEFAULT_LANDMARK_CATEGORIES: frozenset[Category] = frozenset(
    {Category.HISTORIC, Category.MUSEUM, Category.RELIGIOUS, Category.ATTRACTION}
)
# Thuộc tính "Đánh giá" có dạng "4.4/5 (29 lượt, Google)". Dấu thập phân là "." hoặc ",";
# số lượt có thể có dấu phân nghìn "." hoặc ",".
_RATING_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*/\s*5")
_REVIEWS_RE = re.compile(r"\((\d[\d.,]*)\s*lượt")


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


def popularity_score(place: Place) -> float:
    """Độ phổ biến từ thuộc tính "Đánh giá" (vd "4.4/5 (29 lượt, Google)"); 0 nếu không đọc được.

    Công thức: log10(1 + số lượt đánh giá) + điểm sao / 10.
    - Số lượt là tín hiệu chính: đo số người đã đến và đánh giá, và log làm giảm chênh lệch lớn.
      Điểm sao của điểm tham quan thường nằm quanh 4,5-4,7 nên ít phân biệt được; đã thử nhân
      sao với log lượt và điểm lăng vua không vào top 6 của Huế.
    - Điểm sao chỉ là tie-break (tối đa 0,5, tức cỡ một chênh lệch khoảng 3 lần số lượt).
    - Không có số lượt (chỉ "4.8/5") thì điểm là điểm sao / 10: vẫn xếp sau điểm có lượt.
    - Số lượt đọc bằng cách bỏ mọi dấu "." và "," (phân nghìn). Thiếu hoặc lỗi thì 0.
    """
    text = place.attributes.get("Đánh giá")
    if not text:
        return 0.0
    rating_match = _RATING_RE.search(text)
    if rating_match is None:
        return 0.0
    rating = min(max(float(rating_match.group(1).replace(",", ".")), 0.0), 5.0)
    reviews_match = _REVIEWS_RE.search(text)
    if reviews_match is None:
        return rating / 10
    digits = re.sub(r"\D", "", reviews_match.group(1))
    reviews = int(digits) if digits else 0
    return math.log10(1 + reviews) + rating / 10


def landmark_places(
    request: PlanRequest,
    places: Sequence[Place],
    limit: int,
    *,
    excluded_ids: Collection[str],
    excluded_categories: Collection[Category],
    reserved_ids: Collection[str],
) -> list[Place]:
    """Tối đa `limit` điểm tham quan nổi tiếng theo độ phổ biến giảm dần; không phụ thuộc seed.

    Bỏ qua bán kính (điểm xa vẫn được xét), loại nhà hàng và quán cà phê, tôn trọng loại trừ,
    và bỏ các id đã có (`reserved_ids`: điểm bắt buộc). Hòa điểm thì xếp theo id.
    Đi bộ không có landmark: bán kính đi bộ quá nhỏ để điểm xa có ý nghĩa.
    """
    if limit <= 0 or request.travel_mode is TravelMode.WALK:
        return []
    wanted = preferred_categories(request.interests) or set(DEFAULT_LANDMARK_CATEGORIES)
    allowed = (wanted - LANDMARK_EXCLUDED_CATEGORIES) - set(excluded_categories)
    if not allowed:
        return []
    skipped = set(excluded_ids) | set(reserved_ids)
    pool = [place for place in places if place.category in allowed and place.id not in skipped]
    ranked = sorted(pool, key=lambda item: (-popularity_score(item), item.id))
    return ranked[:limit]


def select_candidates(
    request: PlanRequest,
    places: Sequence[Place],
    seed: int,
    *,
    must_include: Sequence[str] = (),
    exclude_ids: Collection[str] = (),
    exclude_categories: Collection[Category] = (),
    landmarks: int = 0,
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
    - `landmarks`: tối đa số điểm tham quan nổi tiếng (xem `landmark_places`) thêm vào, bỏ qua bán
      kính. Chúng chiếm chỗ của điểm thường xếp cuối, không chiếm chỗ bữa ăn, và tổng vẫn bằng
      `candidate_limit`. Đi bộ hoặc 0 thì không thêm điểm nào.
    """
    if landmarks < 0:
        raise ValueError("landmarks không được âm")
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

    limit = candidate_limit(request)
    landmark_list = landmark_places(
        request,
        places,
        min(landmarks, max(0, limit - len(must_places))),
        excluded_ids=excluded_ids,
        excluded_categories=excluded_categories,
        reserved_ids=must_set,
    )
    landmark_set = {place.id for place in landmark_list}
    reserved = must_set | landmark_set

    queues: dict[Category, list[Place]] = {category: [] for category in Category}
    nearby = [
        place
        for place in places
        if within_radius(place, request.travel_mode)
        and place.id not in excluded_ids
        and place.category not in excluded_categories
        and place.id not in reserved
    ]
    for place in sorted(nearby, key=lambda item: item.id):
        queues[place.category].append(place)
    for queue in queues.values():
        rng.shuffle(queue)

    free = max(0, limit - len(must_places) - len(landmark_list))  # chỗ cho điểm thường
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
    chosen.extend(landmark_list)
    rng.shuffle(chosen)
    return chosen
