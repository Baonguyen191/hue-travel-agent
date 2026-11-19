"""Lệnh ask và ask_query với generator giả: QU trả Extraction cố định, plan trả lịch cố định.

Không gọi Ollama. Các điểm dùng chung có toạ độ giống nhau nên thời gian đi bằng 0
(HaversineEstimator).
"""

import datetime as dt
import json
import re
from typing import Any

import pytest

from tests.planning.factories import make_place
from travel_agent.domain.models import Category, PlanRequest
from travel_agent.planning.fill import GAP_REASON, AddedStop
from travel_agent.planning.pipeline import PlanResult
from travel_agent.planning.schedule import DroppedStop
from travel_agent.training.generator import Generation
from travel_agent.understanding.ask import AskOutcome, ask_query, render_ask
from travel_agent.understanding.extract import ExtractionError
from travel_agent.understanding.models import Intent, ParsedQuery
from travel_agent.validation.report import Issue, IssueCode, Severity, ValidationReport

REF = dt.date(2026, 11, 19)
MUSEUM = make_place("t:museum", Category.MUSEUM, name="Bảo tàng Cổ vật")
LUNCH = make_place("t:lunch", Category.RESTAURANT, name="Quán Bún Bò")
DINNER = make_place("t:dinner", Category.RESTAURANT, name="Nhà hàng Sen")
CAFE = make_place("t:cafe", Category.CAFE, name="Cà phê Ba Lần")
PAGODA = make_place("t:pagoda", Category.RELIGIOUS, name="Chùa Thiên Mụ")
PLACES = [MUSEUM, LUNCH, DINNER, CAFE, PAGODA]
VALID_ONE_DAY = json.dumps(
    {
        "days": [
            {
                "date": "2026-12-20",
                "stops": [
                    {"place_id": "t:museum", "arrive": "08:30", "depart": "10:30"},
                    {"place_id": "t:lunch", "arrive": "11:30", "depart": "12:30"},
                    {"place_id": "t:dinner", "arrive": "18:00", "depart": "19:00"},
                ],
            }
        ]
    }
)
INVALID_ONE_DAY = json.dumps(
    {
        "days": [
            {
                "date": "2026-12-20",
                "stops": [
                    {"place_id": "x:404", "arrive": "08:30", "depart": "10:30"},
                    {"place_id": "t:lunch", "arrive": "11:30", "depart": "12:30"},
                    {"place_id": "t:dinner", "arrive": "18:00", "depart": "19:00"},
                ],
            }
        ]
    }
)


def extraction(**fields: Any) -> str:
    base: dict[str, Any] = {
        "intent": "plan_new",
        "date_text": None,
        "duration_text": None,
        "travel_mode": None,
        "pace": None,
        "day_start": None,
        "day_end": None,
        "interest_phrases": [],
        "must_include_mentions": [],
        "exclude_mentions": [],
        "exclude_category_phrases": [],
        "soft_preferences": [],
        "city": None,
    }
    base.update(fields)
    return json.dumps(base, ensure_ascii=False)


class Scripted:
    """Trả lần lượt các nội dung đã cho; có thể ném lỗi hạ tầng hoặc ExtractionError thay vì trả."""

    def __init__(self, *outputs: str | Exception) -> None:
        self.outputs = list(outputs)
        self.calls: list[list[dict[str, str]]] = []

    def generate(
        self, messages: list[dict[str, str]], format_schema: dict[str, Any] | None = None
    ) -> Generation:
        self.calls.append(messages)
        item = self.outputs[min(len(self.calls), len(self.outputs)) - 1]
        if isinstance(item, Exception):
            raise item
        return Generation(content=item, done_reason="stop")


def _outcome(text: str, qu: str, plan: Scripted | None = None, **kwargs: Any) -> AskOutcome:
    return ask_query(
        text,
        REF,
        Scripted(qu),
        plan or Scripted(VALID_ONE_DAY),
        PLACES,
        **kwargs,
    )


# --- ask_query: từng nhánh ---


