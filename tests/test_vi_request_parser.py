"""Rule-based Vietnamese request parser (spec section 1). No network, no guessing."""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.services.vi_request_parser import parse_vietnamese_request, with_start_date  # noqa: E402

TODAY = date(2026, 11, 21)
DOD_TEXT = (
    "Tôi đi Huế 3 ngày 2 đêm, xuất phát Hà Nội, 2 người, "
    "ngân sách 6 triệu, thích di tích và đặc sản"
)


def test_dod_sentence_extracts_every_stated_field_and_marks_dates_missing() -> None:
    parsed = parse_vietnamese_request(DOD_TEXT, TODAY)

    assert parsed.fields["origin"] == "Hà Nội"
    assert parsed.fields["destination"] == "Huế"
    assert parsed.fields["duration_days"] == 3
    assert parsed.fields["nights"] == 2
    assert parsed.fields["people"] == 2
    assert parsed.fields["budget_vnd"] == 6_000_000
    assert parsed.fields["preferences"] == ["di tích", "đặc sản"]
    assert {"start_date", "end_date"} <= set(parsed.missing_fields)
    assert parsed.request is None
    assert parsed.source == "FORM_FALLBACK"


def test_day_month_with_default_year_builds_a_request_from_duration() -> None:
    parsed = parse_vietnamese_request(DOD_TEXT.replace("Tôi đi Huế", "Tôi đi Huế 05/12"), TODAY)

    assert parsed.fields["start_date"] == date(2026, 12, 5)
    assert parsed.fields["end_date"] == date(2026, 12, 7)
    assert parsed.request is not None
    assert parsed.request.start_date == date(2026, 12, 5)
    assert parsed.request.end_date == date(2026, 12, 7)
    assert parsed.source == "RULES"
    assert parsed.missing_fields == []


def test_day_month_before_today_rolls_over_to_next_year() -> None:
    parsed = parse_vietnamese_request("đi Huế từ 05/01 3 ngày 2 đêm 2 người", TODAY)

    assert parsed.fields["start_date"] == date(2027, 1, 5)


def test_explicit_year_and_second_date_are_used_as_given() -> None:
    parsed = parse_vietnamese_request("đi Huế 05/12/2026 - 08/12/2026, 2 người", TODAY)

    assert parsed.fields["start_date"] == date(2026, 12, 5)
    assert parsed.fields["end_date"] == date(2026, 12, 8)


def test_invalid_date_is_not_invented() -> None:
    parsed = parse_vietnamese_request("đi Huế 31/02 2 người", TODAY)

    assert "start_date" not in parsed.fields
    assert "start_date" in parsed.missing_fields


def test_budget_forms_become_integer_vnd() -> None:
    cases = {
        "ngân sách 6tr": 6_000_000,
        "ngân sách 500k": 500_000,
        "ngân sách 6,5 triệu": 6_500_000,
        "ngân sách 6.000.000": 6_000_000,
        "ngân sách 6.000.000 đ": 6_000_000,
    }
    for phrase, expected in cases.items():
        parsed = parse_vietnamese_request(f"đi Huế, {phrase}", TODAY)
        assert parsed.fields["budget_vnd"] == expected, phrase


def test_ambiguous_budget_number_is_not_guessed() -> None:
    parsed = parse_vietnamese_request("đi Huế, ngân sách 6 trong ba ngày", TODAY)

    assert "budget_vnd" not in parsed.fields


def test_couple_phrase_means_two_people() -> None:
    parsed = parse_vietnamese_request("Tôi đi Huế với vợ chồng", TODAY)

    assert parsed.fields["people"] == 2


def test_da_nang_destination_is_kept_and_not_replaced_by_hue() -> None:
    parsed = parse_vietnamese_request("Tôi đi Đà Nẵng 3 ngày 2 đêm, xuất phát Hà Nội, 2 người", TODAY)

    assert parsed.fields["destination"] == "Đà Nẵng"
    assert parsed.fields["origin"] == "Hà Nội"


def test_origin_hue_with_destination_da_nang_keeps_both() -> None:
    parsed = parse_vietnamese_request("xuất phát từ Huế đi Đà Nẵng, 2 người", TODAY)

    assert parsed.fields["origin"] == "Huế"
    assert parsed.fields["destination"] == "Đà Nẵng"


def test_missing_people_is_reported_and_never_invented() -> None:
    parsed = parse_vietnamese_request("Tôi đi Huế 05/12 3 ngày 2 đêm", TODAY)

    assert "people" not in parsed.fields
    assert "people" in parsed.missing_fields
    assert parsed.request is None


def test_empty_text_invents_nothing() -> None:
    parsed = parse_vietnamese_request("xin chào", TODAY)

    assert parsed.fields == {}
    assert parsed.request is None
    assert set(parsed.missing_fields) == {"origin", "destination", "start_date", "end_date", "people"}


def test_rooms_are_extracted_when_stated() -> None:
    parsed = parse_vietnamese_request("đi Huế 05/12, 3 ngày 2 đêm, 2 người, 2 phòng", TODAY)

    assert parsed.fields["rooms"] == 2


def test_with_start_date_fills_only_the_missing_start_and_derives_end() -> None:
    parsed = parse_vietnamese_request(DOD_TEXT, TODAY)

    filled = with_start_date(parsed, date(2026, 12, 5))

    assert filled.request is not None
    assert filled.request.start_date == date(2026, 12, 5)
    assert filled.request.end_date == date(2026, 12, 7)
    assert filled.missing_fields == []


def test_with_start_date_does_not_override_a_start_from_text() -> None:
    parsed = parse_vietnamese_request("xuất phát Hà Nội, đi Huế 05/12 3 ngày 2 đêm 2 người", TODAY)

    filled = with_start_date(parsed, date(2027, 3, 1))

    assert filled.request is not None
    assert filled.request.start_date == date(2026, 12, 5)
