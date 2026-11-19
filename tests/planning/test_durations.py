"""Thời lượng tham quan lấy từ thuộc tính DB. Dạng số nguyên là dạng thật có trong hue.sqlite."""

import pytest

from tests.planning.factories import make_place
from travel_agent.domain.models import Category, Place
from travel_agent.planning.durations import (
    MAX_VISIT_MINUTES,
    MIN_VISIT_MINUTES,
    VISIT_ATTRIBUTE,
    parse_visit_minutes,
    visit_minutes,
)
from travel_agent.planning.solver import VISIT_MINUTES


def with_attribute(category: Category, raw: str | None) -> Place:
    place = make_place("t:x", category)
    if raw is None:
        return place
    return place.model_copy(update={"attributes": {VISIT_ATTRIBUTE: raw}})


# Dạng thật: toàn bộ 1.000 giá trị trong data/hue.sqlite là số nguyên dạng chuỗi.
@pytest.mark.parametrize(
    ("raw", "minutes"),
    [("60", 60), ("120", 120), ("90", 90), ("30", 30), ("300", 300), ("600", 600), ("45", 45)],
)
def test_real_integer_strings_parse_to_minutes(raw: str, minutes: int) -> None:
    assert parse_visit_minutes(raw) == minutes


@pytest.mark.parametrize(
    ("raw", "minutes"),
    [
        ("60 phút", 60),
        ("2 giờ", 120),
        ("1,5 giờ", 90),
        ("1 giờ 30 phút", 90),
        ("90–120", 105),  # khoảng: lấy trung điểm
        ("90-120 phút", 105),
        ("1-2 giờ", 90),
        ("  75  ", 75),
    ],
)
def test_common_variants_parse(raw: str, minutes: int) -> None:
    assert parse_visit_minutes(raw) == minutes


@pytest.mark.parametrize("raw", [None, "", "   ", "abc", "0", "-5", "0 phút", "2 ngày", "1-"])
def test_unparseable_or_non_positive_values_return_none(raw: str | None) -> None:
    assert parse_visit_minutes(raw) is None


def test_database_attribute_wins_over_model_minutes() -> None:
    place = with_attribute(Category.ATTRACTION, "120")
    assert visit_minutes(place, 45) == 120


def test_database_attribute_is_clamped_to_the_allowed_range() -> None:
    long = with_attribute(Category.ATTRACTION, "600")  # dữ liệu thật có 600, 480, 380...
    short = with_attribute(Category.CAFE, "10")
    assert visit_minutes(long, 60) == MAX_VISIT_MINUTES
    assert visit_minutes(short, 60) == MIN_VISIT_MINUTES


def test_model_minutes_are_used_when_attribute_missing_or_unparseable() -> None:
    assert visit_minutes(with_attribute(Category.MUSEUM, None), 50) == 50
    assert visit_minutes(with_attribute(Category.MUSEUM, "không rõ"), 50) == 50


def test_category_constant_when_nothing_else_is_usable() -> None:
    assert visit_minutes(with_attribute(Category.MUSEUM, None), 0) == VISIT_MINUTES[Category.MUSEUM]
    assert visit_minutes(with_attribute(Category.CAFE, "0"), -10) == VISIT_MINUTES[Category.CAFE]
