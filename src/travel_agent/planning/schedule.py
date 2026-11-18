"""Xếp lại giờ cho lịch trình model đã chọn điểm và thứ tự. Hàm thuần, xác định, không mạng.

Model chỉ cần chọn điểm và xếp thứ tự; code tính giờ theo quy tắc (xem plan 6, mục "Xếp giờ"):

- Ngày bắt đầu ở day_start. Giữ nguyên ngày (date) và thứ tự điểm của model.
- Điểm thường: giờ đến = max(giờ rảnh sớm nhất, giờ mở cửa sớm nhất còn vừa lượt thăm).
  Giờ rảnh = giờ rời điểm đã giữ trước + thời gian đi (làm tròn lên phút, cùng quy tắc với solver
  và validator). Lượt thăm = thời lượng model ghi nếu > 0, không thì VISIT_MINUTES[loại].
- Không vừa khung mở cửa hoặc vượt day_end thì bỏ điểm và ghi lý do. Điểm sau đó đi từ điểm
  đã giữ gần nhất.
- Mã địa điểm lạ (không có trong `places`): giữ nguyên dòng của model (giờ không đổi, không
  tính đi lại) và đẩy giờ rảnh tới giờ rời của nó. Validator sẽ báo unknown_place. Không đoán
  gì về điểm lạ.
- Ngày mà mọi điểm đều bị bỏ thì giữ điểm đầu của model nguyên giờ, vì schema bắt buộc mỗi ngày
  có ít nhất một điểm. Validator sẽ báo lỗi của điểm đó; điểm này không nằm trong `dropped`.
- Giờ mở cửa chưa rõ: coi như mở cả khung ngày (giống solver).
- Nhà hàng mà model đặt chồng lên một khung bữa (trưa, tối; chỉ khi khung ngày bao trọn khung đó)
  không được xếp sớm hơn giờ bắt đầu khung bữa. Nhờ vậy xếp lại giờ không làm mất bữa.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from travel_agent.data.place_repository import PlaceLookup
from travel_agent.domain.models import Itinerary, Place, PlannedDay, PlannedStop, PlanRequest
from travel_agent.planning.hours import (
    MINUTES_PER_DAY,
    Interval,
    day_bounds,
    minute_floor,
    open_ranges,
    time_of,
)
from travel_agent.planning.solver import VISIT_MINUTES
from travel_agent.routing.travel_time import TravelTimeProvider
from travel_agent.validation.validator import MEAL_CATEGORIES, MEAL_WINDOWS


@dataclass(frozen=True)
class DroppedStop:
    day_index: int
    place_id: str
    reason: str  # tiếng Việt, hiển thị cho người dùng và đưa vào prompt sửa


@dataclass(frozen=True)
class RetimeResult:
    itinerary: Itinerary
    dropped: list[DroppedStop]


def retime(
    request: PlanRequest,
    itinerary: Itinerary,
    places: PlaceLookup,
    travel: TravelTimeProvider,
) -> RetimeResult:
    days: list[PlannedDay] = []
    dropped: list[DroppedStop] = []
    for day_index, day in enumerate(itinerary.days):
        stops, day_dropped = _retime_day(request, day_index, day.stops, places, travel)
        days.append(PlannedDay(date=day.date, stops=stops))
        dropped.extend(day_dropped)
    return RetimeResult(itinerary=Itinerary(days=days), dropped=dropped)


def _retime_day(
    request: PlanRequest,
    day_index: int,
    model_stops: list[PlannedStop],
    places: PlaceLookup,
    travel: TravelTimeProvider,
) -> tuple[list[PlannedStop], list[DroppedStop]]:
    base = day_index * MINUTES_PER_DAY
    bound = day_bounds(request, day_index)
    clock = bound[0]  # phút sớm nhất mà điểm tiếp theo có thể đến (xe rảnh)
    origin: Place | None = None  # điểm đã giữ gần nhất
    origin_depart = bound[0]
    kept: list[PlannedStop] = []
    dropped: list[tuple[int, DroppedStop]] = []  # (vị trí trong ngày của model, lý do)
    for position, model_stop in enumerate(model_stops):
        place = places.get(model_stop.place_id)
        if place is None:
            kept.append(model_stop)
            clock = max(clock, base + minute_floor(model_stop.depart))
            continue
        visit = _visit_minutes(model_stop, place)
        ready = clock
        if origin is not None:
            ready = max(clock, origin_depart + _travel_minutes(request, origin, place, travel))
        meal_start = _meal_start(request, day_index, model_stop, place)
        if meal_start is not None:
            ready = max(ready, meal_start)
        ranges = open_ranges(request, place, day_index)
        arrive = _earliest_fit(ranges, bound, ready, visit)
        if arrive is None:
            reason = _drop_reason(ranges, bound, visit)
            dropped.append((position, DroppedStop(day_index, place.id, reason)))
            continue
        depart = arrive + visit
        kept.append(
            PlannedStop(
                place_id=place.id,
                arrive=time_of(arrive),
                depart=time_of(depart),
                note=model_stop.note,
            )
        )
        clock = origin_depart = depart
        origin = place
    if not kept:
        # Schema cần ít nhất một điểm mỗi ngày: giữ điểm đầu của model nguyên giờ để validator báo.
        kept.append(model_stops[0])
        dropped = [(position, entry) for position, entry in dropped if position != 0]
    return kept, [entry for _, entry in dropped]


def _meal_start(
    request: PlanRequest, day_index: int, model_stop: PlannedStop, place: Place
) -> int | None:
    """Giờ bắt đầu (phút tuyệt đối) của khung bữa mà điểm ăn của model chồng lên; None nếu không.

    Chỉ áp cho nhà hàng (MEAL_CATEGORIES) đã chồng lên một khung bữa trong lịch của model, và khung
    đó phải nằm trong khung ngày (cùng điều kiện với validator). Khi đó điểm không được xếp sớm hơn
    khung bữa, nên xếp lại giờ không làm mất bữa mà model đã có.
    """
    if place.category not in MEAL_CATEGORIES:
        return None
    starts = [
        window_start
        for _, window_start, window_end in MEAL_WINDOWS
        if request.day_start <= window_start
        and request.day_end >= window_end
        and model_stop.arrive < window_end
        and model_stop.depart > window_start
    ]
    if not starts:
        return None
    return day_index * MINUTES_PER_DAY + minute_floor(min(starts))


def _visit_minutes(model_stop: PlannedStop, place: Place) -> int:
    """Thời lượng model ghi nếu dương, không thì hằng số theo loại (chỉ ở mức phút)."""
    model = minute_floor(model_stop.depart) - minute_floor(model_stop.arrive)
    return model if model > 0 else VISIT_MINUTES[place.category]


def _travel_minutes(
    request: PlanRequest, origin: Place, destination: Place, travel: TravelTimeProvider
) -> int:
    """Cùng provider, cùng chiều và cùng làm tròn lên với validator, nên không lệch."""
    leg = travel.travel_leg(origin.coords, destination.coords, request.travel_mode)
    return math.ceil(leg.minutes)


def _earliest_fit(ranges: list[Interval], bound: Interval, ready: int, visit: int) -> int | None:
    """Giờ đến sớm nhất >= ready để cả lượt thăm nằm gọn trong khoảng mở cửa và khung ngày."""
    for start, end in sorted(ranges):
        start, end = max(start, bound[0]), min(end, bound[1])
        arrive = max(start, ready)
        if arrive + visit <= end:
            return arrive
    return None


def _drop_reason(ranges: list[Interval], bound: Interval, visit: int) -> str:
    """Lý do bỏ điểm, xét trên khoảng mở cửa đã cắt theo khung ngày."""
    if not ranges:
        return "đóng cửa cả ngày"
    clipped = [(max(s, bound[0]), min(e, bound[1])) for s, e in sorted(ranges)]
    clipped = [(s, e) for s, e in clipped if s < e]
    if not clipped:
        return "giờ mở cửa nằm ngoài khung ngày"
    fitting = [(s, e) for s, e in clipped if e - s >= visit]
    if not fitting:
        return f"giờ mở cửa quá ngắn cho lượt thăm {visit} phút"
    _, last_end = fitting[-1]
    return "vượt giờ kết thúc ngày" if last_end == bound[1] else "không kịp trước giờ đóng cửa"
