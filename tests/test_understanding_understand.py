"""understand(): rules fallback, LLM post-processing, clarification and plan changes (no network)."""

from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path

_BACKEND = _Path(__file__).resolve().parents[1] / "backend"
if str(_BACKEND) not in _sys.path:
    _sys.path.insert(0, str(_BACKEND))

import datetime as dt  # noqa: E402
from typing import Any  # noqa: E402

import pytest  # noqa: E402

from app.schemas.place import Place, PlaceCategory  # noqa: E402
from app.schemas.request import TripRequest  # noqa: E402
from app.understanding.extract import ExtractionError, Extraction  # noqa: E402
from app.understanding.models import (  # noqa: E402
    ApproveOption,
    Intent,
    PlanChange,
    PlanChangeKind,
    QuSource,
)
from app.understanding.understand import (  # noqa: E402
    ConversationContext,
    apply_changes,
    understand,
)

REF = dt.date(2026, 11, 18)  # a Wednesday


def _place(place_id: str, name: str, category: PlaceCategory) -> Place:
    return Place(
        id=place_id,
        name=name,
        category=category,
        lat=16.47,
        lon=107.58,
        opening_hours_confidence="UNKNOWN",
        price_status="UNKNOWN",
        source="test",
        source_place_id=place_id,
        collected_at=dt.datetime(2026, 11, 1, tzinfo=dt.UTC),
        raw_attributes={},
    )


PLACES = [
    _place("p1", "Chùa Thiên Mụ", "religious"),
    _place("p2", "Đại Nội Huế", "historic"),
    _place("p3", "Chợ Đông Ba", "market"),
]

BASE: dict[str, Any] = {
    "intent": "plan_new",
    "date_text": None,
    "duration_text": None,
    "origin": None,
    "people": None,
    "rooms": None,
    "budget_text": None,
    "city": None,
    "interest_phrases": [],
    "must_include_mentions": [],
    "exclude_mentions": [],
    "exclude_category_phrases": [],
    "soft_preferences": [],
    "changes": [],
    "approve_option": None,
}


class FakeExtractor:
    """Returns a fixed Extraction built from BASE with overrides; records the calls."""

    def __init__(self, **overrides: Any) -> None:
        self.payload = {**BASE, **overrides}
        self.calls: list[str] = []

    def extract(self, text: str, ref: dt.date) -> Extraction:
        self.calls.append(text)
        return Extraction.model_validate(self.payload)


class BrokenExtractor:
    def extract(self, text: str, ref: dt.date) -> Extraction:
        raise ExtractionError("Ollama không trả lời: connection refused")


def _request(**overrides: Any) -> TripRequest:
    payload: dict[str, Any] = {
        "origin": "Huế",
        "destination": "Huế",
        "start_date": dt.date(2026, 11, 21),
        "end_date": dt.date(2026, 11, 22),
        "people": 2,
    }
    payload.update(overrides)
    return TripRequest(**payload)


# ---------------------------------------------------------------------------
# Rules path (no extractor)
# ---------------------------------------------------------------------------


def test_rules_path_builds_request_from_numeric_date_and_duration() -> None:
    query = understand("Đi Huế 2 ngày từ 20/12, thích lăng tẩm", REF)

    assert query.intent is Intent.PLAN_NEW
    assert query.source is QuSource.RULES
    assert query.request is not None
    assert query.request.start_date == dt.date(2026, 12, 20)
    assert query.request.end_date == dt.date(2026, 12, 21)
    assert query.clarification is None


def test_rules_path_one_day_trip_has_same_start_and_end() -> None:
    query = understand("Đi Huế 1 ngày 22/11 bằng xe máy", REF)

    assert query.request is not None
    assert query.request.start_date == query.request.end_date == dt.date(2026, 11, 22)


def test_rules_path_without_date_asks_for_start_and_lists_missing() -> None:
    query = understand("Đi Huế 2 ngày, thích lăng tẩm", REF)

    assert query.request is None
    assert query.clarification
    assert "start_date" in query.missing_fields
    assert "end_date" in query.missing_fields
    assert query.quick_replies


def test_rules_path_other_city_is_out_of_scope() -> None:
    query = understand("Đi Đà Nẵng 3 ngày từ 10/12", REF)

    assert query.intent is Intent.OUT_OF_SCOPE
    assert query.request is None


def test_defaults_fill_origin_and_people_only_in_the_request() -> None:
    query = understand("Đi Huế 2 ngày từ 20/12", REF)

    assert query.request is not None
    assert query.request.origin == "Huế"
    assert query.request.people == 1
    assert "origin" in query.missing_fields
    assert "people" in query.missing_fields


