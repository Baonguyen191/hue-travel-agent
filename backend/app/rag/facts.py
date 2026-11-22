"""Checks the facts an LLM place answer states against the cited POIs.

Checked: clock times (HH:MM, HHhMM), prices with a unit (đ, đồng, vnd, k, nghìn, ngàn), phone
numbers and the text after "địa chỉ". Durations ("2 giờ") and distances are not facts here. A fact
in a sentence is checked against the POIs cited in that sentence, or against every cited POI when
the sentence cites none. A fact passes when it matches at least one of those POIs.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from app.rag.index import PHONE_KEY
from app.schemas.place import Place
from app.services.poi_search import normalize_vietnamese

CITE_RE = re.compile(r"\[([^\[\]\s]+:[^\[\]\s]+)\]")
_TIME = re.compile(r"(?<![\d.,])([01]?\d|2[0-3])\s*[:h]\s*([0-5]\d)(?!\d)")
_PRICE = re.compile(
    r"(?<![\d.,])(\d{1,3}(?:[.,]\d{3})+|\d+)\s*(nghìn|ngàn|đồng|vnđ|vnd|đ|k)(?![a-zA-Zà-ỹÀ-Ỹ])",
    re.IGNORECASE,
)
_PHONE = re.compile(r"(?<!\d)(?:\+\s*84|84|0)(?:[\s.-]?\d){8,11}(?!\d)")
_ADDRESS = re.compile(r"địa chỉ\s*(?:là|:)?\s*([^\[\n;]+?)(?=\s*\[|[.;\n]|$)", re.IGNORECASE)
_SENTENCE = re.compile(r"(?<=[.!?])\s+|\n+")
_WORD = re.compile(r"[a-z0-9]+")
ADDRESS_OVERLAP = 0.6


@dataclass(frozen=True)
class FactMismatch:
    poi_id: str
    kind: Literal["time", "price", "phone", "address"]
    value: str


def _times(text: str | None) -> set[tuple[int, int]]:
    return {(int(h), int(m)) for h, m in _TIME.findall(text or "")}


def _phones(text: str | None) -> set[str]:
    """Phone numbers as local digits: '(+84) 91 648 22 71' -> '0916482271', '(+84) 0234 3824 399' -> '02343824399'."""
    cleaned = re.sub(r"[ \t]+", " ", (text or "").replace("(", " ").replace(")", " "))
    found = set()
    for match in _PHONE.findall(cleaned):
        digits = re.sub(r"\D", "", match)
        if digits.startswith("84"):
            rest = digits[2:]
            digits = rest if rest.startswith("0") else "0" + rest
        found.add(digits)
    return found


def _price_value(number: str, unit: str) -> int:
    value = int(re.sub(r"[.,]", "", number))
    return value * 1000 if unit.lower() in {"k", "nghìn", "ngàn"} else value


def _price_ok(value: int, place: Place) -> bool:
    low, high = place.price_min_vnd, place.price_max_vnd
    if low is None:
        return value == 0 and place.is_free_claim
    return low <= value <= (high if high is not None else low)


def _address_ok(found: str, place: Place) -> bool:
    words = set(_WORD.findall(normalize_vietnamese(found)))
    if not words:
        return True
    known = set(_WORD.findall(normalize_vietnamese(place.address or "")))
    return len(words & known) / len(words) >= ADDRESS_OVERLAP


def check_facts(answer: str, places: Sequence[Place]) -> list[FactMismatch]:
    by_id = {place.id: place for place in places}
    mismatches: list[FactMismatch] = []
    for sentence in _SENTENCE.split(answer):
        cited = [by_id[i] for i in CITE_RE.findall(sentence) if i in by_id]
        targets = cited or list(places)
        if not targets:
            continue
        label = targets[0].id if len(targets) == 1 else ""
        body = CITE_RE.sub(" ", sentence)
        for hour, minute in sorted(_times(body)):
            if not any((hour, minute) in _times(p.opening_hours_raw) for p in targets):
                mismatches.append(FactMismatch(label, "time", f"{hour:02d}:{minute:02d}"))
        for number, unit in _PRICE.findall(body):
            if not any(_price_ok(_price_value(number, unit), p) for p in targets):
                mismatches.append(FactMismatch(label, "price", f"{number}{unit}"))
        for phone in sorted(_phones(body)):
            if not any(phone in _phones(str(p.raw_attributes.get(PHONE_KEY) or "")) for p in targets):
                mismatches.append(FactMismatch(label, "phone", phone))
        for found in _ADDRESS.findall(body):
            if not any(_address_ok(found, p) for p in targets):
                mismatches.append(FactMismatch(label, "address", found.strip()))
    return mismatches
