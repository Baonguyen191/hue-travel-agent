"""Vietnamese text helpers for query understanding: folding, day counts and budget amounts.

Pure functions: no network, and they never raise on odd input. Inputs are folded with the
app's `normalize_vietnamese` (lower case, no diacritics, đ -> d).
"""

from __future__ import annotations

import re

from app.services.poi_search import normalize_vietnamese
from app.understanding.models import DurationSpec

_UNIT_VND: dict[str, int] = {
    "trieu": 1_000_000,
    "tr": 1_000_000,
    "cu": 1_000_000,
    "nghin": 1_000,
    "ngan": 1_000,
    "k": 1_000,
    "dong": 1,
    "d": 1,
}
# Spoken numbers after folding. Durations use 1..7 (a trip is at most 7 days); budgets use 1..10.
_NUMBER_WORDS: dict[str, int] = {"mot": 1, "hai": 2, "ba": 3, "bon": 4, "nam": 5, "sau": 6, "bay": 7}
_BUDGET_WORDS: dict[str, int] = {**_NUMBER_WORDS, "tam": 8, "chin": 9, "muoi": 10}
_NUMBER = r"(\d+|mot|hai|ba|bon|nam|sau|bay)"
# "2 ngày", "3 hôm"; "đêm" is not counted because the day count already covers the trip.
_DAY_RE = re.compile(rf"(?<![a-z0-9]){_NUMBER}\s*(?:ngay|hom)(?![a-z0-9])")
# "2n1đ" folds to "2n1d".
_NIGHTS_RE = re.compile(r"(?<![a-z0-9])(\d+)\s*n\s*\d+\s*d(?![a-z0-9])")
_HALF_DAY_RE = re.compile(r"(?<![a-z0-9])(?:nua ngay|nua buoi|(?:mot|1)\s*buoi)(?![a-z0-9])")
_BUDGET_RE = re.compile(
    r"(?<![a-z0-9.,])(\d+(?:[.,]\d+)*|mot|hai|ba|bon|nam|sau|bay|tam|chin|muoi)"
    r"\s*(trieu|tr|cu|nghin|ngan|k|dong|d)?(\s*ruoi)?(?![a-z0-9])"
)
_GROUPED = re.compile(r"\d{1,3}(?:[.,]\d{3})+")
_DECIMAL = re.compile(r"\d+(?:\.\d+)?")
_PLAIN_VND_MIN = 100_000


def strip_diacritics(text: str) -> str:
    """Fold Vietnamese text: no diacritics, lower case, single spaces. "Đại Nội" -> "dai noi"."""
    return normalize_vietnamese(text)


def _to_number(token: str) -> int:
    if token.isdigit():
        return int(token)
    return _NUMBER_WORDS[token]


def parse_duration(text: str) -> DurationSpec | None:
    """Read the number of days from a phrase. None when there is no duration.

    "2 ngày 1 đêm" -> 2 days; "2n1đ" -> 2 days; "nửa ngày" -> 1 day, half_day.
    Zero is skipped. The 1..7 limit is enforced by the planner, not here.
    """
    normalized = strip_diacritics(text)
    for match in _DAY_RE.finditer(normalized):
        days = _to_number(match.group(1))
        if days >= 1:
            return DurationSpec(num_days=days)
    for match in _NIGHTS_RE.finditer(normalized):
        days = int(match.group(1))
        if days >= 1:
            return DurationSpec(num_days=days)
    if _HALF_DAY_RE.search(normalized):
        return DurationSpec(num_days=1, half_day=True)
    return None


def _number_value(token: str) -> float | None:
    """Numeric value of a budget token; grouped thousands ("3.000") are not a value here."""
    if token in _BUDGET_WORDS:
        return float(_BUDGET_WORDS[token])
    if _GROUPED.fullmatch(token):
        return None
    if _DECIMAL.fullmatch(token.replace(",", ".")):
        return float(token.replace(",", "."))
    return None


def _plain_vnd(number: str) -> int | None:
    """A bare amount is VND only when it is at least 100 000; smaller bare numbers are ambiguous."""
    digits = re.sub(r"[.,]", "", number) if _GROUPED.fullmatch(number) else number
    if not digits.isdigit() or int(digits) < _PLAIN_VND_MIN:
        return None
    return int(digits)


def _budget_amount(number: str, unit: str | None, half: bool) -> int | None:
    if unit is None or unit in ("dong", "d"):
        return _plain_vnd(number) if unit is None else _grouped_vnd(number)
    value = _number_value(number)
    if value is None:
        return None
    if half:
        value += 0.5
    return round(value * _UNIT_VND[unit])


def _grouped_vnd(number: str) -> int | None:
    """An amount with an explicit đồng unit: "3.000.000 đồng" or "500 đồng"."""
    digits = re.sub(r"[.,]", "", number) if _GROUPED.fullmatch(number) else number
    return int(digits) if digits.isdigit() else None


def parse_budget_vnd(text: str) -> int | None:
    """Read a budget in VND from a phrase such as "5 triệu", "5tr", "500k" or "hai triệu rưỡi".

    Returns the first amount that has a clear unit. None when the phrase has no amount or the
    unit is missing and the number is too small to be VND.
    """
    for match in _BUDGET_RE.finditer(strip_diacritics(text)):
        number, unit, half = match.group(1), match.group(2), match.group(3)
        amount = _budget_amount(number, unit, half is not None)
        if amount is not None:
            return amount
    return None
