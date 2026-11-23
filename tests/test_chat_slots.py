"""Slot filling rules: value recognition, the required-slot fallbacks, the restated line and question batching."""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.chat import texts  # noqa: E402
from app.chat.draft import (  # noqa: E402
    build_request,
    mark_asked,
    money_text,
    next_questions,
    pending_units,
    precheck_due,
    precheck_key,
    restated,
)
from app.chat.slots import interests_from, origin_from, take_answers, value_of  # noqa: E402
from app.schemas.request import TripRequest  # noqa: E402


def _full(**overrides: object) -> dict:
    """A draft with every required slot settled (origin Hà Nội, 2 people, 3 days, 6 triệu, food)."""
    draft: dict = {
        "origin": "Hà Nội",
        "people": 2,
        "start_date": "2026-11-24",
        "num_days": 3,
        "budget_vnd": 6_000_000,
        "categories": ["restaurant"],
    }
    draft.update(overrides)
    return draft


@pytest.mark.parametrize(
    "text, value",
    [
        ("xe giường nằm", "bus"),
        ("xe khách", "bus"),
        ("bus", "bus"),
        ("xe", "bus"),
        ("tàu hỏa", "train"),
        ("tàu lửa", "train"),
        ("máy bay", "flight"),
        ("bay", "flight"),
        ("xem phim", None),
        ("6 triệu", None),
    ],
)
def test_transport_words_are_recognised_as_whole_words(text: str, value: str | None) -> None:
    assert value_of("transport", text) == value


@pytest.mark.parametrize(
    "text, value",
    [("homestay", "homestay"), ("khách sạn", "hotel"), ("ks", "hotel"), ("resort", "resort"), ("6 triệu", None)],
)
def test_stay_words_are_recognised(text: str, value: str | None) -> None:
    assert value_of("stay", text) == value


@pytest.mark.parametrize(
    "text, value",
    [
        ("thong thả", "relaxed"),
        ("nhẹ nhàng", "relaxed"),
        ("vừa phải", "moderate"),
        ("đi nhiều", "packed"),
        ("ở đây", None),
    ],
)
def test_pace_words_are_recognised_and_here_is_not_a_pace(text: str, value: str | None) -> None:
    assert value_of("pace", text) == value


def test_an_early_answer_fills_transport_and_stay_without_being_asked() -> None:
    answered = take_answers(_full(), "xe giường nằm, homestay", {})

    assert answered["transport_mode"] == "bus"
    assert answered["hotel_tier"] == "homestay"
    assert "transport" not in pending_units(answered)
    assert "stay" not in pending_units(answered)


def test_tuy_settles_the_optional_units_that_were_asked() -> None:
    draft = _full(last_asked=["transport", "stay", "places"], asked=["transport", "stay", "places"])

    answered = take_answers(draft, "tùy", {})

    assert answered["transport_mode"] == "any"
    assert answered["hotel_tier"] == "any"
    assert answered["places_done"] is True


def test_an_unrecognised_answer_settles_an_asked_optional_unit_as_any() -> None:
    answered = take_answers(_full(last_asked=["pace"]), "6 triệu", {})

    assert answered["pace"] == "any"


def test_khong_settles_the_places_question_with_no_places() -> None:
    answered = take_answers(_full(last_asked=["places"]), "không", {})

    assert answered["places_done"] is True
    assert "must_include_poi_ids" not in answered


def test_tuy_does_not_settle_an_optional_unit_that_was_not_asked() -> None:
    answered = take_answers(_full(last_asked=[]), "tùy", {})

    assert "transport_mode" not in answered and "hotel_tier" not in answered


def test_a_concrete_value_beats_the_any_settling() -> None:
    answered = take_answers(_full(last_asked=["transport"]), "xe giường nằm", {})

    assert answered["transport_mode"] == "bus"


@pytest.mark.parametrize(
    "text, fields, origin",
    [
        ("Hà Nội", {}, "Hà Nội"),
        ("từ Đà Nẵng", {}, "Đà Nẵng"),
        ("xuất phát từ hà nội", {}, "Hà Nội"),
        ("ngày mai", {}, None),
        ("3 ngày", {}, None),
        ("Hà Nội", {"num_days": 3}, None),
        ("để mình suy nghĩ thêm", {}, None),
    ],
)
def test_origin_fallback_takes_a_short_place_answer_only(text: str, fields: dict, origin: str | None) -> None:
    assert origin_from(text, fields) == origin


