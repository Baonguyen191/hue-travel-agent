"""Thời lượng tham quan thật của một điểm, lấy từ dữ liệu DB khi có. Hàm thuần, không mạng.

Nguồn: thuộc tính `Thời gian trải nghiệm TB (phút)` của địa điểm (khoảng 1.000 điểm trong
`data/hue.sqlite`, toàn bộ là số nguyên dạng chuỗi như "60", "120"). Phần đọc còn nhận thêm
các dạng khác để không hỏng khi dữ liệu nguồn thay đổi: "60 phút", "2 giờ", "1,5 giờ",
"1 giờ 30 phút", khoảng "90-120" hoặc "1-2 giờ" (lấy trung điểm). Chuỗi không đọc được thì
trả None và người gọi dùng giá trị dự phòng.

Thứ tự ưu tiên khi tính lượt thăm (xem `visit_minutes`): thuộc tính DB, rồi thời lượng model
ghi (nếu > 0), rồi hằng số theo loại trong `VISIT_MINUTES`.
"""

from __future__ import annotations

import re

from travel_agent.domain.models import Place
from travel_agent.planning.solver import VISIT_MINUTES

VISIT_ATTRIBUTE = "Thời gian trải nghiệm TB (phút)"
MIN_VISIT_MINUTES = 20
MAX_VISIT_MINUTES = 240

_NUMBER = r"\d+(?:[.,]\d+)?"
_UNIT = r"(giờ|gio|h|phút|phut|ph|p)"
# "1 giờ 30 phút"
_HOURS_MINUTES_RE = re.compile(
    r"^\s*(\d+)\s*(?:giờ|gio|h)\s*(\d+)\s*(?:phút|phut|ph|p)?\s*$", re.IGNORECASE
)
# "90-120", "1-2 giờ", "90 – 120 phút"
_RANGE_RE = re.compile(
    rf"^\s*({_NUMBER})\s*(?:-|–|—|đến)\s*({_NUMBER})\s*{_UNIT}?\s*$", re.IGNORECASE
)
# "60", "60 phút", "2 giờ", "1,5 giờ"
_SINGLE_RE = re.compile(rf"^\s*({_NUMBER})\s*{_UNIT}?\s*$", re.IGNORECASE)


def parse_visit_minutes(raw: str | None) -> int | None:
    """Số phút của chuỗi thuộc tính; None nếu không đọc được hoặc không dương.

    Không có đơn vị thì hiểu là phút. Khoảng lấy trung điểm, làm tròn đến phút gần nhất.
    """
    if raw is None:
        return None
    text = raw.strip()
    match = _HOURS_MINUTES_RE.match(text)
    if match:
        minutes = int(match.group(1)) * 60 + int(match.group(2))
        return minutes if minutes > 0 else None
    match = _RANGE_RE.match(text)
    if match:
        low = _to_minutes(match.group(1), match.group(3))
        high = _to_minutes(match.group(2), match.group(3))
        return _positive_round((low + high) / 2)
    match = _SINGLE_RE.match(text)
    if match:
        return _positive_round(_to_minutes(match.group(1), match.group(2)))
    return None


def _to_minutes(number: str, unit: str | None) -> float:
    """Số trong chuỗi (dấu phẩy hoặc chấm thập phân) đổi sang phút theo đơn vị; mặc định phút."""
    value = float(number.replace(",", "."))
    is_hours = unit is not None and unit.lower() in {"giờ", "gio", "h"}
    return value * 60 if is_hours else value


def _positive_round(minutes: float) -> int | None:
    rounded = int(minutes + 0.5)
    return rounded if rounded > 0 else None


def visit_minutes(place: Place, model_minutes: int) -> int:
    """Lượt thăm của `place` tính bằng phút, đã kẹp về [MIN_VISIT_MINUTES, MAX_VISIT_MINUTES].

    Ưu tiên thuộc tính DB; không có thì thời lượng model ghi nếu > 0; không thì hằng số theo loại.
    Chỉ kẹp giá trị từ DB, còn thời lượng model ghi giữ nguyên như trước.
    """
    parsed = parse_visit_minutes(place.attributes.get(VISIT_ATTRIBUTE))
    if parsed is not None:
        return min(max(parsed, MIN_VISIT_MINUTES), MAX_VISIT_MINUTES)
    if model_minutes > 0:
        return model_minutes
    return VISIT_MINUTES[place.category]
