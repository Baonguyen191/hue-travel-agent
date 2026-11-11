"""Prompt sinh lịch trình. Nguồn duy nhất cho baseline, SFT, RL và runtime.

Sửa file này làm lệch dữ liệu đã train. Snapshot test sẽ vỡ để nhắc việc đó.
"""

from __future__ import annotations

from collections.abc import Sequence

from travel_agent.domain.models import Place, PlanRequest

SYSTEM_PROMPT = """Bạn lập lịch trình du lịch cho thành phố Huế.

Quy tắc bắt buộc:
1. Chỉ dùng place_id có trong danh sách ĐỊA ĐIỂM. Không tự tạo place_id.
2. Mỗi place_id chỉ xuất hiện một lần trong toàn bộ lịch trình.
3. Số ngày bằng đúng num_days. Ngày đầu là start_date, các ngày sau liên tiếp.
4. Mọi điểm dừng nằm trong khung day_start đến day_end. depart phải sau arrive.
5. Điểm dừng trong ngày xếp theo thứ tự thời gian, không chồng giờ, và chừa đủ thời gian \
di chuyển giữa hai điểm theo travel_mode (ước lượng từ tọa độ).
6. Nếu địa điểm có giờ mở cửa thì cả khoảng arrive đến depart phải nằm trong giờ mở cửa. \
"unknown" nghĩa là không rõ giờ.
7. Số điểm dừng mỗi ngày theo pace: relaxed 3 đến 4, moderate 4 đến 6, packed 6 đến 8.
8. Nếu khung ngày bao trọn 11:00-13:30 thì có một điểm restaurant trong khung đó. \
Tương tự với 17:30-20:00.
9. Ưu tiên địa điểm khớp interests.

Chỉ trả về JSON đúng dạng sau, không thêm chữ nào khác:
{"days":[{"date":"YYYY-MM-DD","stops":[{"place_id":"...","arrive":"HH:MM",\
"depart":"HH:MM","note":null}]}]}"""

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
    name = " ".join(place.name.split())
    hours = place.opening_hours_raw or "unknown"
    coords = f"{place.coords.lat:.4f},{place.coords.lon:.4f}"
    return f"{place.id} | {name} | {place.category.value} | {coords} | {hours}"


def build_messages(request: PlanRequest, candidates: Sequence[Place]) -> list[dict[str, str]]:
    rows = "\n".join(format_candidate(place) for place in candidates)
    user = f"{format_request(request)}\n\n{CANDIDATE_HEADER}\n{rows}"
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]