def test_defaulted_fields_list_origin_and_people_when_not_stated() -> None:
    query = understand("Đi Huế 2 ngày từ 20/12", REF)

    assert query.defaulted_fields == ["origin", "people"]
    assert query.request is not None
    assert query.request.origin == "Huế"


def test_defaulted_fields_empty_when_origin_and_people_are_stated() -> None:
    extractor = FakeExtractor(
        date_text="20/12", duration_text="2 ngày", origin="Hà Nội", people=2
    )

    query = understand("Từ Hà Nội, 2 người, đi Huế 2 ngày từ 20/12", REF, extractor=extractor, places=PLACES)

    assert query.request is not None
    assert query.defaulted_fields == []
    assert query.missing_fields == []


def test_defaulted_fields_lists_only_the_unstated_one() -> None:
    extractor = FakeExtractor(date_text="20/12", duration_text="2 ngày", origin="Hà Nội")

    query = understand("Từ Hà Nội đi Huế 2 ngày từ 20/12", REF, extractor=extractor, places=PLACES)

    assert query.defaulted_fields == ["people"]
    assert query.missing_fields == ["people"]


def test_defaulted_fields_empty_for_modify_and_other_intents() -> None:
    extractor = FakeExtractor(intent="place_info")

    query = understand("Chợ Đông Ba mở cửa lúc mấy giờ?", REF, extractor=extractor, places=PLACES)

    assert query.defaulted_fields == []


def test_more_than_seven_days_asks_for_fewer() -> None:
    extractor = FakeExtractor(date_text="20/12", duration_text="9 ngày")

    query = understand("Đi Huế 9 ngày từ 20/12", REF, extractor=extractor, places=PLACES)

    assert query.request is None
    assert "7" in (query.clarification or "")


# ---------------------------------------------------------------------------
# LLM path: code resolves what the model copied
# ---------------------------------------------------------------------------


def test_llm_phrases_are_resolved_by_code() -> None:
    extractor = FakeExtractor(
        date_text="cuối tuần này",
        duration_text="2 ngày 1 đêm",
        people=2,
        budget_text="khoảng 4 triệu",
        interest_phrases=["đi chùa", "đặc sản"],
    )

    query = understand("Cuối tuần này đi Huế 2 ngày 1 đêm, 2 người", REF, extractor=extractor, places=PLACES)

    assert query.source is QuSource.OLLAMA
    assert query.request is not None
    assert query.request.start_date == dt.date(2026, 11, 21)
    assert query.request.end_date == dt.date(2026, 11, 22)
    assert query.request.budget_vnd == 4_000_000
    assert query.request.people == 2
    assert set(query.request.categories) == {"religious", "restaurant"}


def test_llm_unresolvable_date_asks_with_the_phrase() -> None:
    extractor = FakeExtractor(date_text="tháng sau", duration_text="3 ngày")

    query = understand("Tháng sau đi Huế 3 ngày", REF, extractor=extractor, places=PLACES)

    assert query.request is None
    assert 'tháng sau' in (query.clarification or "")


def test_llm_place_mentions_are_linked_to_poi_ids() -> None:
    extractor = FakeExtractor(
        date_text="20/12",
        duration_text="2 ngày",
        must_include_mentions=["chùa Thiên Mụ"],
        exclude_mentions=["Đại Nội"],
    )

    query = understand("x", REF, extractor=extractor, places=PLACES)

    assert [item.poi_id for item in query.must_include] == ["p1"]
    assert [item.poi_id for item in query.exclude] == ["p2"]


def test_llm_exclude_category_phrases_map_to_categories() -> None:
    extractor = FakeExtractor(
        date_text="20/12", duration_text="2 ngày", exclude_category_phrases=["chợ"]
    )

    query = understand("x", REF, extractor=extractor, places=PLACES)

    assert query.exclude_categories == ["market"]


def test_unmapped_interest_phrase_goes_to_soft_preferences() -> None:
    extractor = FakeExtractor(
        date_text="20/12", duration_text="2 ngày", interest_phrases=["xem nghệ thuật đường phố"]
    )

    query = understand("x", REF, extractor=extractor, places=PLACES)

    assert "xem nghệ thuật đường phố" in query.soft_preferences


def test_place_info_keeps_the_place_only() -> None:
    extractor = FakeExtractor(intent="place_info", must_include_mentions=["Chùa Thiên Mụ"])

    query = understand("Chùa Thiên Mụ mở cửa mấy giờ?", REF, extractor=extractor, places=PLACES)

    assert query.intent is Intent.PLACE_INFO
    assert query.place_query is not None
    assert query.place_query.poi_id == "p1"
    assert query.must_include == []


