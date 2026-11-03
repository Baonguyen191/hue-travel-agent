"""Parser cho một tập con cú pháp OSM `opening_hours`.

Nguyên tắc: không hiểu chắc chắn thì trả None (unknown). Không bao giờ đoán giờ mở cửa.
Hỗ trợ: "24/7", "Mo-Fr 08:00-17:00", "Sa,Su 08:00-11:30,13:30-17:00", "We off",
"06:00-22:00" (mọi ngày), nhiều rule nối bằng ";" (rule sau ghi đè rule trước).
Không hỗ trợ (trả None): ngày lễ PH/SH, khung giờ qua nửa đêm, tháng/tuần, comment.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass

WEEKDAY_CODES = ("Mo", "Tu", "We", "Th", "Fr", "Sa", "Su")
_ALL_DAYS = tuple(range(7))
_RANGE_RE = re.compile(r"^(\d{2}):(\d{2})-(\d{2}):(\d{2})$")


@dataclass(frozen=True)
class TimeRange:
    start: dt.time
    end: dt.time


@dataclass(frozen=True)
class WeeklyHours:
    """Key = weekday (0 = thứ Hai, như `date.weekday()`). Ngày không có key = đóng cửa."""

    by_weekday: dict[int, tuple[TimeRange, ...]]

    def covers(self, weekday: int, start: dt.time, end: dt.time) -> bool:
        ranges = self.by_weekday.get(weekday, ())
        return any(r.start <= start and end <= r.end for r in ranges)


def parse_opening_hours(raw: str | None) -> WeeklyHours | None:
    if raw is None:
        return None
    text = raw.strip()
    if not text:
        return None
    if text == "24/7":
        always = (TimeRange(dt.time(0, 0), dt.time.max),)
        return WeeklyHours({day: always for day in _ALL_DAYS})
    by_weekday: dict[int, tuple[TimeRange, ...]] = {}
    for rule in text.split(";"):
        rule_text = rule.strip()
        if not rule_text:
            continue
        parsed = _parse_rule(rule_text)
        if parsed is None:
            return None
        days, ranges = parsed
        for day in days:
            by_weekday[day] = ranges
    if not by_weekday:
        return None
    return WeeklyHours(by_weekday)


def _parse_rule(rule: str) -> tuple[tuple[int, ...], tuple[TimeRange, ...]] | None:
    days: tuple[int, ...] | None
    if rule[0].isdigit():
        days, times_text = _ALL_DAYS, rule
    else:
        day_spec, _, rest = rule.partition(" ")
        days, times_text = _parse_days(day_spec), rest.strip()
    if days is None or not times_text:
        return None
    if times_text in ("off", "closed"):
        return days, ()
    ranges: list[TimeRange] = []
    for chunk in times_text.split(","):
        time_range = _parse_range(chunk.strip())
        if time_range is None:
            return None
        ranges.append(time_range)
    return days, tuple(ranges)


def _parse_days(spec: str) -> tuple[int, ...] | None:
    days: list[int] = []
    for part in spec.split(","):
        first, sep, last = part.partition("-")
        if first not in WEEKDAY_CODES or (sep and last not in WEEKDAY_CODES):
            return None
        start = WEEKDAY_CODES.index(first)
        if not sep:
            days.append(start)
            continue
        end = WEEKDAY_CODES.index(last)
        if start <= end:
            days.extend(range(start, end + 1))
        else:  # vòng qua cuối tuần, ví dụ "Sa-Mo"
            days.extend([*range(start, 7), *range(0, end + 1)])
    return tuple(days)


def _parse_range(text: str) -> TimeRange | None:
    match = _RANGE_RE.match(text)
    if match is None:
        return None
    h1, m1, h2, m2 = (int(group) for group in match.groups())
    if h1 > 23 or m1 > 59 or h2 > 24 or m2 > 59:
        return None
    start = dt.time(h1, m1)
    if h2 == 24:
        if m2 != 0:
            return None
        end = dt.time.max
    else:
        end = dt.time(h2, m2)
    if end <= start:
        return None  # khung qua nửa đêm: chưa hỗ trợ -> unknown
    return TimeRange(start, end)
