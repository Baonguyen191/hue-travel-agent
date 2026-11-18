"""Test đổi cụm ngày tiếng Việt thành ngày cụ thể.

Quy tắc đang dùng (xem docstring của understanding/dates.py):
- "thứ X này": thứ X gần nhất từ ref trở đi, tính cả ref.
- "thứ X", "thứ X tới", "thứ X sau": thứ X đầu tiên sau ref, không tính ref.
- "cuối tuần này": thứ Bảy gần nhất từ ref trở đi; nếu ref là Chủ nhật thì trả về ref.
- "tuần sau": thứ Hai đầu tiên sau ref.
"""

import datetime as dt

import pytest

from travel_agent.understanding.dates import resolve_date_text

# 2026-11-18 là thứ Tư (ref chính của bộ eval).
WED = dt.date(2026, 11, 18)
SAT = dt.date(2026, 11, 21)
SUN = dt.date(2026, 11, 22)
MON = dt.date(2026, 11, 16)
# 2026-12-20 là Chủ nhật, dùng để test chuyển năm.
DEC_SUN = dt.date(2026, 12, 20)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("hôm nay", dt.date(2026, 11, 18)),
        ("hom nay", dt.date(2026, 11, 18)),
        ("mai", dt.date(2026, 11, 19)),
        ("mai.", dt.date(2026, 11, 19)),
        ("ngày mai", dt.date(2026, 11, 19)),
        ("ngay mai", dt.date(2026, 11, 19)),
        ("ngày kia", dt.date(2026, 11, 20)),
        ("ngay kia", dt.date(2026, 11, 20)),
        ("mốt", dt.date(2026, 11, 20)),
        ("ngày mốt", dt.date(2026, 11, 20)),
        ("ngay mot", dt.date(2026, 11, 20)),
    ],
)
def test_relative_days(text: str, expected: dt.date) -> None:
    assert resolve_date_text(text, WED) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("cuối tuần này", dt.date(2026, 11, 21)),
        ("cuoi tuan nay", dt.date(2026, 11, 21)),
        ("cuối tuần", dt.date(2026, 11, 21)),
        ("cuối tuần sau", dt.date(2026, 11, 28)),
        ("cuối tuần tới", dt.date(2026, 11, 28)),
        ("cuoi tuan toi", dt.date(2026, 11, 28)),
        ("tuần sau", dt.date(2026, 11, 23)),
        ("tuần tới", dt.date(2026, 11, 23)),
        ("tuan sau", dt.date(2026, 11, 23)),
    ],
)
def test_weekend_and_week_from_wednesday(text: str, expected: dt.date) -> None:
    assert resolve_date_text(text, WED) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # Bare, "tới", "sau": thứ Bảy sau ref, không tính hôm nay.
        ("thứ 7", dt.date(2026, 11, 21)),
        ("thứ 7 tới", dt.date(2026, 11, 21)),
        ("thu 7 toi", dt.date(2026, 11, 21)),
        ("thứ bảy tới", dt.date(2026, 11, 21)),
        ("thu 7 sau", dt.date(2026, 11, 21)),
        # "này": gần nhất từ ref trở đi.
        ("thứ 7 này", dt.date(2026, 11, 21)),
        ("thu bay nay", dt.date(2026, 11, 21)),
        ("thứ 5 này", dt.date(2026, 11, 19)),
        ("thứ 6 sau", dt.date(2026, 11, 20)),
        ("thứ 2 tới", dt.date(2026, 11, 23)),
        ("thứ hai", dt.date(2026, 11, 23)),
        ("thứ 2 này", dt.date(2026, 11, 23)),
        ("thứ 4 này", dt.date(2026, 11, 18)),
        ("thứ tư này", dt.date(2026, 11, 18)),
        ("thứ 4", dt.date(2026, 11, 25)),
        ("thứ tư tới", dt.date(2026, 11, 25)),
        ("chủ nhật", dt.date(2026, 11, 22)),
        ("chu nhat nay", dt.date(2026, 11, 22)),
        ("CN", dt.date(2026, 11, 22)),
        ("cn tới", dt.date(2026, 11, 22)),
        ("chủ nhật tới", dt.date(2026, 11, 22)),
    ],
)
def test_weekday_rules_from_wednesday(text: str, expected: dt.date) -> None:
    assert resolve_date_text(text, WED) == expected


