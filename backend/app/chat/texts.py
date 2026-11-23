"""Vietnamese reply templates. Facts about places, prices and plans come from data, never from an LLM."""

from __future__ import annotations

from collections.abc import Sequence

from app.schemas.booking import BookingResult
from app.schemas.place import Place

CONFIRM_WORDS = frozenset({"dong y", "ok", "okay", "xac nhan", "co", "yes"})
CANCEL_WORDS = frozenset({"huy", "huy bo", "khong", "thoi", "bo qua"})
YES_REPLIES = ("Đồng ý", "Huỷ")
NO_PLAN = "Bạn chưa có lịch trình nào. Hãy cho mình biết ngày đi và số ngày đi Huế."
NEED_APPROVAL = "Bạn cần duyệt một phương án trước khi đặt."
NOT_WAITING = "Phương án này không còn chờ duyệt. Hãy lên lịch mới nếu bạn muốn thay đổi."
CANCELLED = "Đã huỷ xác nhận. Bạn cứ nói tiếp nhé."
OUT_OF_SCOPE = "Xin lỗi, hiện mình chỉ lên kế hoạch cho chuyến đi Huế. Bạn muốn lên lịch đi Huế không?"
SMALLTALK_EXAMPLE = 'Bạn thử nhắn: "Tôi đi Huế 3 ngày 2 đêm từ 05/12, xuất phát Hà Nội, 2 người".'
GREETING = "Chào bạn! Mình là trợ lý lập lịch du lịch Huế. Mình lên lịch trình theo ngày, ước tính chi phí, trả lời giờ mở cửa và giá vé của địa điểm ở Huế, và đặt xe, phòng ở chế độ mô phỏng."
IDENTITY = "Mình là trợ lý lập lịch du lịch Huế, dùng dữ liệu địa điểm từ huetripo.hue.gov.vn. Mình lên lịch trình, ước tính chi phí và trả lời câu hỏi về địa điểm ở Huế. Xe, khách sạn và đặt chỗ đều là MÔ PHỎNG, chưa đặt thật."
THANKS = "Không có gì, rất vui được giúp bạn!"
GOODBYE = "Tạm biệt bạn, chúc chuyến đi Huế vui vẻ!"
PLAN_WAITING_NUDGE = "Lịch trình của bạn đang chờ duyệt; bạn có thể duyệt hoặc nhắn thay đổi bất cứ lúc nào."
PLAN_APPROVED_NUDGE = 'Phương án đã được duyệt; nhắn "Đặt vé và khách sạn" khi bạn sẵn sàng.'
WEATHER = "Mình chưa có dữ liệu thời tiết nên không trả lời được; bạn xem dự báo của nchmf.gov.vn trước khi đi nhé. Mình có thể lên lịch đi Huế cho bạn."
PLACE_MISSING = "Mình chưa tìm thấy địa điểm đó trong dữ liệu Huế. Bạn thử nêu tên khác nhé?"
GUIDE_SOURCE = "Nguồn: Wikipedia tiếng Việt (CC BY-SA 4.0) · {url}"
SUMMARY_SOURCE = "Nguồn: huetripo.hue.gov.vn"
NO_DESCRIPTION = "Nguồn dữ liệu không có phần giới thiệu về nơi này."
CHOOSE_OPTION = "Bạn muốn duyệt phương án nào?"
UNVERIFIED = "Giờ mở cửa lấy từ nguồn dữ liệu, chưa xác minh."
# The summary before planning (S4, S5). Confirm words beyond CONFIRM_WORDS start the plan at the summary.
SUMMARY_HEAD = "Mình tóm tắt lại chuyến đi:"
SUMMARY_TAIL = "Mình lên lịch theo thông tin này nhé? Nếu cần sửa gì, bạn cứ nhắn."
CHANGED_MARK = " ← đã đổi"
TRIP_CONFIRM_WORDS = frozenset({"len lich", "len lich di", "duoc", "chot", "ok luon", "dong y luon"})
CHEAPEST = "chọn rẻ nhất"
SUMMARY_TRANSPORT = {"bus": "xe giường nằm", "train": "tàu hỏa", "flight": "máy bay"}
SUMMARY_STAY = {"homestay": "homestay", "hotel": "khách sạn", "resort": "resort"}
SUMMARY_PACE = {
    "relaxed": "thong thả, 3 điểm tham quan mỗi ngày",
    "moderate": "vừa phải, 4 điểm tham quan mỗi ngày",
    "packed": "đi nhiều, 5 điểm tham quan mỗi ngày",
}
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


def category_name(code: str) -> str:
    """The Vietnamese name of a place category code (religious -> tôn giáo)."""
    return _CATEGORY_NAMES.get(code, code)


_EVENT_NAMES = {"VISIT": "tham quan", "MEAL": "ăn", "MEAL_BREAK": "nghỉ ăn trưa", "REST": "nghỉ trưa"}
_OPTION_NAMES = {"BUDGET": "Tiết kiệm", "BALANCED": "Cân bằng", "COMFORT": "Thoải mái"}


def option_name(label: str) -> str:
    """The Vietnamese name of a budget option code (BUDGET -> Tiết kiệm)."""
    return _OPTION_NAMES.get(label, label)