def test_out_of_scope_is_refused_without_planning() -> None:
    plan = Scripted(VALID_ONE_DAY)
    outcome = ask_query(
        "viết code python giúp mình", REF, Scripted(extraction(intent="out_of_scope")), plan, PLACES
    )
    assert outcome.kind == "out_of_scope"
    assert outcome.plan is None
    assert plan.calls == []
    assert "Mình chỉ lập lịch trình du lịch Huế" in render_ask(outcome, PLACES)


def test_other_city_is_out_of_scope() -> None:
    outcome = _outcome("đi Đà Nẵng 2 ngày", extraction(city="Đà Nẵng", duration_text="2 ngày"))
    assert outcome.kind == "out_of_scope"


@pytest.mark.parametrize(
    ("intent", "marker"),
    [("modify_plan", "modify_plan"), ("place_info", "place_info")],
)
def test_modify_and_place_info_are_reported_as_unsupported(intent: str, marker: str) -> None:
    outcome = _outcome("đổi lịch đi", extraction(intent=intent))
    assert outcome.kind == "unsupported"
    assert outcome.plan is None
    text = render_ask(outcome, PLACES)
    assert "chưa hỗ trợ" in text
    assert marker in text


def test_missing_date_asks_back_and_lists_what_was_understood() -> None:
    plan = Scripted(VALID_ONE_DAY)
    outcome = ask_query(
        "đi Huế 2 ngày",
        REF,
        Scripted(extraction(duration_text="2 ngày")),
        plan,
        PLACES,
    )
    assert outcome.kind == "clarification"
    assert outcome.query.request is None
    assert plan.calls == []
    text = render_ask(outcome, PLACES)
    assert "Bạn muốn đi Huế từ ngày nào?" in text
    assert "đi 2 ngày" in text


def test_clarification_without_understood_fields_has_no_understood_line() -> None:
    outcome = _outcome("đi Huế", extraction())
    assert outcome.kind == "clarification"
    assert "Mình đã hiểu" not in render_ask(outcome, PLACES)


def test_plan_branch_reaches_plan_trip_with_defaults_and_plan_result() -> None:
    outcome = _outcome(
        "đi Huế 20/12, 1 ngày",
        extraction(date_text="20/12", duration_text="1 ngày"),
        max_repairs=0,
    )
    assert outcome.kind == "plan"
    assert outcome.plan is not None and outcome.plan.valid
    assert outcome.query.request is not None
    assert outcome.query.request.start_date == dt.date(2026, 12, 20)
    assert set(outcome.query.defaulted) == {"travel_mode", "pace", "day_start", "day_end"}


def test_must_and_exclude_are_passed_to_candidates() -> None:
    outcome = _outcome(
        "đi Huế 20/12, 1 ngày, ghé Chùa Thiên Mụ, bỏ Cà phê Ba Lần",
        extraction(
            date_text="20/12",
            duration_text="1 ngày",
            must_include_mentions=["Chùa Thiên Mụ"],
            exclude_mentions=["Cà phê Ba Lần"],
        ),
        plan=Scripted(VALID_ONE_DAY),
        max_repairs=0,
    )
    assert outcome.plan is not None
    assert "t:pagoda" in outcome.plan.candidates_ids
    assert "t:cafe" not in outcome.plan.candidates_ids
    # Model không xếp chùa: lỗi thiếu điểm bắt buộc được sửa, rồi chèn bằng code.
    assert outcome.plan.inserted_must == ["t:pagoda"]
    assert outcome.plan.missing_must == []
    assert outcome.plan.itinerary is not None
    planned = [s.place_id for d in outcome.plan.itinerary.days for s in d.stops]
    assert "t:pagoda" in planned


def test_exclude_category_reaches_candidates() -> None:
    outcome = _outcome(
        "đi Huế 20/12, 1 ngày, không uống cà phê",
        extraction(
            date_text="20/12",
            duration_text="1 ngày",
            exclude_category_phrases=["quán cà phê"],
        ),
        max_repairs=0,
    )
    assert outcome.plan is not None
    assert "t:cafe" not in outcome.plan.candidates_ids


