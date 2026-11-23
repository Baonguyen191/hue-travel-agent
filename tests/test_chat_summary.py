"""The summary before planning (S4), its marked edits (S5) and the pace recognisers of S5."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import pytest  # noqa: E402

from app.chat import texts  # noqa: E402
from app.chat.draft import summary_lines, summary_text  # noqa: E402
from app.chat.slots import pace_step, take_answers  # noqa: E402

DAI_NOI = "huetripo:531787"
CHO_DONG_BA = "huetripo:100"
NAMES = {DAI_NOI: "Đại Nội Huế", CHO_DONG_BA: "Chợ Đông Ba Huế"}


def _name_of(poi_id: str) -> str | None:
    return NAMES.get(poi_id)


def _precheck(low: int = 5_150_000, high: int = 6_160_000) -> dict:
    return {"key": "k", "min": low, "max": high, "mode": "BUS", "tier": "HOMESTAY"}


def _full(**overrides: object) -> dict:
    """The S4 example: Hà Nội → Huế, 24–26/11, 2 people, 6 triệu, bus, homestay, moderate, food and nature."""
    draft: dict = {
        "origin": "Hà Nội",
        "people": 2,
        "start_date": "2026-11-24",
        "num_days": 3,
        "budget_vnd": 6_000_000,
        "categories": ["restaurant", "attraction"],
        "themes": ["nature"],
        "transport_mode": "bus",
        "hotel_tier": "homestay",
        "pace": "moderate",
        "precheck": _precheck(),
        "must_include_poi_ids": [DAI_NOI],
        "exclude_poi_ids": [CHO_DONG_BA],
    }
    draft.update(overrides)
    return draft


EXAMPLE_SUMMARY = "\n".join(
    [
        "Mình tóm tắt lại chuyến đi:",
        "- Hành trình: Hà Nội → Huế, thứ Ba 24/11 – thứ Năm 26/11 (3 ngày 2 đêm)",
        "- Đoàn: 2 người, 1 phòng",
        "- Ngân sách: 6 triệu (ước tính 5,15–6,16 triệu)",
        "- Đi lại: xe giường nằm · Chỗ ở: homestay",
        "- Nhịp độ: vừa phải, 4 điểm tham quan mỗi ngày",
        "- Ưu tiên: ẩm thực, thiên nhiên, ngắm cảnh",
        "- Muốn đến: Đại Nội Huế · Tránh: Chợ Đông Ba Huế",
        "Mình lên lịch theo thông tin này nhé? Nếu cần sửa gì, bạn cứ nhắn.",
    ]
)


def test_summary_of_a_full_draft_has_the_exact_shape() -> None:
    assert summary_text(_full(), _name_of) == EXAMPLE_SUMMARY


def test_over_budget_accepted_says_the_cheapest_option_is_kept() -> None:
    draft = _full(budget_vnd=5_000_000, budget_accepted=True)

    text = summary_text(draft, _name_of)

    assert "- Ngân sách: 5 triệu (chọn phương án tiết kiệm nhất, ước tính 5,15–6,16 triệu)" in text.splitlines()


def test_budget_without_an_estimate_has_no_parenthesis() -> None:
    draft = _full(precheck={})

    assert "- Ngân sách: 6 triệu" in summary_text(draft, _name_of).splitlines()


def test_origin_hue_leaves_out_the_transport_part() -> None:
    lines = summary_text(_full(origin="Huế"), _name_of).splitlines()

    assert "- Hành trình: Huế, thứ Ba 24/11 – thứ Năm 26/11 (3 ngày 2 đêm)" in lines
    assert "- Đi lại: xe giường nằm · Chỗ ở: homestay" not in lines
    assert "- Chỗ ở: homestay" in lines


def test_one_day_trip_leaves_out_the_stay_part() -> None:
    draft = _full(num_days=1)

    lines = summary_text(draft, _name_of).splitlines()

    assert "- Hành trình: Hà Nội → Huế, thứ Ba 24/11 (1 ngày)" in lines
    assert "- Đi lại: xe giường nằm" in lines


def test_origin_hue_and_one_day_drop_the_whole_travel_line() -> None:
    draft = _full(origin="Huế", num_days=1)

    assert "travel" not in summary_lines(draft, _name_of)
    assert not any(line.startswith("- Đi lại") or line.startswith("- Chỗ ở") for line in summary_text(draft, _name_of).splitlines())


def test_unknown_choices_read_as_the_cheapest_option_and_any_pace_as_moderate() -> None:
    draft = _full(transport_mode="any", hotel_tier="any", pace="any")

    text = summary_text(draft, _name_of)

    assert "- Đi lại: chọn rẻ nhất · Chỗ ở: chọn rẻ nhất" in text.splitlines()
    assert "- Nhịp độ: vừa phải, 4 điểm tham quan mỗi ngày" in text.splitlines()


@pytest.mark.parametrize(
    "pace, line",
    [
        ("relaxed", "- Nhịp độ: thong thả, 3 điểm tham quan mỗi ngày"),
        ("moderate", "- Nhịp độ: vừa phải, 4 điểm tham quan mỗi ngày"),
        ("packed", "- Nhịp độ: đi nhiều, 5 điểm tham quan mỗi ngày"),
    ],
)
def test_pace_line_says_the_stops_per_day(pace: str, line: str) -> None:
    assert line in summary_text(_full(pace=pace), _name_of).splitlines()


def test_must_and_avoid_lines_use_the_names_and_the_excluded_categories() -> None:
    draft = _full(exclude_categories=["market"])

    lines = summary_text(draft, _name_of).splitlines()

    assert "- Muốn đến: Đại Nội Huế · Tránh: Chợ Đông Ba Huế, chợ" in lines


def test_a_place_without_a_name_is_left_out_and_empty_places_drop_the_line() -> None:
    draft = _full(must_include_poi_ids=["unknown"], exclude_poi_ids=[])

    text = summary_text(draft, _name_of)

    assert "Muốn đến" not in text
    assert "Tránh" not in text


def test_a_changed_budget_marks_only_the_budget_line() -> None:
    before = _full()
    previous = summary_lines(before, _name_of)

    text = summary_text(_full(budget_vnd=8_000_000), _name_of, previous=previous)

    marked = [line for line in text.splitlines() if line.endswith(texts.CHANGED_MARK)]
    assert marked == ["- Ngân sách: 8 triệu (ước tính 5,15–6,16 triệu) ← đã đổi"]


def test_without_a_previous_summary_nothing_is_marked() -> None:
    assert texts.CHANGED_MARK not in summary_text(_full(), _name_of)


def test_an_unchanged_summary_marks_nothing() -> None:
    draft = _full()

    assert texts.CHANGED_MARK not in summary_text(draft, _name_of, previous=summary_lines(draft, _name_of))


@pytest.mark.parametrize(
    "text, step",
    [
        ("thêm số lượng điểm đến", 1),
        ("thêm vài điểm", 1),
        ("nhiều điểm hơn", 1),
        ("đi nhiều hơn", 1),
        ("bớt điểm", -1),
        ("ít điểm hơn", -1),
        ("thong thả hơn", -1),
        ("tùy", 0),
        ("ok", 0),
        ("Đại Nội có mở cửa lúc mấy giờ?", 0),
    ],
)
def test_pace_step_words_move_the_pace_one_step(text: str, step: int) -> None:
    assert pace_step(text) == step


@pytest.mark.parametrize(
    "pace, text, expected",
    [
        ("moderate", "thêm số lượng điểm đến", "packed"),
        ("packed", "thêm số lượng điểm đến", "packed"),
        ("moderate", "thong thả hơn", "relaxed"),
        ("relaxed", "thong thả hơn", "relaxed"),
        ("packed", "bớt điểm", "moderate"),
        ("any", "thêm vài điểm", "packed"),
        (None, "bớt điểm", "relaxed"),
    ],
)
def test_a_pace_step_is_applied_to_the_draft_and_the_ends_stay_put(pace: str | None, text: str, expected: str) -> None:
    draft = {"pace": pace} if pace is not None else {}

    assert take_answers(draft, text, {})["pace"] == expected


def test_a_pace_word_that_is_not_a_step_still_sets_the_pace() -> None:
    assert take_answers({"pace": "packed"}, "thong thả, không", {})["pace"] == "relaxed"


def test_adding_a_named_place_does_not_change_the_pace() -> None:
    from app.chat.slots import pace_step

    assert pace_step("thêm điểm Đại Nội") == 0
    assert pace_step("thêm vài điểm nữa") == 1