def test_origin_fallback_is_used_for_the_asked_origin_slot() -> None:
    draft = _full(origin=None, last_asked=["origin"])

    assert take_answers(draft, "Hà Nội", {})["origin"] == "Hà Nội"
    assert take_answers(draft, "ngày mai", {})["origin"] is None


def test_budget_fallback_reads_the_amount_of_an_asked_budget() -> None:
    draft = _full(budget_vnd=None, last_asked=["budget"])

    answered = take_answers(draft, "6 triệu", {})

    assert answered["budget_vnd"] == 6_000_000


def test_interest_fallback_maps_the_asked_interest_phrases() -> None:
    draft = _full(categories=[], last_asked=["interests"])

    answered = take_answers(draft, "ẩm thực, ngắm cảnh", {})

    assert "restaurant" in answered["categories"]
    assert "attraction" in answered["categories"]
    assert interests_from("ẩm thực và ngắm cảnh")[0] == interests_from("ẩm thực, ngắm cảnh")[0]


def test_restated_line_names_the_route_the_weekday_dates_and_the_length() -> None:
    assert restated(_full()) == "Mình ghi nhận: Hà Nội → Huế, 2 người, thứ Ba 24/11 – thứ Năm 26/11 (3 ngày 2 đêm), ngân sách 6 triệu, thích ẩm thực."


def test_interest_names_read_as_the_user_says_them() -> None:
    from app.chat.draft import interest_names

    assert interest_names(["restaurant", "cafe", "market", "attraction"], ["nature"]) == [
        "ẩm thực",
        "thiên nhiên, ngắm cảnh",
    ]
    assert interest_names(["historic", "religious"], []) == ["di tích", "chùa chiền"]
    assert interest_names(["cafe"], []) == ["cà phê"]


def test_pace_does_not_read_day_as_here() -> None:
    from app.chat.slots import value_of

    assert value_of("pace", "đây là lịch của mình") is None
    assert value_of("pace", "lịch dày một chút") == "packed"


def test_restated_line_for_a_one_day_trip_and_for_a_length_only() -> None:
    assert restated({"start_date": "2026-11-24", "num_days": 1}) == "Mình ghi nhận: Huế, thứ Ba 24/11 (1 ngày)."
    assert restated({"num_days": 3}) == "Mình ghi nhận: Huế, 3 ngày 2 đêm."


def test_restated_line_is_absent_when_nothing_beyond_the_destination_is_known() -> None:
    assert restated({}) is None
    assert restated({"origin": "Huế"}) == "Mình ghi nhận: Huế."


def test_money_is_written_in_millions_with_a_comma_or_in_dong() -> None:
    assert money_text(6_000_000) == "6 triệu"
    assert money_text(6_500_000) == "6,5 triệu"
    assert money_text(800_000) == "800.000 đ"


def test_next_questions_asks_when_and_origin_first_for_an_empty_draft() -> None:
    assert next_questions({}) == (
        "1. Bạn muốn đi Huế từ ngày nào và đi mấy ngày?\n2. Bạn xuất phát từ đâu?"
    )


def test_next_questions_asks_at_most_two_units_in_order_after_the_restated_line() -> None:
    text = next_questions(_full(origin=None, people=None, budget_vnd=None, categories=[]))

    assert text is not None
    lines = text.splitlines()
    assert lines[0].startswith("Mình ghi nhận: Huế, thứ Ba 24/11")
    assert lines[1:] == ["1. Bạn xuất phát từ đâu?", "2. Bạn đi mấy người?"]


def test_a_single_open_unit_is_asked_on_one_line() -> None:
    text = next_questions(_full(categories=[]))

    assert text is not None
    assert text.splitlines()[-1] == texts.QUESTIONS["interests"]


def test_required_units_come_before_optional_ones() -> None:
    draft = _full(budget_vnd=None)

    assert pending_units(draft) == ["budget"]
    assert "bằng gì" not in next_questions(draft)


def test_transport_is_skipped_when_the_trip_starts_in_hue() -> None:
    draft = _full(origin="Huế")

    assert pending_units(draft) == ["stay", "pace", "places"]
    assert texts.QUESTIONS["transport"] not in next_questions(draft)


def test_stay_is_skipped_on_a_one_day_trip() -> None:
    assert pending_units(_full(num_days=1)) == ["transport", "pace", "places"]


def test_an_optional_unit_is_asked_once() -> None:
    assert pending_units(_full(asked=["transport"])) == ["stay", "pace", "places"]