# One question per slot. Required slots are asked until filled; optional slots once.
QUESTIONS = {
    "origin": "Bạn xuất phát từ đâu?",
    "people": "Bạn đi mấy người?",
    "budget": "Ngân sách khoảng bao nhiêu cho cả chuyến?",
    "interests": "Bạn thích gì: di tích, ẩm thực, chùa chiền, thiên nhiên, cà phê ngắm cảnh…?",
    "transport": "Bạn muốn đi Huế bằng gì: xe giường nằm, tàu hỏa hay máy bay?",
    "stay": "Bạn muốn ở đâu: homestay, khách sạn hay resort?",
    "pace": "Bạn muốn lịch thong thả (3 điểm mỗi ngày), vừa phải (4) hay đi nhiều (5)?",
    "places": 'Có nơi nào nhất định muốn đến hoặc muốn tránh không? (Không có thì bạn nhắn "không".)',
}


def when_question(need_start: bool, need_days: bool) -> str:
    """Asks the start date, the length, or both, whichever is still unknown."""
    if need_start and need_days:
        return "Bạn muốn đi Huế từ ngày nào và đi mấy ngày?"
    if need_start:
        return "Bạn muốn đi Huế từ ngày nào?"
    return "Bạn định đi Huế mấy ngày?"


def too_many_days(max_days: int) -> str:
    return f"Mình chỉ lên lịch tối đa {max_days} ngày. Bạn muốn đi mấy ngày?"


_MODE_NAMES = {"BUS": "xe khách", "TRAIN": "tàu hỏa", "FLIGHT": "máy bay"}
_TIER_NAMES = {"HOMESTAY": "homestay", "THREE_STAR": "khách sạn", "FOUR_STAR": "resort"}


def budget_warning(
    *, low: str, high: str, over_low: str, over_high: str, budget: str, mode: str | None, tier: str | None
) -> str:
    """The early budget check (S2): the cheapest option's range, the excess, and the two choices."""
    names = [name for name in (_MODE_NAMES.get(mode or ""), _TIER_NAMES.get(tier or "")) if name]
    detail = f" ({' + '.join(names)})" if names else ""
    return (
        f"Lưu ý: phương án rẻ nhất{detail} ước tính {money_range(low, high)}, "
        f"vượt ngân sách {money_range(over_low, over_high)}. "
        f"Bạn muốn tăng ngân sách, hay giữ {budget} để mình chọn phương án tiết kiệm nhất?"
    )


def budget_raise_question(*, low: str, high: str, mode: str | None, tier: str | None) -> str:
    """After "tăng ngân sách" with no amount: ask for the new amount and say what the cheapest needs."""
    names = [name for name in (_MODE_NAMES.get(mode or ""), _TIER_NAMES.get(tier or "")) if name]
    detail = f" ({' + '.join(names)})" if names else ""
    return (
        f"Bạn muốn tăng ngân sách lên bao nhiêu? Phương án rẻ nhất{detail} cần khoảng "
        f"{money_range(low, high)}. Bạn cũng có thể đổi phương tiện hoặc chỗ ở cho rẻ hơn."
    )


def soft_budget_note(low: str, high: str) -> str:
    """The one-time note when the cheapest estimate may slightly exceed the budget (S2)."""
    return f"Chi phí ước tính {money_range(low, high)}, có thể vượt ngân sách một chút."


def money_range(low: str, high: str) -> str:
    """"5,15–6,16 triệu" when both ends are in millions; otherwise both ends in full."""
    unit = " triệu"
    if low.endswith(unit) and high.endswith(unit):
        return f"{low[: -len(unit)]}–{high}"
    return f"{low}–{high}"


def invalid(detail: str) -> str:
    return f"Thông tin chưa hợp lệ: {detail}. Bạn kiểm tra lại giúp mình nhé?"


def plan_text(days: int, version: int, labels: Sequence[str]) -> str:
    options = ", ".join(option_name(label) for label in labels) if labels else "chưa có phương án ngân sách"
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
    return f"Phương án hiện tại không có lựa chọn {option_name(label)}. Bạn chọn lại giúp mình nhé?"


def approve_question(label: str, version: int, total: str) -> str:
    return (
        f"Xác nhận duyệt phương án {option_name(label)} (version {version}, tổng khoảng {total}). "
        'Trả lời "đồng ý" để xác nhận; nói điều khác để huỷ.'
    )


def approved_text(label: str, version: int) -> str:
    return (
        f"Đã duyệt phương án {option_name(label)} (version {version}). "
        "Bạn có thể đặt vé xe và khách sạn (mô phỏng)."
    )


def book_question(label: str) -> str:
    return (
        f"Xác nhận đặt vé xe và khách sạn theo phương án {option_name(label)} đã duyệt? "
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


def guide_text(name: str, sentences: Sequence[str], url: str) -> str:
    return f"{name}: {' '.join(sentences)}\n{GUIDE_SOURCE.format(url=url)}"


def summary_text(name: str, summary: str) -> str:
    return f"{name}: {summary.strip()}\n{SUMMARY_SOURCE}"


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
