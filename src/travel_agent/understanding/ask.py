"""Từ câu tự do tới kết quả cho người dùng: hỏi lại, từ chối, báo chưa hỗ trợ, hoặc lập lịch.

Hàm `ask_query` không in gì và không đọc CLI; `render_ask` trả về chuỗi tiếng Việt để in. Lệnh
`ask` nằm trong understanding/cli.py và chỉ nối hai hàm này với Ollama và DB.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from travel_agent.domain.models import Category, Place
from travel_agent.planning.pipeline import PlanResult, plan_trip
from travel_agent.routing.travel_time import HaversineEstimator, TravelTimeProvider
from travel_agent.training.generator import PlanGenerator
from travel_agent.understanding.extract import parse_query
from travel_agent.understanding.models import Intent, ParsedQuery
from travel_agent.validation.report import Severity

OutcomeKind = Literal["out_of_scope", "unsupported", "clarification", "plan"]

OUT_OF_SCOPE_MESSAGE = (
    "Mình chỉ lập lịch trình du lịch Huế thôi, nên chưa giúp được việc này. "
    "Bạn thử nói ngày đi, số ngày và sở thích để mình lên lịch nhé."
)
UNSUPPORTED_MESSAGES: dict[Intent, str] = {
    Intent.MODIFY_PLAN: (
        "Mình chưa hỗ trợ sửa một lịch trình đã lập (modify_plan). "
        "Bạn hãy nói lại đầy đủ yêu cầu để mình lập lịch mới."
    ),
    Intent.PLACE_INFO: (
        "Mình chưa hỗ trợ hỏi thông tin chi tiết về một địa điểm (place_info). "
        "Hiện mình chỉ lập lịch trình."
    ),
}

WEEKDAYS_VI = ("thứ Hai", "thứ Ba", "thứ Tư", "thứ Năm", "thứ Sáu", "thứ Bảy", "Chủ nhật")
CATEGORY_VI: dict[Category, str] = {
    Category.ATTRACTION: "điểm tham quan",
    Category.MUSEUM: "bảo tàng",
    Category.HISTORIC: "di tích",
    Category.VIEWPOINT: "điểm ngắm cảnh",
    Category.RESTAURANT: "nhà hàng",
    Category.CAFE: "quán cà phê",
    Category.MARKET: "chợ",
    Category.PARK: "công viên",
    Category.RELIGIOUS: "cơ sở tôn giáo",
}
TRAVEL_VI: dict[str, str] = {"walk": "đi bộ", "motorbike": "đi xe máy", "car": "đi ô tô"}
PACE_VI: dict[str, str] = {
    "relaxed": "nhịp thong thả",
    "moderate": "nhịp vừa phải",
    "packed": "nhịp dày",
}


@dataclass(frozen=True)
class AskOutcome:
    kind: OutcomeKind
    query: ParsedQuery
    plan: PlanResult | None = None  # chỉ có khi kind là "plan"


def ask_query(
    text: str,
    ref: dt.date,
    qu_generator: PlanGenerator,
    plan_generator: PlanGenerator,
    places: Sequence[Place],
    *,
    retime: bool = True,
    max_repairs: int = 2,
    travel: TravelTimeProvider | None = None,
) -> AskOutcome:
    """Hiểu câu bằng `qu_generator`; nếu là lập lịch đủ thông tin thì gọi `plan_trip`.

    Ràng buộc đưa vào lập lịch: điểm `must_include` và `exclude` đã liên kết được (có place_id),
    cùng `exclude_categories`. Mention chưa liên kết không đưa vào, và được ghi trong phần hiển thị.
    Lỗi hạ tầng (GenerationError) và JSON sai (ExtractionError) không bị bắt ở đây.
    """
    query = parse_query(text, ref, qu_generator, places)
    if query.intent is Intent.OUT_OF_SCOPE:
        return AskOutcome("out_of_scope", query)
    if query.intent is not Intent.PLAN_NEW:
        return AskOutcome("unsupported", query)
    if query.request is None:
        # ParsedQuery đảm bảo plan_new có request hoặc clarification; nhánh này là có clarification.
        return AskOutcome("clarification", query)
    plan = plan_trip(
        query.request,
        places,
        plan_generator,
        travel if travel is not None else HaversineEstimator(),
        retime=retime,
        max_repairs=max_repairs,
        must_include=[m.place_id for m in query.must_include if m.place_id is not None],
        exclude_ids=[m.place_id for m in query.exclude if m.place_id is not None],
        exclude_categories=query.exclude_categories,
    )
    return AskOutcome("plan", query, plan)


def render_ask(outcome: AskOutcome, places: Sequence[Place]) -> str:
    """Chữ tiếng Việt cho người dùng; `places` dùng để đổi place_id thành tên."""
    if outcome.kind == "out_of_scope":
        return OUT_OF_SCOPE_MESSAGE
    if outcome.kind == "unsupported":
        return UNSUPPORTED_MESSAGES[outcome.query.intent]
    if outcome.kind == "clarification":
        return _render_clarification(outcome.query)
    if outcome.plan is None:  # không xảy ra: kind "plan" luôn có plan
        raise ValueError("kết quả lập lịch thiếu PlanResult")
    return _render_plan(outcome.query, outcome.plan, {place.id: place for place in places})


def _date_vi(day: dt.date) -> str:
    return f"{WEEKDAYS_VI[day.weekday()]} {day:%d/%m/%Y}"


def _render_clarification(query: ParsedQuery) -> str:
    lines = [query.clarification or "Bạn nói rõ thêm giúp mình nhé."]
    understood = [
        text
        for key, value in query.partial.items()
        if (text := _understood_item(key, value)) is not None
    ]
    if understood:
        lines.append("Mình đã hiểu: " + "; ".join(understood) + ".")
    return "\n".join(lines)


def _understood_item(key: str, value: object) -> str | None:
    """Một mục trong "Mình đã hiểu"; None với trường rỗng hoặc không hiển thị."""
    if value in (None, "", []):
        return None
    if key == "start_date":
        try:
            return f"ngày đi {_date_vi(dt.date.fromisoformat(str(value)))}"
        except ValueError:
            return f"ngày đi {value}"
    if key == "num_days":
        return f"đi {value} ngày"
    if key == "travel_mode":
        return TRAVEL_VI.get(str(value), str(value))
    if key == "pace":
        return PACE_VI.get(str(value), str(value))
    if key == "day_start":
        return f"bắt đầu lúc {value}"
    if key == "day_end":
        return f"kết thúc lúc {value}"
    if key == "interests" and isinstance(value, list):
        return "sở thích " + ", ".join(str(item) for item in value)
    return None


def _assumptions(query: ParsedQuery) -> list[str]:
    """Các mục code tự điền (query.defaulted), dịch sang câu tiếng Việt, không lặp khung giờ."""
    request = query.request
    if request is None:
        return []
    parts: list[str] = []
    for name in query.defaulted:
        if name == "travel_mode":
            parts.append(TRAVEL_VI.get(request.travel_mode.value, request.travel_mode.value))
        elif name == "pace":
            parts.append(PACE_VI.get(request.pace.value, request.pace.value))
        elif name in ("day_start", "day_end"):
            window = f"khung giờ {request.day_start:%H:%M}–{request.day_end:%H:%M}"
            if window not in parts:
                parts.append(window)
        else:
            parts.append(name)
    return parts


def _render_plan(query: ParsedQuery, result: PlanResult, by_id: dict[str, Place]) -> str:
    request = query.request
    if request is None:
        raise ValueError("lập lịch cần request")
    lines = [f"Lịch trình Huế {request.num_days} ngày, bắt đầu {_date_vi(request.start_date)}."]

    assumed = _assumptions(query)
    if assumed:
        lines.append("Mình giả định: " + ", ".join(assumed) + ".")
    if request.interests:
        lines.append("Sở thích đã dùng để chọn điểm: " + ", ".join(request.interests) + ".")
    if query.soft_preferences:
        lines.append(
            "Chưa dùng để chọn điểm (yêu cầu mềm): " + "; ".join(query.soft_preferences) + "."
        )
    unlinked_must = [m.text for m in query.must_include if m.place_id is None]
    if unlinked_must:
        lines.append("Không tìm thấy trong DB, nên không đưa vào lịch: " + ", ".join(unlinked_must))
    unlinked_exclude = [m.text for m in query.exclude if m.place_id is None]
    if unlinked_exclude:
        lines.append("Không tìm thấy trong DB để loại trừ: " + ", ".join(unlinked_exclude))

    lines.append("")
    if result.itinerary is None:
        lines.append(
            f"Không đọc được lịch từ model sau {len(result.attempts)} lần gọi. Thử lại sau."
        )
    else:
        for index, day in enumerate(result.itinerary.days, start=1):
            lines.append(f"Ngày {index} — {_date_vi(day.date)}")
            for stop in day.stops:
                place = by_id.get(stop.place_id)
                if place is None:
                    name, kind = f"{stop.place_id} (không có trong DB)", "không rõ"
                else:
                    name, kind = place.name, CATEGORY_VI.get(place.category, place.category.value)
                line = f"  {stop.arrive:%H:%M}–{stop.depart:%H:%M} {name} ({kind})"
                if stop.note:
                    line += f" — {stop.note}"
                lines.append(line)
            lines.append("")

    report = result.report
    warnings = (
        [i.message for i in report.issues if i.severity is Severity.WARNING] if report else []
    )
    errors = [i.message for i in report.errors()] if report else []
    if warnings:
        lines.append("Cảnh báo:")
        lines.extend(f"  - {message}" for message in warnings)
    if errors:
        lines.append("Lỗi còn lại, lịch này chưa dùng được:")
        lines.extend(f"  - {message}" for message in errors)
    if result.dropped:
        lines.append("Điểm bị bỏ khi xếp giờ:")
        for drop in result.dropped:
            place = by_id.get(drop.place_id)
            name = place.name if place is not None else drop.place_id
            lines.append(f"  - Ngày {drop.day_index + 1}: {name}. Lý do: {drop.reason}")
    if result.missing_must:
        names = [by_id[pid].name if pid in by_id else pid for pid in result.missing_must]
        lines.append("Yêu cầu bắt buộc chưa có trong lịch: " + ", ".join(names))

    repairs = sum(1 for attempt in result.attempts if attempt.kind == "repair")
    lines.append(f"Đã gọi model {len(result.attempts)} lần, trong đó sửa {repairs} lần.")
    return "\n".join(lines)
