"""Read a slot answer: the values a message gives, the optional slots it settles, and fallbacks.

Recognition runs on the folded message (`normalize_vietnamese`) and matches whole words only.
Concrete values (transport, stay, pace) are read from any message while the draft is filling,
so an early answer fills its slot and it is never asked. An optional slot asked in the last
question turn and still open is settled by the next message: a recognised value, or "any"
(cheapest or default later). Required slots keep their fallbacks for values the understanding
layer missed.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from app.chat.draft import OPTIONAL_UNITS, REQUIRED_UNITS, UNIT_KEYS, settled, skipped
from app.services.poi_search import normalize_vietnamese
from app.services.preferences import map_themes
from app.understanding.normalize import parse_budget_vnd
from app.understanding.understand import _map_interest_phrases

ANY = "any"
# Value phrases per optional unit (folded). The first value whose phrase matches wins.
_VALUE_PHRASES: dict[str, dict[str, tuple[str, ...]]] = {
    "transport": {
        "bus": ("xe giuong nam", "xe khach", "bus", "xe"),
        "train": ("tau hoa", "tau lua", "tau"),
        "flight": ("may bay", "bay"),
    },
    "stay": {
        "homestay": ("homestay",),
        "hotel": ("khach san", "ks", "hotel"),
        "resort": ("resort",),
    },
    "pace": {
        "relaxed": ("thong tha", "nhe nhang", "cham"),
        "moderate": ("vua", "vua phai", "binh thuong"),
        # Not bare "day": it is also "đây" (here) once diacritics are stripped.
        "packed": ("di nhieu", "nhieu diem", "lich day", "day dac", "day lich", "kin"),
    },
}
_PUNCTUATION = re.compile(r"[^a-z0-9]+")
_HERE = re.compile(r"\bo day\b")  # "ở đây" (here) must not read as the pace word "đây"
_TIME_WORDS = frozenset(
    {"ngay", "mai", "hom", "dem", "tuan", "thang", "nam", "sang", "chieu", "nay", "trieu", "nguoi",
     "tuy", "khong", "co", "ok", "yes", "toi", "tu"}
)
_FROM_PREFIXES = (("xuat", "phat", "tu"), ("di", "tu"), ("tu",))
_DATE_FIELDS = ("start_date", "num_days", "duration_days")
_PHRASE_SPLIT = re.compile(r"[,;]|\s+và\s+|\s+va\s+", re.IGNORECASE)
_PACE_ORDER = ("relaxed", "moderate", "packed")
# Folded phrases that move the pace one step (S5): more stops, or fewer stops.
# Not bare "thêm điểm": "thêm điểm Đại Nội" asks for a place, not a faster pace.
_PACE_UP = ("them so luong diem", "them vai diem", "them diem den", "nhieu diem hon", "di nhieu hon")
_PACE_DOWN = ("bot diem", "it diem hon", "thong tha hon")
# Folded words that keep the current budget after the early budget check (budget_ok).
_KEEP_BUDGET_PHRASES = ("giu", "ok", "duoc", "khong", "van", "thoi", "tiet kiem")
# "tăng ngân sách" with no amount: the next question asks for the new amount instead of
# repeating the warning.
_RAISE_BUDGET_PHRASES = ("tang", "nang", "them tien", "them ngan sach", "cao hon")


def proper_name(name: str) -> str:
    """"Hà nội" → "Hà Nội": a place name with every word capitalised, other letters kept."""
    return " ".join(word[:1].upper() + word[1:] for word in name.split())


def value_of(unit: str, text: str) -> str | None:
    """The value a message names for an optional unit (transport, stay or pace), or None."""
    # Punctuation ends a word too ("đi tàu, ở resort" has "tau" before a comma).
    folded = _PUNCTUATION.sub(" ", normalize_vietnamese(text))
    if unit == "pace":
        folded = _HERE.sub(" ", folded)
    padded = f" {folded} "
    for value, phrases in _VALUE_PHRASES[unit].items():
        if any(f" {phrase} " in padded for phrase in phrases):
            return value
    return None


def pace_step(text: str) -> int:
    """+1 for "thêm số lượng điểm" (one pace step up), -1 for "bớt điểm" (one step down), 0 otherwise."""
    padded = f" {_PUNCTUATION.sub(' ', normalize_vietnamese(text))} "
    if any(f" {phrase} " in padded for phrase in _PACE_UP):
        return 1
    if any(f" {phrase} " in padded for phrase in _PACE_DOWN):
        return -1
    return 0


def _stepped_pace(current: Any, step: int) -> str:
    """One step from the current pace; "any" and a missing pace count as moderate, and the ends stay put."""
    index = _PACE_ORDER.index(current) if current in _PACE_ORDER else 1
    return _PACE_ORDER[min(max(index + step, 0), len(_PACE_ORDER) - 1)]


def origin_from(text: str, fields: Mapping[str, Any]) -> str | None:
    """A short place answer ("Hà Nội", "từ Đà Nẵng") when the message is not a date or a number."""
    if any(fields.get(name) is not None for name in _DATE_FIELDS) or re.search(r"\d", text):
        return None
    words = text.strip(" .,!?").split()
    folded = [normalize_vietnamese(word) for word in words]
    for prefix in _FROM_PREFIXES:
        if len(words) > len(prefix) and tuple(folded[: len(prefix)]) == prefix:
            words, folded = words[len(prefix) :], folded[len(prefix) :]
            break
    if not words or len(words) > 4 or _TIME_WORDS.intersection(folded):
        return None
    return " ".join(word[:1].upper() + word[1:] for word in words)


def interests_from(text: str) -> tuple[list[str], list[str]]:
    """(categories, themes) of the comma- or "và"-separated interest phrases in a message."""
    phrases = [part.strip() for part in _PHRASE_SPLIT.split(text) if part and part.strip()]
    categories, _ = _map_interest_phrases(phrases)
    return [str(category) for category in categories], map_themes(phrases)


def take_answers(draft: dict[str, Any], text: str, fields: Mapping[str, Any]) -> dict[str, Any]:
    """The draft after a slot answer: values read from the message, then the last asked units settled."""
    answered = dict(draft)
    step = pace_step(text)
    for unit in UNIT_KEYS:
        if unit == "pace" and step:
            answered["pace"] = _stepped_pace(answered.get("pace"), step)
            continue
        value = value_of(unit, text)
        if value is not None:
            answered[UNIT_KEYS[unit]] = value
    last_asked = list(answered.get("last_asked", []))
    for unit in last_asked:
        if unit == "places":
            answered["places_done"] = True
        elif unit in UNIT_KEYS and not settled(unit, answered) and not skipped(unit, answered):
            answered[UNIT_KEYS[unit]] = ANY
    if "budget_ok" in last_asked:
        _answer_budget_check(answered, text)
    for unit in last_asked:
        if unit not in REQUIRED_UNITS or settled(unit, answered):
            continue
        if unit == "budget":
            amount = parse_budget_vnd(text)
            if amount is not None:
                answered["budget_vnd"] = amount
        elif unit == "interests":
            categories, themes = interests_from(text)
            answered["categories"] = _unique([*answered.get("categories", []), *categories])
            answered["themes"] = _unique([*answered.get("themes", []), *themes])
        elif unit == "origin":
            origin = origin_from(text, fields)
            if origin is not None:
                answered["origin"] = proper_name(origin)
    return answered


def _answer_budget_check(answered: dict[str, Any], text: str) -> None:
    """A new amount becomes the budget (the check re-runs); the current amount or a keep word accepts it.

    Anything else leaves the check open, so the question is asked again.
    """
    current = answered.get("budget_vnd")
    amount = parse_budget_vnd(text)
    if amount is not None and amount != current:
        answered["budget_vnd"] = amount
        answered.pop("budget_accepted", None)
        answered.pop("budget_raise", None)
        return
    padded = f" {_PUNCTUATION.sub(' ', normalize_vietnamese(text))} "
    if amount is None and any(f" {phrase} " in padded for phrase in _RAISE_BUDGET_PHRASES):
        answered["budget_raise"] = True
        return
    if amount == current or any(f" {phrase} " in padded for phrase in _KEEP_BUDGET_PHRASES):
        answered["budget_accepted"] = True
        answered.pop("budget_raise", None)


def _unique(values: list[Any]) -> list[Any]:
    result: list[Any] = []
    for value in values:
        if value not in result:
            result.append(value)
    return result
