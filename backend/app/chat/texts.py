"""Vietnamese reply templates. Facts about places, prices and plans come from data, never from an LLM."""

from __future__ import annotations

from collections.abc import Sequence

from app.schemas.booking import BookingResult
from app.schemas.place import Place

CONFIRM_WORDS = frozenset({"dong y", "ok", "okay", "xac nhan", "co", "yes"})
DEFAULT_WORDS = frozenset({"dung mac dinh", "mac dinh"})
CANCEL_WORDS = frozenset({"huy", "huy bo", "khong", "thoi", "bo qua"})
YES_REPLIES = ("Đồng ý", "Huỷ")
DEFAULTS_QUESTION = "Bạn xuất phát từ đâu và đi mấy người? (mặc định: Huế, 1 người)"
DEFAULT_REPLIES = ("Từ Hà Nội, 2 người", "Dùng mặc định")
NO_PLAN = "Bạn chưa có lịch trình nào. Hãy cho mình biết ngày đi và số ngày đi Huế."
NEED_APPROVAL = "Bạn cần duyệt một phương án trước khi đặt."
NOT_WAITING = "Phương án này không còn chờ duyệt. Hãy lên lịch mới nếu bạn muốn thay đổi."
CANCELLED = "Đã huỷ xác nhận. Bạn cứ nói tiếp nhé."
OUT_OF_SCOPE = "Xin lỗi, hiện mình chỉ lên kế hoạch cho chuyến đi Huế. Bạn muốn lên lịch đi Huế không?"
PLACE_MISSING = "Mình chưa tìm thấy địa điểm đó trong dữ liệu Huế. Bạn thử nêu tên khác nhé?"
CHOOSE_OPTION = "Bạn muốn duyệt phương án nào?"
UNVERIFIED = "Giờ mở cửa lấy từ nguồn dữ liệu, chưa xác minh."
_CATEGORY_NAMES = {
    "restaurant": "quán ăn",
    "cafe": "quán cà phê",
    "historic": "di tích",
    "attraction": "điểm tham quan",
    "market": "chợ",
    "religious": "tôn giáo",
    "park": "công viên",
    "museum": "bảo tàng",
}
_EVENT_NAMES = {"VISIT": "tham quan", "MEAL": "ăn", "MEAL_BREAK": "nghỉ ăn trưa"}


def invalid(detail: str) -> str:
    return f"Thông tin chưa hợp lệ: {detail}. Bạn kiểm tra lại giúp mình nhé?"


def plan_text(days: int, version: int, labels: Sequence[str]) -> str:
    options = ", ".join(labels) if labels else "chưa có phương án ngân sách"
    return (
        f"Mình đã lên lịch {days} ngày ở Huế (phương án version {version}). "
        f"Các phương án ngân sách: {options}. {UNVERIFIED} Bạn muốn duyệt phương án nào?"
    )


def plan_failed(warnings: Sequence[str]) -> str:
    reasons = "; ".join(warnings) if warnings else "không đủ dữ liệu"
    return f"Mình chưa lên được lịch phù hợp ({reasons}). Bạn thử đổi ngày hoặc số người nhé?"


def changes_applied(lines: Sequence[str], notes: Sequence[str]) -> str:
    done = "; ".join(lines) if lines else "không có thay đổi"
    tail = " ".join(notes)
    return f"Mình đã cập nhật: {done}. {tail}".strip()


def changes_not_applied(notes: Sequence[str]) -> str:
    reasons = " ".join(notes) if notes else "Mình chưa hiểu thay đổi bạn muốn."
    return f"Mình chưa áp dụng được thay đổi nào. {reasons}".strip()


def no_option(label: str) -> str:
    return f"Phương án hiện tại không có lựa chọn {label}. Bạn chọn lại giúp mình nhé?"


def approve_question(label: str, version: int, total: str) -> str:
    return (
        f"Xác nhận duyệt phương án {label} (version {version}, tổng khoảng {total}). "
        'Trả lời "đồng ý" để xác nhận; nói điều khác để huỷ.'
    )


def approved_text(label: str, version: int) -> str:
    return f"Đã duyệt phương án {label} (version {version}). Bạn có thể đặt vé xe và khách sạn (mô phỏng)."


def book_question(label: str) -> str:
    return (
        f"Xác nhận đặt vé xe và khách sạn theo phương án {label} đã duyệt? "
        'Đây là đặt chỗ MÔ PHỎNG. Trả lời "đồng ý" để xác nhận; nói điều khác để huỷ.'
    )


def booking_text(result: BookingResult) -> str:
    return " ".join(result.explanation) or f"Trạng thái đặt chỗ: {result.status}."


def stale(detail: str) -> str:
    return f"Phương án đã thay đổi hoặc đã được duyệt rồi: {detail}"


def total_range(low: int, high: int | None) -> str:
    if high is None or high == low:
        return f"{low:,} VND"
    return f"{low:,} – {high:,} VND"


def place_text(place: Place, phone: str | None) -> str:
    lines = [
        f"{place.name} ({_CATEGORY_NAMES.get(place.category, place.category)})",
        f"Địa chỉ: {place.address or 'chưa có dữ liệu'}",
        f"Giờ mở cửa (nguồn, chưa xác minh): {place.opening_hours_raw or 'chưa có dữ liệu'}",
        f"Giá tham khảo: {_price_text(place)}",
        f"Điện thoại: {phone or 'chưa có dữ liệu'}",
        f"Nguồn: {place.source_url or 'chưa có dữ liệu'}",
    ]
    return "\n".join(lines)


def nearby_text(places: Sequence[tuple[Place, float]]) -> str:
    if not places:
        return "Không có địa điểm nào trong vòng 1 km trong dữ liệu Huế."
    lines = [f"- {item.name} (cách {distance:.2f} km)" for item, distance in places]
    return "Gần đó (trong 1 km):\n" + "\n".join(lines)


def event_name(kind: str) -> str:
    return _EVENT_NAMES.get(kind, kind)


def _price_text(place: Place) -> str:
    if place.price_min_vnd is not None and place.price_max_vnd is not None:
        return f"{place.price_min_vnd:,} – {place.price_max_vnd:,} VND (tham khảo, mỗi người)"
    if place.price_status == "FREE_CLAIM":
        return "miễn phí theo nguồn"
    return "chưa có dữ liệu"
