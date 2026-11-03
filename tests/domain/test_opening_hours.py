import datetime as dt

import pytest

from travel_agent.domain.opening_hours import parse_opening_hours

MON, WED, SAT, SUN = 0, 2, 5, 6


def t(text: str) -> dt.time:
    return dt.time.fromisoformat(text)


@pytest.mark.parametrize(
    "raw",
    [
        None,
        "",
        "   ",
        "PH off",
        "Mo-Su 07:00-17:00; PH off",
        "Mo-Fr 18:00-02:00",
        "sunrise-sunset",
        'Mo-Su 07:00-17:00 "theo mùa"',
        "Jan-Mar 08:00-17:00",
        "Mo-Su 7:00-17:00",
    ],
)
def test_unsupported_or_missing_is_unknown(raw: str | None) -> None:
    assert parse_opening_hours(raw) is None


def test_every_day_range() -> None:
    hours = parse_opening_hours("Mo-Su 07:00-17:30")
    assert hours is not None
    assert hours.covers(WED, t("08:00"), t("17:30"))
    assert not hours.covers(WED, t("06:30"), t("08:00"))
    assert not hours.covers(WED, t("17:00"), t("18:00"))


def test_split_ranges_and_weekend_rule() -> None:
    hours = parse_opening_hours("Mo-Fr 08:00-11:30,13:30-17:00; Sa,Su 08:00-12:00")
    assert hours is not None
    assert hours.covers(WED, t("09:00"), t("11:00"))
    assert not hours.covers(WED, t("11:00"), t("14:00"))  # vắt qua giờ nghỉ trưa
    assert hours.covers(SAT, t("08:00"), t("12:00"))
    assert not hours.covers(SUN, t("13:00"), t("14:00"))


def test_later_rule_overrides_with_day_off() -> None:
    hours = parse_opening_hours("Mo-Su 08:00-17:00; We off")
    assert hours is not None
    assert not hours.covers(WED, t("09:00"), t("10:00"))
    assert hours.covers(SAT, t("09:00"), t("10:00"))


def test_unmentioned_day_is_closed() -> None:
    hours = parse_opening_hours("Mo-Fr 08:00-17:00")
    assert hours is not None
    assert not hours.covers(SAT, t("09:00"), t("10:00"))


def test_times_without_days_apply_every_day() -> None:
    hours = parse_opening_hours("06:00-22:00")
    assert hours is not None
    assert all(hours.covers(day, t("06:00"), t("22:00")) for day in range(7))


def test_wraparound_day_range() -> None:
    hours = parse_opening_hours("Sa-Mo 09:00-12:00")
    assert hours is not None
    assert hours.covers(SUN, t("09:00"), t("10:00"))
    assert hours.covers(MON, t("09:00"), t("10:00"))
    assert not hours.covers(WED, t("09:00"), t("10:00"))


def test_always_open() -> None:
    hours = parse_opening_hours("24/7")
    assert hours is not None
    assert hours.covers(SUN, t("00:00"), t("23:59"))


def test_closing_at_midnight() -> None:
    hours = parse_opening_hours("Mo-Su 18:00-24:00")
    assert hours is not None
    assert hours.covers(WED, t("22:00"), t("23:59"))