def test_unlinked_must_mention_is_not_sent_to_planner() -> None:
    outcome = _outcome(
        "đi Huế 20/12, 1 ngày, ghé Lăng không có trong DB",
        extraction(
            date_text="20/12",
            duration_text="1 ngày",
            must_include_mentions=["Lăng không có trong DB"],
        ),
        max_repairs=0,
    )
    assert outcome.plan is not None
    assert outcome.plan.missing_must == []
    assert "Không tìm thấy trong DB" in render_ask(outcome, PLACES)


def test_extraction_error_propagates() -> None:
    with pytest.raises(ExtractionError):
        ask_query(
            "đi Huế",
            REF,
            Scripted("không phải json", "vẫn không phải json"),
            Scripted(VALID_ONE_DAY),
            PLACES,
        )


# --- render_ask ---


def _plan_outcome() -> AskOutcome:
    """AskOutcome kind plan dựng tay, để kiểm các dòng cảnh báo, bỏ điểm và thiếu bắt buộc."""
    request = PlanRequest(start_date=dt.date(2026, 12, 20), num_days=1)
    query = ParsedQuery(
        intent=Intent.PLAN_NEW,
        request=request,
        defaulted=["travel_mode", "pace"],
        soft_preferences=["yên tĩnh"],
    )
    issues = [
        Issue(
            code=IssueCode.OPENING_HOURS_UNKNOWN,
            severity=Severity.WARNING,
            message="Chưa rõ giờ mở cửa của Bảo tàng Cổ vật.",
        ),
        Issue(
            code=IssueCode.UNKNOWN_PLACE,
            severity=Severity.ERROR,
            message="Điểm x:404 không có trong danh sách.",
        ),
    ]
    result = PlanResult(
        itinerary=None,
        report=ValidationReport(issues=issues),
        valid=False,
        attempts=[],
        dropped=[DroppedStop(day_index=0, place_id="t:pagoda", reason="ngoài giờ mở cửa")],
        candidates_ids=[],
        missing_must=["t:pagoda", "x:404"],
    )
    return AskOutcome("plan", query, result)


def test_render_plan_shows_warnings_drops_missing_and_assumptions() -> None:
    text = render_ask(_plan_outcome(), PLACES)
    assert "Mình giả định: đi xe máy, nhịp vừa phải." in text
    assert "Chưa dùng để chọn điểm (yêu cầu mềm): yên tĩnh." in text
    assert "Cảnh báo:" in text and "Chưa rõ giờ mở cửa" in text
    assert "Lỗi còn lại" in text and "x:404 không có trong danh sách" in text
    assert "Chùa Thiên Mụ. Lý do: ngoài giờ mở cửa" in text
    assert "Yêu cầu bắt buộc chưa có trong lịch: Chùa Thiên Mụ, x:404" in text


def test_render_itinerary_has_names_times_and_categories() -> None:
    outcome = _outcome(
        "đi Huế 20/12, 1 ngày",
        extraction(date_text="20/12", duration_text="1 ngày"),
        max_repairs=0,
    )
    text = render_ask(outcome, PLACES)
    assert "Ngày 1 — Chủ nhật 20/12/2026" in text
    assert re.search(r"\d{2}:\d{2}–\d{2}:\d{2} Bảo tàng Cổ vật \(bảo tàng\)", text)
    assert re.search(r"\d{2}:\d{2}–\d{2}:\d{2} Quán Bún Bò \(nhà hàng\)", text)
    assert "Đã gọi model 1 lần, trong đó sửa 0 lần." in text


def test_render_plan_lists_added_places_with_reasons() -> None:
    outcome = _plan_outcome()
    assert outcome.plan is not None
    added = [AddedStop(day_index=0, place_id="t:cafe", reason=GAP_REASON)]
    outcome = AskOutcome("plan", outcome.query, outcome.plan.model_copy(update={"added": added}))
    text = render_ask(outcome, PLACES)
    assert "Điểm thêm vào:" in text
    assert f"Cà phê Ba Lần. Lý do: {GAP_REASON}" in text