def test_optional_questions_are_asked_in_turn_after_the_required_ones() -> None:
    draft = _full()

    assert pending_units(draft) == ["transport", "stay", "pace", "places"]
    assert next_questions(draft).splitlines()[-2:] == [
        "1. " + texts.QUESTIONS["transport"],
        "2. " + texts.QUESTIONS["stay"],
    ]


def test_a_complete_draft_has_no_pending_units_and_no_question() -> None:
    draft = _full(transport_mode="bus", hotel_tier="any", pace="moderate", places_done=True)

    assert pending_units(draft) == []
    assert next_questions(draft) is None


def test_a_length_above_the_maximum_asks_for_fewer_days_without_restating_it() -> None:
    draft = _full(num_days=10)

    text = next_questions(draft)

    assert text is not None
    assert "tối đa 7 ngày" in text
    assert "10 ngày" not in text


def test_mark_asked_records_the_units_without_changing_the_draft() -> None:
    draft = _full()

    marked = mark_asked(draft, ["transport", "stay"])

    assert marked["last_asked"] == ["transport", "stay"]
    assert marked["asked"] == ["transport", "stay"]
    assert "last_asked" not in draft


def test_build_request_needs_origin_and_people() -> None:
    with pytest.raises(ValueError):
        build_request({"start_date": "2026-11-24", "num_days": 2, "people": 2})
    with pytest.raises(ValueError):
        build_request({"start_date": "2026-11-24", "num_days": 2, "origin": "Hà Nội"})


def test_build_request_of_a_complete_draft_has_the_trip_dates() -> None:
    request = build_request(_full())

    assert isinstance(request, TripRequest)
    assert request.origin == "Hà Nội"
    assert request.start_date == date(2026, 11, 24)
    assert request.end_date == date(2026, 11, 26)
    assert request.budget_vnd == 6_000_000


def test_build_request_maps_any_and_missing_slots_to_the_request_defaults() -> None:
    request = build_request(_full(transport_mode="any", hotel_tier="any", pace="any"))

    assert request.transport_mode is None
    assert request.hotel_tier is None
    assert request.pace == "moderate"
    assert build_request(_full()).pace == "moderate"


def test_build_request_passes_the_stated_slots() -> None:
    request = build_request(_full(transport_mode="train", hotel_tier="resort", pace="relaxed"))

    assert (request.transport_mode, request.hotel_tier, request.pace) == ("train", "resort", "relaxed")


# ---------------------------------------------------------------------------
# Early budget check (S2): the warning, the soft note, the due check and the budget answers
# ---------------------------------------------------------------------------

RESTATED = "Mình ghi nhận: Hà Nội → Huế, 2 người, thứ Ba 24/11 – thứ Năm 26/11 (3 ngày 2 đêm), ngân sách 6 triệu, thích ẩm thực."


def _precheck(low: int, high: int, mode: str | None = "BUS", tier: str | None = "HOMESTAY") -> dict:
    return {"key": "stored", "min": low, "max": high, "mode": mode, "tier": tier}


def _settled_stay(**overrides: object) -> dict:
    """Every required slot, transport and stay settled, pace and places settled too: only budget_ok can be open."""
    return _full(transport_mode="bus", hotel_tier="homestay", pace="moderate", places_done=True, **overrides)


def test_money_keeps_two_decimals_in_millions() -> None:
    assert money_text(6_350_000) == "6,35 triệu"
    assert money_text(7_760_000) == "7,76 triệu"
    assert money_text(1_760_000) == "1,76 triệu"


def test_over_budget_precheck_asks_the_budget_warning_with_exact_numbers() -> None:
    draft = _settled_stay(precheck=_precheck(6_350_000, 7_760_000))

    assert pending_units(draft) == ["budget_ok"]
    assert next_questions(draft) == (
        RESTATED
        + "\nLưu ý: phương án rẻ nhất (xe khách + homestay) ước tính 6,35–7,76 triệu, "
        + "vượt ngân sách 350.000 đ–1,76 triệu. Bạn muốn tăng ngân sách, hay giữ 6 triệu để mình chọn phương án tiết kiệm nhất?"
    )


def test_budget_warning_leaves_out_a_missing_mode_or_tier_and_its_parenthesis() -> None:
    only_tier = _settled_stay(precheck=_precheck(6_350_000, 7_760_000, mode=None))
    neither = _settled_stay(precheck=_precheck(6_350_000, 7_760_000, mode=None, tier=None))

    assert "(homestay) ước tính" in next_questions(only_tier)
    assert "phương án rẻ nhất ước tính 6,35–7,76 triệu" in next_questions(neither)