def test_weekday_rules_when_ref_is_saturday() -> None:
    assert resolve_date_text("cuối tuần này", SAT) == dt.date(2026, 11, 21)
    assert resolve_date_text("thứ 7", SAT) == dt.date(2026, 11, 28)
    assert resolve_date_text("thứ 7 này", SAT) == dt.date(2026, 11, 21)
    assert resolve_date_text("chủ nhật", SAT) == dt.date(2026, 11, 22)
    assert resolve_date_text("cuối tuần sau", SAT) == dt.date(2026, 11, 28)
    assert resolve_date_text("tuần sau", SAT) == dt.date(2026, 11, 23)
    assert resolve_date_text("mai", SAT) == dt.date(2026, 11, 22)


def test_weekday_rules_when_ref_is_sunday() -> None:
    # Chủ nhật là ref thì "cuối tuần này" là chính ref, tuần sau đến thứ Hai kế tiếp.
    assert resolve_date_text("cuối tuần này", SUN) == dt.date(2026, 11, 22)
    assert resolve_date_text("cuối tuần sau", SUN) == dt.date(2026, 11, 29)
    assert resolve_date_text("chủ nhật này", SUN) == dt.date(2026, 11, 22)
    assert resolve_date_text("chủ nhật", SUN) == dt.date(2026, 11, 29)
    assert resolve_date_text("thứ 7 này", SUN) == dt.date(2026, 11, 28)
    assert resolve_date_text("tuần sau", SUN) == dt.date(2026, 11, 23)
    assert resolve_date_text("thứ 2", SUN) == dt.date(2026, 11, 23)


def test_next_week_from_monday_is_a_week_later() -> None:
    assert resolve_date_text("tuần sau", MON) == dt.date(2026, 11, 23)
    assert resolve_date_text("thứ 2", MON) == dt.date(2026, 11, 23)
    assert resolve_date_text("thứ 2 này", MON) == dt.date(2026, 11, 16)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("20/12", dt.date(2026, 12, 20)),
        ("20-12", dt.date(2026, 12, 20)),
        ("20.12", dt.date(2026, 12, 20)),
        ("20 / 12", dt.date(2026, 12, 20)),
        ("ngày 20/12", dt.date(2026, 12, 20)),
        ("18/11", dt.date(2026, 11, 18)),
        ("17/11", dt.date(2027, 11, 17)),
        ("30/04", dt.date(2027, 4, 30)),
        ("20/12/2026", dt.date(2026, 12, 20)),
        ("20-12-2026", dt.date(2026, 12, 20)),
        ("20/12/2025", dt.date(2025, 12, 20)),
        ("ngày 20 tháng 12", dt.date(2026, 12, 20)),
        ("ngay 20 thang 12", dt.date(2026, 12, 20)),
        ("ngày 20 tháng 12 năm 2026", dt.date(2026, 12, 20)),
        ("ngày 1 tháng 1", dt.date(2027, 1, 1)),
        ("ngày 5 tháng 11", dt.date(2027, 11, 5)),
        ("29/02/2028", dt.date(2028, 2, 29)),
        ("29/02", dt.date(2028, 2, 29)),
    ],
)
def test_numeric_and_word_dates(text: str, expected: dt.date) -> None:
    assert resolve_date_text(text, WED) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("đầu tháng 12", dt.date(2026, 12, 1)),
        ("dau thang 12", dt.date(2026, 12, 1)),
        ("giữa tháng 12", dt.date(2026, 12, 15)),
        ("giua thang 12", dt.date(2026, 12, 15)),
        ("cuối tháng 12", dt.date(2026, 12, 25)),
        ("cuoi thang 12", dt.date(2026, 12, 25)),
        ("đầu tháng 11", dt.date(2027, 11, 1)),
        ("đầu tháng 12 năm 2027", dt.date(2027, 12, 1)),
    ],
)
def test_part_of_month(text: str, expected: dt.date) -> None:
    assert resolve_date_text(text, WED) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("tết dương lịch", dt.date(2027, 1, 1)),
        ("tet duong lich", dt.date(2027, 1, 1)),
        ("giáng sinh", dt.date(2026, 12, 24)),
        ("giang sinh", dt.date(2026, 12, 24)),
        ("noel", dt.date(2026, 12, 24)),
        ("Noël", dt.date(2026, 12, 24)),
    ],
)
def test_fixed_holidays_next_occurrence(text: str, expected: dt.date) -> None:
    assert resolve_date_text(text, WED) == expected