def test_llm_out_of_scope_city_gives_no_request() -> None:
    extractor = FakeExtractor(city="Đà Lạt", date_text="10/1", duration_text="3 ngày")

    query = understand("Đi Đà Lạt 3 ngày từ 10/1", REF, extractor=extractor, places=PLACES)

    assert query.intent is Intent.OUT_OF_SCOPE
    assert query.request is None


def test_approve_option_is_carried() -> None:
    extractor = FakeExtractor(intent="approve", approve_option="BUDGET")

    query = understand("Chọn gói tiết kiệm", REF, extractor=extractor, places=PLACES)

    assert query.intent is Intent.APPROVE
    assert query.approve_option is ApproveOption.BUDGET


def test_extraction_error_falls_back_to_rules_with_a_note() -> None:
    query = understand(
        "Đi Huế 2 ngày từ 20/12", REF, extractor=BrokenExtractor(), places=PLACES
    )

    assert query.source is QuSource.RULES
    assert query.request is not None
    assert any("Ollama không dùng được" in note for note in query.notes)


def test_modify_plan_maps_place_and_day_changes_with_linked_ids() -> None:
    extractor = FakeExtractor(
        intent="modify_plan",
        changes=[
            {"kind": "remove_place", "text": "bỏ chùa Thiên Mụ", "value": None},
            {"kind": "add_days", "text": "thêm một ngày nữa", "value": "1"},
        ],
    )

    query = understand("x", REF, extractor=extractor, places=PLACES)

    assert query.intent is Intent.MODIFY_PLAN
    assert [change.kind for change in query.changes] == [
        PlanChangeKind.REMOVE_PLACE,
        PlanChangeKind.ADD_DAYS,
    ]
    assert query.changes[0].value == "p1"
    assert query.changes[1].value == 1


def test_modify_plan_set_people_reads_the_number_from_the_text() -> None:
    extractor = FakeExtractor(
        intent="modify_plan",
        changes=[{"kind": "set_people", "text": "Đổi thành 4 người", "value": "}]}}{"}],
    )
    context = ConversationContext(request=_request())

    query = understand("x", REF, context, extractor=extractor, places=PLACES)

    assert query.changes[0].value == 4
    assert query.request is not None
    assert query.request.people == 4


def test_modify_plan_set_budget_reads_a_spoken_amount() -> None:
    extractor = FakeExtractor(
        intent="modify_plan",
        changes=[{"kind": "set_budget", "text": "Tăng ngân sách lên 10 triệu", "value": "10 triệu"}],
    )
    context = ConversationContext(request=_request())

    query = understand("x", REF, context, extractor=extractor, places=PLACES)

    assert query.changes[0].value == 10_000_000
    assert query.request is not None
    assert query.request.budget_vnd == 10_000_000


def test_modify_plan_category_word_becomes_an_exclude_category() -> None:
    extractor = FakeExtractor(
        intent="modify_plan",
        changes=[{"kind": "remove_place", "text": "bỏ chùa", "value": None}],
    )
    context = ConversationContext(request=_request())

    query = understand("x", REF, context, extractor=extractor, places=PLACES)

    assert [(c.kind, c.value) for c in query.changes] == [
        (PlanChangeKind.EXCLUDE_CATEGORY, "religious")
    ]
    assert query.request is not None
    assert "religious" in query.request.exclude_categories


def test_modify_plan_remove_place_with_leading_verb_links_the_place() -> None:
    extractor = FakeExtractor(
        intent="modify_plan",
        changes=[{"kind": "remove_place", "text": "Bỏ Đại Nội", "value": None}],
    )
    context = ConversationContext(request=_request())

    query = understand("x", REF, context, extractor=extractor, places=PLACES)

    assert [(c.kind, c.value) for c in query.changes] == [(PlanChangeKind.REMOVE_PLACE, "p2")]
    assert query.request is not None
    assert query.request.exclude_poi_ids == ["p2"]


def test_modify_plan_add_place_with_a_phrase_links_the_place() -> None:
    extractor = FakeExtractor(
        intent="modify_plan",
        changes=[{"kind": "add_place", "text": "Thêm chợ Đông Ba vào lịch", "value": "chợ Đông Ba"}],
    )
    context = ConversationContext(request=_request())

    query = understand("x", REF, context, extractor=extractor, places=PLACES)

    assert [(c.kind, c.value) for c in query.changes] == [(PlanChangeKind.ADD_PLACE, "p3")]
    assert query.request is not None
    assert query.request.must_include_poi_ids == ["p3"]