def test_under_budget_precheck_asks_nothing_about_the_budget() -> None:
    draft = _settled_stay(precheck=_precheck(5_150_000, 6_160_000))

    assert pending_units(draft) == []
    assert next_questions(draft) is None


def test_between_budget_and_maximum_adds_the_soft_note_once() -> None:
    draft = _full(
        transport_mode="bus", hotel_tier="homestay", budget_vnd=5_500_000, precheck=_precheck(5_150_000, 6_160_000)
    )
    lines = next_questions(draft).splitlines()

    assert lines[0] == restated(draft)
    assert lines[1] == "Chi phí ước tính 5,15–6,16 triệu, có thể vượt ngân sách một chút."
    assert lines[2:] == ["1. " + texts.QUESTIONS["pace"], "2. " + texts.QUESTIONS["places"]]
    assert "Chi phí ước tính" not in next_questions({**draft, "precheck_noted": True})


def test_precheck_is_due_once_transport_and_stay_are_settled_and_stale_when_the_key_changes() -> None:
    draft = _full(transport_mode="bus", hotel_tier="homestay")
    assert precheck_due(draft) is True
    draft["precheck"] = {"key": precheck_key(draft), "min": 5, "max": 6, "mode": "BUS", "tier": "HOMESTAY"}
    assert precheck_due(draft) is False
    assert precheck_due({**draft, "budget_vnd": 10_000_000}) is True
    assert precheck_due({**draft, "transport_mode": None}) is False
    assert precheck_due({**draft, "pace": "packed"}) is False


def test_accepted_budget_closes_the_warning() -> None:
    draft = _settled_stay(precheck=_precheck(6_350_000, 7_760_000), budget_accepted=True)

    assert pending_units(draft) == []


def test_budget_warning_answer_keeps_the_budget_on_a_keep_word_or_the_current_amount() -> None:
    draft = _settled_stay(precheck=_precheck(6_350_000, 7_760_000), last_asked=["budget_ok"])

    for text in ("giữ", "Giữ 6 triệu", "ok, vẫn được", "tiết kiệm", "không"):
        answered = take_answers(draft, text, {})
        assert answered.get("budget_accepted") is True, text
        assert answered["budget_vnd"] == 6_000_000, text


def test_budget_warning_answer_with_a_new_amount_replaces_the_budget_and_reopens_the_check() -> None:
    draft = _settled_stay(precheck=_precheck(6_350_000, 7_760_000), last_asked=["budget_ok"], budget_accepted=True)

    answered = take_answers(draft, "10 triệu", {})

    assert answered["budget_vnd"] == 10_000_000
    assert "budget_accepted" not in answered


def test_budget_warning_answer_that_is_not_an_answer_leaves_the_check_open() -> None:
    draft = _settled_stay(precheck=_precheck(6_350_000, 7_760_000), last_asked=["budget_ok"])

    answered = take_answers(draft, "hmm để xem", {})

    assert "budget_accepted" not in answered
    assert pending_units(answered) == ["budget_ok"]


def test_raising_the_budget_without_an_amount_asks_for_the_amount() -> None:
    draft = _settled_stay(precheck=_precheck(15_970_000, 17_900_000, mode="FLIGHT", tier="FOUR_STAR"))
    draft["last_asked"] = ["budget_ok"]

    raised = take_answers(draft, "tăng ngân sách", {})

    assert raised.get("budget_raise") is True
    assert not raised.get("budget_accepted")
    question = next_questions(raised)
    assert "tăng ngân sách lên bao nhiêu" in question
    assert "(máy bay + resort) cần khoảng 15,97–17,9 triệu" in question
    assert "vượt ngân sách" not in question  # the warning is not repeated

    raised["last_asked"] = ["budget_ok"]
    answered = take_answers(raised, "18 triệu", {})
    assert answered["budget_vnd"] == 18_000_000
    assert "budget_raise" not in answered


def test_origin_is_written_as_a_proper_name() -> None:
    from app.chat.slots import proper_name

    assert proper_name("Hà nội") == "Hà Nội"
    assert proper_name("đà nẵng") == "Đà Nẵng"
    assert proper_name("TP. Hồ Chí Minh") == "TP. Hồ Chí Minh"