def test_holiday_on_its_own_day_is_that_day() -> None:
    assert resolve_date_text("tết dương lịch", dt.date(2027, 1, 1)) == dt.date(2027, 1, 1)
    assert resolve_date_text("noel", dt.date(2026, 12, 24)) == dt.date(2026, 12, 24)


@pytest.mark.parametrize(
    "text",
    [
        "31/02",
        "31/02/2026",
        "29/02/2027",
        "30/02/2028",
        "0/12",
        "00/12",
        "32/01",
        "12/13",
        "1/0",
        "20/12/0000",
        "20/12/26",
        "đầu tháng 13",
        "đầu tháng 0",
        "ngày 31 tháng 4",
        "99999999999999999999/12",
        "20/12/2026/1",
    ],
)
def test_invalid_dates_return_none(text: str) -> None:
    assert resolve_date_text(text, WED) is None


@pytest.mark.parametrize(
    "text",
    [
        "",
        "   ",
        "đi Huế",
        "asdf",
        "💥",
        "\x00",
        "hôm qua",
        "tuần trước",
        "tháng sau",
        "cuối năm",
        "ngày",
        "thứ 8",
        "thứ 1",
        "chủ",
        "2 ngày",
        "9999/99/99",
        "cuối tuần này sáng",
        "x" * 10000,
    ],
)
def test_unknown_input_returns_none_and_never_raises(text: str) -> None:
    assert resolve_date_text(text, WED) is None


def test_year_rollover_from_december() -> None:
    assert resolve_date_text("20/12", DEC_SUN) == dt.date(2026, 12, 20)
    assert resolve_date_text("19/12", DEC_SUN) == dt.date(2027, 12, 19)
    assert resolve_date_text("ngày 25 tháng 12", DEC_SUN) == dt.date(2026, 12, 25)
    assert resolve_date_text("ngày 5 tháng 12", DEC_SUN) == dt.date(2027, 12, 5)
    assert resolve_date_text("đầu tháng 12", DEC_SUN) == dt.date(2027, 12, 1)
    assert resolve_date_text("giáng sinh", DEC_SUN) == dt.date(2026, 12, 24)
    assert resolve_date_text("giáng sinh", dt.date(2026, 12, 25)) == dt.date(2027, 12, 24)
    assert resolve_date_text("tết dương lịch", DEC_SUN) == dt.date(2027, 1, 1)


def test_relative_dates_cross_new_year() -> None:
    assert resolve_date_text("mai", DEC_SUN) == dt.date(2026, 12, 21)
    assert resolve_date_text("tuần sau", DEC_SUN) == dt.date(2026, 12, 21)
    assert resolve_date_text("cuối tuần này", DEC_SUN) == dt.date(2026, 12, 20)
    assert resolve_date_text("cuối tuần sau", DEC_SUN) == dt.date(2026, 12, 27)
    assert resolve_date_text("thứ 7", DEC_SUN) == dt.date(2026, 12, 26)
    assert resolve_date_text("tết dương lịch", dt.date(2026, 12, 31)) == dt.date(2027, 1, 1)


def test_numeric_date_with_explicit_year_is_not_rolled_forward() -> None:
    assert resolve_date_text("20/12/2025", DEC_SUN) == dt.date(2025, 12, 20)
