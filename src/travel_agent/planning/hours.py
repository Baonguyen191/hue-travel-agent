"""Khung giờ dùng chung cho solver và retime: khung ngày, giờ mở cửa, đổi giữa phút và giờ.

Mọi giờ ở đây là phút tuyệt đối: ngày d chiếm [d * 1440, (d + 1) * 1440). Hàm thuần, không I/O.
Làm tròn khớp với validator: giờ bắt đầu làm tròn lên, giờ kết thúc làm tròn xuống, nên một
lượt thăm nằm trong [start, end] phút tuyệt đối thì cũng nằm trong khung giờ của validator.
"""

from __future__ import annotations

import datetime as dt

from travel_agent.domain.models import Place, PlanRequest
from travel_agent.domain.opening_hours import parse_opening_hours

MINUTES_PER_DAY = 24 * 60

Interval = tuple[int, int]  # (bắt đầu, kết thúc) phút tuyệt đối, đóng hai đầu


def minute_ceil(value: dt.time) -> int:
    return value.hour * 60 + value.minute + (1 if value.second or value.microsecond else 0)


def minute_floor(value: dt.time) -> int:
    return value.hour * 60 + value.minute


def time_of(absolute: int) -> dt.time:
    """Giờ trong ngày (bỏ phần ngày) của một phút tuyệt đối."""
    minute = absolute % MINUTES_PER_DAY
    return dt.time(minute // 60, minute % 60)


def day_bounds(request: PlanRequest, day: int) -> Interval:
    """Khung ngày của `day`: từ day_start (làm tròn lên) đến day_end (làm tròn xuống)."""
    base = day * MINUTES_PER_DAY
    return base + minute_ceil(request.day_start), base + minute_floor(request.day_end)


def open_ranges(request: PlanRequest, place: Place, day: int) -> list[Interval]:
    """Khoảng mở cửa (phút tuyệt đối) trong ngày `day`; giờ chưa rõ thì là cả khung ngày.

    Chưa cắt theo khung ngày: người gọi tự cắt nếu cần. Thứ tự là thứ tự trong dữ liệu.
    """
    hours = parse_opening_hours(place.opening_hours_raw)
    if hours is None:
        return [day_bounds(request, day)]
    weekday = (request.start_date + dt.timedelta(days=day)).weekday()
    base = day * MINUTES_PER_DAY
    return [
        (base + minute_ceil(r.start), base + minute_floor(r.end))
        for r in hours.by_weekday.get(weekday, ())
    ]
