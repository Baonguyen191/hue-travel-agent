"""Test trích thông tin bằng LLM với generator giả (không gọi mạng)."""

import datetime as dt
import json
from pathlib import Path
from typing import Any

import pytest

from travel_agent.domain.models import Category, Coordinates, Pace, Place, TravelMode
from travel_agent.training.generator import Generation, GenerationError
from travel_agent.understanding.extract import (
    _FEW_SHOT,
    EXTRACTION_SCHEMA,
    Extraction,
    ExtractionError,
    build_extraction_messages,
    parse_query,
)
from travel_agent.understanding.models import Intent

# 2026-11-18 là thứ Tư.
WED = dt.date(2026, 11, 18)
EVAL_FILE = Path(__file__).parents[2] / "data" / "eval" / "query_eval_v1.jsonl"


class FakeGenerator:
    """Trả lần lượt các chuỗi đã cho; ghi lại số lần gọi và format_schema đã truyền."""

    def __init__(self, *responses: str | Exception) -> None:
        self._responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def generate(
        self, messages: list[dict[str, str]], format_schema: dict[str, Any] | None = None
    ) -> Generation:
        self.calls.append({"messages": messages, "format_schema": format_schema})
        item = self._responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return Generation(content=item)


def _answer(**overrides: Any) -> str:
    """JSON mặc định của LLM (không có gì được trích), ghi đè theo tham số."""
    data: dict[str, Any] = {
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
    data.update(overrides)
    return json.dumps(data, ensure_ascii=False)


def _parse(text: str, answer: str, places: list[Place] | None = None) -> Any:
    return parse_query(text, WED, FakeGenerator(answer), places or [])


def _place(place_id: str, name: str, category: Category) -> Place:
    return Place(
        id=place_id,
        name=name,
        category=category,
        coords=Coordinates(lat=16.47, lon=107.58),
        source="test",
        source_place_id=place_id,
        license="test",
        collected_at=dt.datetime(2026, 11, 1, tzinfo=dt.UTC),
    )


# ---------------------------------------------------------------------------
# Schema và prompt
# ---------------------------------------------------------------------------


def test_schema_required_keys_match_extraction_fields() -> None:
    assert set(EXTRACTION_SCHEMA["required"]) == set(Extraction.model_fields)
    assert set(EXTRACTION_SCHEMA["properties"]) == set(Extraction.model_fields)
    assert EXTRACTION_SCHEMA["additionalProperties"] is False


def test_schema_enums_and_time_pattern() -> None:
    props = EXTRACTION_SCHEMA["properties"]
    assert set(props["intent"]["enum"]) == {item.value for item in Intent}
    assert set(props["travel_mode"]["enum"]) == {"walk", "motorbike", "car", None}
    assert set(props["pace"]["enum"]) == {"relaxed", "moderate", "packed", None}
    assert props["day_start"]["pattern"] == props["day_end"]["pattern"]


def test_messages_have_system_few_shot_and_final_user_turn() -> None:
    messages = build_extraction_messages("đi Huế 2 ngày", WED)
    assert messages[0]["role"] == "system"
    assert len(_FEW_SHOT) == 6
    assert len(messages) == 1 + 2 * len(_FEW_SHOT) + 1
    assert messages[-1]["role"] == "user"
    assert messages[-1]["content"].endswith("Câu: đi Huế 2 ngày")
    assert "2026-11-18" in messages[-1]["content"]


def test_few_shot_sentences_are_not_copied_from_eval_set() -> None:
    if not EVAL_FILE.exists():
        pytest.skip("thiếu data/eval/query_eval_v1.jsonl")
    eval_texts = {
        json.loads(line)["text"] for line in EVAL_FILE.read_text(encoding="utf-8").splitlines()
    }
    for sentence, _ in _FEW_SHOT:
        assert sentence not in eval_texts


def test_system_prompt_states_the_pace_and_soft_preference_rules() -> None:
    system = build_extraction_messages("x", WED)[0]["content"]
    assert "thong thả" in system
    assert "KHÔNG đổi pace" in system
    assert "Không tự tính ngày" in system


# ---------------------------------------------------------------------------
# Gọi LLM: thử lại và lỗi
# ---------------------------------------------------------------------------


def test_request_passes_extraction_schema_to_generator() -> None:
    generator = FakeGenerator(_answer())
    parse_query("đi Huế 2 ngày", WED, generator, [])
    assert generator.calls[0]["format_schema"] is EXTRACTION_SCHEMA


def test_invalid_json_is_retried_once_then_succeeds() -> None:
    generator = FakeGenerator("không phải json", _answer(duration_text="2 ngày"))
    query = parse_query("đi Huế 2 ngày", WED, generator, [])
    assert len(generator.calls) == 2
    assert query.partial["num_days"] == 2


def test_two_invalid_answers_raise_extraction_error() -> None:
    generator = FakeGenerator("{", '{"intent": "bay"}')
    with pytest.raises(ExtractionError):
        parse_query("đi Huế", WED, generator, [])
    assert len(generator.calls) == 2


def test_model_cannot_supply_a_computed_start_date() -> None:
    # LLM không có trường start_date; trường lạ bị coi là sai schema.
    answer = json.dumps({**json.loads(_answer()), "start_date": "2026-01-01"})
    with pytest.raises(ExtractionError):
        parse_query("đi Huế", WED, FakeGenerator(answer, answer), [])


def test_bad_clock_format_is_rejected_then_raises() -> None:
    answer = _answer(day_start="8h")
    with pytest.raises(ExtractionError):
        parse_query("đi Huế", WED, FakeGenerator(answer, answer), [])


def test_infrastructure_error_propagates_without_retry() -> None:
    generator = FakeGenerator(GenerationError("Ollama chết"))
    with pytest.raises(GenerationError):
        parse_query("đi Huế", WED, generator, [])
    assert len(generator.calls) == 1


# ---------------------------------------------------------------------------
# Hậu xử lý bằng code
# ---------------------------------------------------------------------------


def test_full_plan_request_from_fake_answer() -> None:
    query = _parse(
        "Cuối tuần này đi Huế hai ngày bằng ô tô, thích đặc sản và đi chùa.",
        _answer(
            date_text="Cuối tuần này",
            duration_text="hai ngày",
            travel_mode="car",
            interest_phrases=["đặc sản", "đi chùa"],
        ),
    )
    assert query.intent is Intent.PLAN_NEW
    assert query.clarification is None
    assert query.request is not None
    assert query.request.start_date == dt.date(2026, 11, 21)
    assert query.request.num_days == 2
    assert query.request.travel_mode is TravelMode.CAR
    assert query.request.interests == ["food", "spiritual"]
    assert query.request.pace is Pace.MODERATE
    assert query.defaulted == ["pace", "day_start", "day_end"]
    assert query.date_text == "Cuối tuần này"


def test_llm_date_text_is_resolved_by_code_not_copied() -> None:
    query = _parse(
        "đi Huế thứ 5 tuần này 2 ngày",
        _answer(date_text="thứ 5 tuần này", duration_text="2 ngày"),
    )
    assert query.request is not None
    assert query.request.start_date == dt.date(2026, 11, 19)


def test_date_falls_back_to_raw_text_when_llm_leaves_it_null() -> None:
    query = _parse("đi Huế từ 20/12, 2 ngày", _answer(duration_text="2 ngày"))
    assert query.request is not None
    assert query.request.start_date == dt.date(2026, 12, 20)
    assert query.date_text == "20/12"


def test_date_fallback_respects_next_year_suffix() -> None:
    query = _parse("đi Huế 20/12 năm sau, 2 ngày", _answer(duration_text="2 ngày"))
    assert query.request is not None
    assert query.request.start_date == dt.date(2027, 12, 20)


def test_unresolvable_date_asks_clarification_and_keeps_fields() -> None:
    query = _parse(
        "đi Huế ngày 40/12, 2 ngày, thích chùa",
        _answer(date_text="ngày 40/12", duration_text="2 ngày", interest_phrases=["chùa"]),
    )
    assert query.request is None
    assert query.clarification is not None
    assert "ngày 40/12" in query.clarification
    assert query.partial["num_days"] == 2
    assert query.partial["interests"] == ["spiritual"]
    assert "start_date" not in query.partial


def test_missing_days_asks_clarification_but_keeps_date_in_partial() -> None:
    query = _parse("đi Huế từ 20/12", _answer(date_text="20/12", interest_phrases=["lăng"]))
    assert query.request is None
    assert query.clarification == "Bạn định đi Huế mấy ngày?"
    assert query.partial["start_date"] == "2026-12-20"
    assert query.partial["interests"] == ["history"]


def test_missing_date_and_days_asks_both() -> None:
    query = _parse("lên lịch đi Huế", _answer())
    assert query.request is None
    assert query.clarification == "Bạn muốn đi Huế từ ngày nào và đi mấy ngày?"


def test_missing_date_only_asks_for_date() -> None:
    query = _parse("đi Huế 3 ngày", _answer(duration_text="3 ngày"))
    assert query.request is None
    assert query.clarification == "Bạn muốn đi Huế từ ngày nào?"
    assert query.partial["num_days"] == 3


def test_more_than_seven_days_asks_clarification() -> None:
    query = _parse("đi Huế 9 ngày từ 1/12", _answer(date_text="1/12", duration_text="9 ngày"))
    assert query.request is None
    assert query.clarification is not None
    assert "7 ngày" in query.clarification


def test_half_day_sets_day_end_four_hours_after_start() -> None:
    query = _parse(
        "đi Huế nửa ngày từ 20/12",
        _answer(date_text="20/12", duration_text="nửa ngày"),
    )
    assert query.request is not None
    assert query.request.num_days == 1
    assert query.request.day_start.hour == 8
    assert query.request.day_end.hour == 12


def test_day_window_must_end_after_it_starts() -> None:
    query = _parse(
        "đi Huế 1 ngày 20/12 từ 18:00 đến 09:00",
        _answer(date_text="20/12", duration_text="1 ngày", day_start="18:00", day_end="09:00"),
    )
    assert query.request is None
    assert query.clarification is not None
    assert "sau giờ bắt đầu" in query.clarification


def test_explicit_hours_are_used() -> None:
    query = _parse(
        "đi Huế 1 ngày 20/12 từ 7:30",
        _answer(date_text="20/12", duration_text="1 ngày", day_start="07:30", day_end="18:00"),
    )
    assert query.request is not None
    assert query.request.day_start.hour == 7
    assert query.request.day_start.minute == 30
    assert query.request.day_end.hour == 18
    assert query.defaulted == ["travel_mode", "pace"]


def test_duration_falls_back_to_raw_text() -> None:
    query = _parse("đi Huế 20/12 3 hôm", _answer(date_text="20/12"))
    assert query.request is not None
    assert query.request.num_days == 3


def test_family_with_elderly_parents_changes_only_soft_preferences() -> None:
    query = _parse(
        "đi Huế 2 ngày 20/12, bố mẹ già đi cùng",
        _answer(
            date_text="20/12",
            duration_text="2 ngày",
            soft_preferences=["bố mẹ già đi cùng"],
        ),
    )
    assert query.request is not None
    assert query.request.pace is Pace.MODERATE
    assert "pace" in query.defaulted
    assert query.soft_preferences == ["bố mẹ già đi cùng"]


def test_explicit_pace_is_taken_from_llm() -> None:
    query = _parse(
        "đi Huế 2 ngày 20/12, thong thả",
        _answer(date_text="20/12", duration_text="2 ngày", pace="relaxed"),
    )
    assert query.request is not None
    assert query.request.pace is Pace.RELAXED
    assert "pace" not in query.defaulted


def test_unmatched_interest_phrase_moves_to_soft_preferences() -> None:
    query = _parse(
        "đi Huế 2 ngày 20/12, thích yên tĩnh và chụp ảnh",
        _answer(
            date_text="20/12",
            duration_text="2 ngày",
            interest_phrases=["yên tĩnh", "chụp ảnh"],
        ),
    )
    assert query.request is not None
    assert query.request.interests == ["photography"]
    assert query.soft_preferences == ["yên tĩnh"]


def test_specific_like_can_be_in_both_interests_and_soft_preferences() -> None:
    query = _parse(
        "đi Huế 2 ngày 20/12, thích chùa",
        _answer(
            date_text="20/12",
            duration_text="2 ngày",
            interest_phrases=["chùa"],
            soft_preferences=["chùa"],
        ),
    )
    assert query.request is not None
    assert query.request.interests == ["spiritual"]
    assert query.soft_preferences == ["chùa"]


def test_exclude_category_phrases_map_to_categories() -> None:
    query = _parse(
        "đi Huế 2 ngày 20/12, bỏ chợ và bảo tàng",
        _answer(
            date_text="20/12",
            duration_text="2 ngày",
            exclude_category_phrases=["chợ", "bảo tàng"],
        ),
    )
    assert query.exclude_categories == [Category.MARKET, Category.MUSEUM]
    assert query.request is not None
    assert query.request.interests == []


def test_unknown_exclude_category_phrase_goes_to_soft_preferences() -> None:
    query = _parse(
        "đi Huế 2 ngày 20/12, không đi casino",
        _answer(date_text="20/12", duration_text="2 ngày", exclude_category_phrases=["casino"]),
    )
    assert query.exclude_categories == []
    assert query.soft_preferences == ["casino"]


def test_must_and_exclude_mentions_are_linked_to_places() -> None:
    places = [
        _place("huetripo:197559", "Chùa Thiên Mụ (Chùa Linh Mụ)", Category.RELIGIOUS),
        _place("huetripo:531787", "Đại Nội Huế", Category.HISTORIC),
    ]
    query = _parse(
        "đi Huế 2 ngày 20/12, ghé chùa Thiên Mụ, bỏ Đại Nội",
        _answer(
            date_text="20/12",
            duration_text="2 ngày",
            must_include_mentions=["chùa Thiên Mụ", "Lăng Không Có"],
            exclude_mentions=["Đại Nội"],
        ),
        places,
    )
    assert [item.place_id for item in query.must_include] == ["huetripo:197559", None]
    assert query.must_include[1].text == "Lăng Không Có"
    assert [item.place_id for item in query.exclude] == ["huetripo:531787"]


def test_out_of_scope_intent_has_no_request_or_clarification() -> None:
    query = _parse("lên kế hoạch đi Hội An 2 ngày", _answer(intent="out_of_scope"))
    assert query.intent is Intent.OUT_OF_SCOPE
    assert query.request is None
    assert query.clarification is None


def test_other_city_turns_plan_new_into_out_of_scope() -> None:
    query = _parse(
        "đi Đà Nẵng 3 ngày từ 10/12",
        _answer(intent="plan_new", date_text="10/12", duration_text="3 ngày", city="Đà Nẵng"),
    )
    assert query.intent is Intent.OUT_OF_SCOPE
    assert query.request is None


def test_hue_city_name_keeps_plan_new() -> None:
    query = _parse(
        "đi Thành phố Huế 2 ngày 20/12",
        _answer(date_text="20/12", duration_text="2 ngày", city="Thành phố Huế"),
    )
    assert query.intent is Intent.PLAN_NEW
    assert query.request is not None


def test_place_info_keeps_mentions_without_request() -> None:
    places = [_place("huetripo:627150", "Lăng vua Khải Định", Category.HISTORIC)]
    query = _parse(
        "Lăng Khải Định mở cửa lúc mấy giờ?",
        _answer(intent="place_info", must_include_mentions=["Lăng Khải Định"]),
        places,
    )
    assert query.intent is Intent.PLACE_INFO
    assert query.request is None
    assert query.clarification is None
    assert [item.place_id for item in query.must_include] == ["huetripo:627150"]


def test_modify_plan_keeps_exclusions_and_partial_without_request() -> None:
    query = _parse(
        "bỏ cà phê ra khỏi lịch",
        _answer(intent="modify_plan", exclude_category_phrases=["cà phê"]),
    )
    assert query.intent is Intent.MODIFY_PLAN
    assert query.request is None
    assert query.exclude_categories == [Category.CAFE]


def test_extraction_model_rejects_unknown_intent_value() -> None:
    with pytest.raises(ValueError):
        Extraction.model_validate_json(_answer(intent="bay"))


def test_bare_mot_means_day_after_tomorrow_but_counting_mot_is_not_a_date() -> None:
    query = _parse("Mốt đi Huế 2 ngày, xe máy", _answer(duration_text="2 ngày"))
    assert query.request is not None
    assert query.request.start_date == dt.date(2026, 11, 20)
    counting = _parse("đi Huế một mình 2 ngày", _answer(duration_text="2 ngày"))
    assert counting.request is None
    assert "start_date" not in counting.partial