def test_modify_plan_applies_changes_to_context_request() -> None:
    extractor = FakeExtractor(
        intent="modify_plan",
        changes=[{"kind": "add_days", "text": "thêm một ngày nữa", "value": "1"}],
    )
    context = ConversationContext(request=_request())

    query = understand("x", REF, context, extractor=extractor, places=PLACES)

    assert query.request is not None
    assert query.request.end_date == dt.date(2026, 11, 23)


# ---------------------------------------------------------------------------
# apply_changes
# ---------------------------------------------------------------------------


def test_apply_changes_adds_and_removes_days_without_passing_start() -> None:
    request = _request()
    added, _ = apply_changes(request, [PlanChange(kind=PlanChangeKind.ADD_DAYS, value=2)])
    assert added.end_date == dt.date(2026, 11, 24)

    kept, notes = apply_changes(request, [PlanChange(kind=PlanChangeKind.REMOVE_DAYS, value=5)])
    assert kept.end_date == request.end_date
    assert notes


def test_apply_changes_set_dates_keeps_the_length() -> None:
    changed, _ = apply_changes(
        _request(), [PlanChange(kind=PlanChangeKind.SET_DATES, value="2026-12-05")]
    )
    assert changed.start_date == dt.date(2026, 12, 5)
    assert changed.end_date == dt.date(2026, 12, 6)


def test_apply_changes_set_people_and_budget() -> None:
    changed, _ = apply_changes(
        _request(),
        [
            PlanChange(kind=PlanChangeKind.SET_PEOPLE, value="4"),
            PlanChange(kind=PlanChangeKind.SET_BUDGET, value="6000000"),
        ],
    )
    assert changed.people == 4
    assert changed.budget_vnd == 6_000_000


def test_apply_changes_include_and_exclude_category() -> None:
    included, _ = apply_changes(
        _request(), [PlanChange(kind=PlanChangeKind.INCLUDE_CATEGORY, value="cafe")]
    )
    assert included.categories == ["cafe"]
    assert included.exclude_categories == []
    removed, _ = apply_changes(
        included, [PlanChange(kind=PlanChangeKind.EXCLUDE_CATEGORY, value="cafe")]
    )
    assert removed.categories == []
    assert removed.exclude_categories == ["cafe"]
    reincluded, _ = apply_changes(
        removed, [PlanChange(kind=PlanChangeKind.INCLUDE_CATEGORY, value="cafe")]
    )
    assert reincluded.categories == ["cafe"]
    assert reincluded.exclude_categories == []


def test_apply_changes_place_edits_become_must_include_and_exclude_ids() -> None:
    added, notes = apply_changes(
        _request(), [PlanChange(kind=PlanChangeKind.ADD_PLACE, value="p3", text="chợ Đông Ba")]
    )
    assert added.must_include_poi_ids == ["p3"]
    assert notes == []
    removed, _ = apply_changes(
        added, [PlanChange(kind=PlanChangeKind.REMOVE_PLACE, value="p3", text="chợ Đông Ba")]
    )
    assert removed.must_include_poi_ids == []
    assert removed.exclude_poi_ids == ["p3"]


def test_apply_changes_unlinked_place_edit_gives_a_note() -> None:
    changed, notes = apply_changes(
        _request(), [PlanChange(kind=PlanChangeKind.REMOVE_PLACE, text="Bỏ Nhà Nào Đó")]
    )
    assert changed == _request()
    assert any("Không tìm thấy" in note for note in notes)


def test_apply_changes_invalid_result_keeps_original_with_note() -> None:
    request = _request()
    changed, notes = apply_changes(
        request, [PlanChange(kind=PlanChangeKind.SET_PEOPLE, value="25")]
    )
    assert changed == request
    assert notes


# Rules fallback: place questions (no Ollama) use the real Hue catalog.


def test_rules_place_question_with_a_linked_place_is_place_info() -> None:
    query = understand("Đại Nội mở cửa mấy giờ?", REF)

    assert query.intent is Intent.PLACE_INFO
    assert query.source is QuSource.RULES
    assert query.place_query is not None
    assert query.place_query.poi_id == "huetripo:531787"


def test_rules_ticket_price_question_is_place_info() -> None:
    query = understand("Giá vé lăng Tự Đức bao nhiêu?", REF)

    assert query.intent is Intent.PLACE_INFO
    assert query.place_query is not None
    assert query.place_query.poi_id is not None


