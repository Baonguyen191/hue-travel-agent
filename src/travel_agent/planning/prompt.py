"""Prompt sinh lịch trình. Nguồn duy nhất cho baseline, SFT, RL và runtime.

Sửa file này làm lệch dữ liệu đã train. Snapshot test sẽ vỡ để nhắc việc đó.
"""

from __future__ import annotations

import datetime as dt
import json
from collections.abc import Sequence

from travel_agent.domain.models import Itinerary, Place, PlanRequest, TravelMode
from travel_agent.routing.travel_time import HaversineEstimator
from travel_agent.validation.report import Issue, Severity


def _per_mode(values: dict[TravelMode, float], unit: str) -> str:
    return ", ".join(f"{mode.value} {values[mode]:g} {unit}" for mode in TravelMode)


# Số lấy thẳng từ HaversineEstimator (cùng ước tính validator dùng) để prompt không lệch validator.
TRAVEL_TIME_RULE = (
    "Điểm dừng trong ngày xếp theo thứ tự thời gian, không chồng giờ, và chừa đủ thời gian "
    "di chuyển giữa hai điểm. Thời gian di chuyển ước tính = khoảng cách đường chim bay "
    f"× {HaversineEstimator.DETOUR_FACTOR:g}, đi với tốc độ "
    f"{_per_mode(HaversineEstimator.SPEED_KMH, 'km/h')}, cộng thời gian khởi hành "
    f"{_per_mode(HaversineEstimator.START_OVERHEAD_MIN, 'phút')}."
)

_PROMPT_TEMPLATE = """Bạn lập lịch trình du lịch cho thành phố Huế.

Quy tắc bắt buộc:
1. Chỉ dùng place_id có trong danh sách ĐỊA ĐIỂM. Không tự tạo place_id.
2. Mỗi place_id chỉ xuất hiện một lần trong toàn bộ lịch trình.
3. Số ngày bằng đúng num_days. Ngày đầu là start_date, các ngày sau liên tiếp.
4. Mọi điểm dừng nằm trong khung day_start đến day_end. depart phải sau arrive.
5. @@TRAVEL_TIME_RULE@@
6. Nếu địa điểm có giờ mở cửa thì cả khoảng arrive đến depart phải nằm trong giờ mở cửa. \
"unknown" nghĩa là không rõ giờ.
7. Số điểm dừng mỗi ngày theo pace: relaxed 3 đến 4, moderate 4 đến 6, packed 6 đến 8.
8. Nếu khung ngày bao trọn 11:00-13:30 thì có một điểm restaurant trong khung đó. \
Tương tự với 17:30-20:00.
9. Ưu tiên địa điểm khớp interests.

Chỉ trả về JSON đúng dạng sau, không thêm chữ nào khác:
{"days":[{"date":"YYYY-MM-DD","stops":[{"place_id":"...","arrive":"HH:MM",\
"depart":"HH:MM","note":null}]}]}"""

SYSTEM_PROMPT = _PROMPT_TEMPLATE.replace("@@TRAVEL_TIME_RULE@@", TRAVEL_TIME_RULE)

CANDIDATE_HEADER = "ĐỊA ĐIỂM (place_id | tên | loại | lat,lon | giờ mở cửa)"
WEEKDAY_CODES = ("Mo", "Tu", "We", "Th", "Fr", "Sa", "Su")  # mã ngày của OSM opening_hours


def format_request(request: PlanRequest) -> str:
    weekday = WEEKDAY_CODES[request.start_date.weekday()]
    interests = ", ".join(request.interests) if request.interests else "không có"
    return "\n".join(
        [
            "YÊU CẦU",
            f"city: {request.city}",
            f"start_date: {request.start_date.isoformat()} ({weekday})",
            f"num_days: {request.num_days}",
            f"day_start: {request.day_start.strftime('%H:%M')}",
            f"day_end: {request.day_end.strftime('%H:%M')}",
            f"travel_mode: {request.travel_mode.value}",
            f"pace: {request.pace.value}",
            f"interests: {interests}",
        ]
    )


def format_candidate(place: Place) -> str:
    name = " ".join(place.name.split()).replace("|", "/")  # "|" là ký tự ngăn cột
    hours = place.opening_hours_raw or "unknown"
    coords = f"{place.coords.lat:.4f},{place.coords.lon:.4f}"
    return f"{place.id} | {name} | {place.category.value} | {coords} | {hours}"


REPAIR_PLAN_HEADER = "LỊCH TRÌNH CẦN SỬA"
REPAIR_ISSUES_HEADER = "LỖI CẦN SỬA (từ validator)"
REPAIR_INSTRUCTION = (
    "Sửa hết các lỗi trên. Trả về toàn bộ lịch trình đã sửa, tuân theo mọi quy tắc bắt buộc."
)


def _clock(value: dt.time) -> str:
    """HH:MM như ví dụ trong system prompt; giữ giây nếu có để không làm sai lệch plan gốc."""
    if value.second or value.microsecond:
        return value.isoformat()
    return value.strftime("%H:%M")


def format_itinerary(itinerary: Itinerary) -> str:
    """JSON gọn, đúng thứ tự khóa và dạng giờ của ví dụ trong system prompt.

    Dùng cho đáp án SFT và cho lịch trình hỏng trong prompt repair.
    """
    days = [
        {
            "date": day.date.isoformat(),
            "stops": [
                {
                    "place_id": stop.place_id,
                    "arrive": _clock(stop.arrive),
                    "depart": _clock(stop.depart),
                    "note": stop.note,
                }
                for stop in day.stops
            ],
        }
        for day in itinerary.days
    ]
    return json.dumps({"days": days}, ensure_ascii=False, separators=(",", ":"))


def format_issue(issue: Issue) -> str:
    """Mã lỗi, vị trí (đếm từ 1) và message nguyên văn của validator."""
    position = []
    if issue.day_index is not None:
        position.append(f"ngày {issue.day_index + 1}")
    if issue.stop_index is not None:
        position.append(f"điểm {issue.stop_index + 1}")
    if issue.place_id is not None:
        position.append(issue.place_id)
    where = f" ({', '.join(position)})" if position else ""
    return f"- {issue.code.value}{where}: {issue.message}"


def build_messages(
    request: PlanRequest,
    candidates: Sequence[Place],
    *,
    broken: Itinerary | None = None,
    issues: Sequence[Issue] = (),
) -> list[dict[str, str]]:
    """Prompt sinh plan; có `broken` thì là prompt repair.

    Prompt repair giữ nguyên system prompt và phần yêu cầu, thêm lịch trình hỏng và các issue
    mức ERROR (warning bị bỏ: đó không phải việc model phải sửa). `issues` nhận thẳng
    `ValidationReport.issues`, nên runtime và dataset dựng prompt repair giống hệt nhau.
    """
    rows = "\n".join(format_candidate(place) for place in candidates)
    user = f"{format_request(request)}\n\n{CANDIDATE_HEADER}\n{rows}"
    errors = [issue for issue in issues if issue.severity is Severity.ERROR]
    if broken is None and issues:
        raise ValueError("issues chỉ dùng được kèm broken")
    if broken is not None:
        if not errors:
            raise ValueError("prompt repair cần ít nhất một issue mức ERROR")
        issue_lines = "\n".join(format_issue(issue) for issue in errors)
        user = (
            f"{user}\n\n{REPAIR_PLAN_HEADER}\n{format_itinerary(broken)}"
            f"\n\n{REPAIR_ISSUES_HEADER}\n{issue_lines}\n\n{REPAIR_INSTRUCTION}"
        )
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]