def test_rules_nearby_question_anchors_on_the_place_after_gan() -> None:
    query = understand("quán bún bò gần Đại Nội", REF)

    assert query.intent is Intent.PLACE_INFO
    assert query.place_query is not None
    assert query.place_query.poi_id == "huetripo:531787"


def test_rules_trip_sentence_without_a_question_stays_plan_new() -> None:
    query = understand("Tôi đi Huế 3 ngày từ 05/12", REF)

    assert query.intent is Intent.PLAN_NEW


def test_rules_trip_question_with_days_stays_plan_new() -> None:
    query = understand("Lên lịch Huế 2 ngày từ 20/12, đi Đại Nội không?", REF)

    assert query.intent is Intent.PLAN_NEW


# ---------------------------------------------------------------------------
# Smalltalk: greetings and thanks are not a plan, and not out of scope either
# ---------------------------------------------------------------------------


def test_rules_greeting_is_smalltalk() -> None:
    query = understand("xin chào", REF)

    assert query.intent is Intent.SMALLTALK
    assert query.request is None


def test_llm_out_of_scope_thanks_becomes_smalltalk() -> None:
    query = understand("cảm ơn bạn", REF, extractor=FakeExtractor(intent="out_of_scope"), places=PLACES)

    assert query.intent is Intent.SMALLTALK


@pytest.mark.parametrize(
    ("text", "overrides"),
    [
        # Bare answers to a clarifying question; the model sees them alone and says smalltalk.
        ("ngày mai", {"date_text": "ngày mai"}),
        ("ok", {}),
    ],
)
def test_llm_smalltalk_without_rule_match_is_a_trip_message(text: str, overrides: dict[str, Any]) -> None:
    extractor = FakeExtractor(intent="smalltalk", **overrides)
    query = understand(text, REF, extractor=extractor, places=PLACES)

    assert query.intent is Intent.PLAN_NEW


@pytest.mark.parametrize(
    ("text", "people"),
    [
        ("tôi muốn đi Huế 3 ngày 2 đêm với người yêu", 2),
        ("đi Huế 2 ngày cùng vợ", 2),
        ("vợ chồng mình muốn đi Huế 3 ngày", 2),
        ("đi Huế 3 ngày với người yêu và 2 bạn", None),  # a bigger group: not inferred
        ("đi Huế 3 ngày cùng gia đình", None),
        ("đi Huế 3 ngày", None),
    ],
)
def test_couple_without_head_count_is_two_people(text: str, people: int | None) -> None:
    query = understand(text, REF, extractor=FakeExtractor(intent="plan_new"), places=PLACES)

    assert query.fields.get("people") == people


def test_stated_head_count_wins_over_couple() -> None:
    extractor = FakeExtractor(intent="plan_new", people=3)
    query = understand("đi Huế với người yêu, 3 người", REF, extractor=extractor, places=PLACES)

    assert query.fields.get("people") == 3


def test_llm_smalltalk_confirmed_by_rules_stays_smalltalk() -> None:
    query = understand("xin chào", REF, extractor=FakeExtractor(intent="smalltalk"), places=PLACES)

    assert query.intent is Intent.SMALLTALK


def test_llm_plan_new_with_trip_details_stays_plan_new() -> None:
    text = "chào bạn, cho mình đi Huế 3 ngày từ 5/12"
    query = understand(text, REF, extractor=FakeExtractor(intent="plan_new"), places=PLACES)

    assert query.intent is Intent.PLAN_NEW


def test_nature_and_scenery_interests_become_the_nature_theme_not_the_park_category() -> None:
    parsed = understand("đi Huế 3 ngày từ 5/12, thích thiên nhiên và ngắm cảnh", REF)

    assert parsed.fields["themes"] == ["nature"]
    assert "park" not in parsed.fields["categories"]
    assert parsed.request is not None
    assert parsed.request.themes == ["nature"]


def test_parse_reads_transport_stay_and_pace_from_the_message() -> None:
    query = understand(
        "Đi Huế 2 ngày từ 20/12 từ Hà Nội 2 người, đi tàu, ở resort, lịch thong thả", REF
    )

    assert query.request is not None
    assert query.request.transport_mode == "train"
    assert query.request.hotel_tier == "resort"
    assert query.request.pace == "relaxed"


def test_parse_leaves_unstated_slots_as_any_and_moderate_pace() -> None:
    query = understand("Đi Huế 2 ngày từ 20/12 từ Hà Nội 2 người", REF)

    assert query.request is not None
    assert query.request.transport_mode is None
    assert query.request.hotel_tier is None
    assert query.request.pace == "moderate"
