"""Rule-based Vietnamese trip-request extraction.

Works on `normalize_vietnamese` text, so accents and case do not matter. Preference
phrases keep the spelling from the user's text. A value that cannot be read is never
guessed: it is left out and reported in `missing_fields`.
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any

from pydantic import ValidationError

from app.schemas.parsed_trip import ParsedTrip
from app.schemas.request import TripRequest
from app.services.poi_search import normalize_vietnamese

REQUIRED_FIELDS = ("origin", "destination", "start_date", "end_date", "people")
HUE_NAME = "Huế"
MAX_PREFERENCES = 10

# Normalized city form -> display name. Every Hue spelling maps to the MVP destination.
CITY_NAMES: dict[str, str] = {
    "hue": HUE_NAME,
    "thanh pho hue": HUE_NAME,
    "thua thien hue": HUE_NAME,
    "da nang": "Đà Nẵng",
    "ha noi": "Hà Nội",
    "ho chi minh": "TP. Hồ Chí Minh",
    "tp ho chi minh": "TP. Hồ Chí Minh",
    "sai gon": "TP. Hồ Chí Minh",
    "hoi an": "Hội An",
    "nha trang": "Nha Trang",
    "da lat": "Đà Lạt",
}
_CITY_ALTERNATION = "|".join(re.escape(name) for name in sorted(CITY_NAMES, key=len, reverse=True))
_CITY = f"(?:{_CITY_ALTERNATION})"
_ORIGIN = re.compile(rf"(?:xuat phat(?: tu)?|(?<!\w)tu) (?P<city>{_CITY})(?!\w)")
_DESTINATION = re.compile(rf"(?<!\w)(?:di|den|toi|du lich) (?P<city>{_CITY})(?!\w)")
_HUE = re.compile(r"(?<!\w)(?:thanh pho hue|thua thien hue|hue)(?!\w)")
_DURATION = re.compile(r"(?<!\w)(\d+)\s*ngay(?:\s*(\d+)\s*dem)?(?!\w)")
_DATE = re.compile(r"(?<![\d/])(\d{1,2})/(\d{1,2})(?:/(\d{4}))?(?![\d/])")
_PEOPLE = re.compile(r"(?<!\w)(\d+)\s*(?:nguoi|khach)(?! san)(?!\w)")
_COUPLE = re.compile(r"(?<!\w)(?:hai )?vo chong(?!\w)")
_ROOMS = re.compile(r"(?<!\w)(\d+)\s*phong(?!\w)")
_BUDGET = re.compile(
    r"ngan sach(?: \w+){0,2}? (\d+(?:[.,]\d+)*)\s*(trieu|tr|nghin|ngan|k|dong|d)?(?!\w)"
)
_GROUPED = re.compile(r"\d{1,3}(?:[.,]\d{3})+")
_UNIT_VALUES = {"trieu": 1_000_000, "tr": 1_000_000, "nghin": 1_000, "ngan": 1_000, "k": 1_000, "dong": 1, "d": 1}
_PREFERENCE_TRIGGERS = ("thich", "muon")
_NOT_A_PREFERENCE_AFTER_MUON = frozenset({"di", "den", "toi", "o", "ve", "du", "xem", "tham"})
_CONNECTORS = frozenset({"va", "voi"})
_PUNCTUATION = ".,;:!?()\"'"


def parse_vietnamese_request(text: str, today: date) -> ParsedTrip:
    """Extract every field the text states; return a request only when all required ones are known."""
    clean = _clean(text)
    fields: dict[str, Any] = {}
    notes: list[str] = []
    _extract_places(clean, fields)
    _extract_dates(clean, today, fields, notes)
    _extract_duration(clean, fields)
    _extract_counts(clean, fields)
    _extract_budget(clean, fields, notes)
    _extract_preferences(text, fields)
    derive_end_date(fields)
    return finalize_parsed(fields, notes, "RULES")


def with_start_date(parsed: ParsedTrip, start: date) -> ParsedTrip:
    """Fill a missing start date (for example from a CLI flag) and derive the end from the nights."""
    fields = dict(parsed.fields)
    notes = list(parsed.notes)
    fields.setdefault("start_date", start)
    derive_end_date(fields)
    success = parsed.source if parsed.source.startswith("RULES") else "RULES"
    return finalize_parsed(fields, notes, success)


def finalize_parsed(fields: dict[str, Any], notes: list[str], source: str) -> ParsedTrip:
    """Build the result: a request when every required field is known, else the missing names."""
    _check_end_after_start(fields, notes)
    missing = [name for name in REQUIRED_FIELDS if name not in fields]
    request = None if missing else _build_request(fields, notes)
    return ParsedTrip(
        request=request,
        missing_fields=missing,
        source=source if request is not None else "FORM_FALLBACK",
        fields=fields,
        notes=notes,
    )


def _clean(text: str) -> str:
    """Normalize accents and case, and turn the dot of `TP.` into a space."""
    lowered = re.sub(r"(?<=[a-z])\.", " ", normalize_vietnamese(text))
    return " ".join(lowered.split())


def _blank(text: str, match: re.Match[str]) -> str:
    return text[: match.start()] + " " + text[match.end() :]


def _extract_places(clean: str, fields: dict[str, Any]) -> None:
    origin = _ORIGIN.search(clean)
    if origin is not None:
        fields["origin"] = CITY_NAMES[origin["city"]]
        clean = _blank(clean, origin)
    destination = _DESTINATION.search(clean)
    if destination is not None:
        fields["destination"] = CITY_NAMES[destination["city"]]
        return
    if _HUE.search(clean) is not None:
        fields["destination"] = HUE_NAME


def _safe_date(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _resolve_date(match: re.Match[str], today: date) -> date | None:
    """Explicit year as given; otherwise the next occurrence on or after today."""
    day, month = int(match[1]), int(match[2])
    if match[3] is not None:
        return _safe_date(int(match[3]), month, day)
    candidate = _safe_date(today.year, month, day)
    if candidate is None or candidate >= today:
        return candidate
    return _safe_date(today.year + 1, month, day)


def _extract_dates(clean: str, today: date, fields: dict[str, Any], notes: list[str]) -> None:
    resolved = [_resolve_date(match, today) for match in list(_DATE.finditer(clean))[:2]]
    if resolved and resolved[0] is not None:
        fields["start_date"] = resolved[0]
    if len(resolved) > 1 and resolved[1] is not None:
        fields["end_date"] = resolved[1]
    if any(value is None for value in resolved):
        notes.append("Có ngày không hợp lệ nên đã bỏ qua.")


def _extract_duration(clean: str, fields: dict[str, Any]) -> None:
    match = _DURATION.search(clean)
    if match is None:
        return
    days = int(match[1])
    fields["duration_days"] = days
    fields["nights"] = int(match[2]) if match[2] is not None else days - 1


def derive_end_date(fields: dict[str, Any]) -> None:
    if "end_date" in fields or "start_date" not in fields or "nights" not in fields:
        return
    fields["end_date"] = fields["start_date"] + timedelta(days=fields["nights"])


def _extract_counts(clean: str, fields: dict[str, Any]) -> None:
    people = _PEOPLE.search(clean)
    if people is not None:
        fields["people"] = int(people[1])
    elif _COUPLE.search(clean) is not None:
        fields["people"] = 2
    rooms = _ROOMS.search(clean)
    if rooms is not None:
        fields["rooms"] = int(rooms[1])


def _plain_vnd(number: str) -> int | None:
    """A bare number is VND only when it is at least 100 000; smaller values are ambiguous."""
    digits = re.sub(r"[.,]", "", number) if _GROUPED.fullmatch(number) else number
    if digits.isdigit() and int(digits) >= 100_000:
        return int(digits)
    return None


def _money(number: str, unit: str | None) -> int | None:
    """Convert a budget figure to integer VND; None when the unit makes it ambiguous."""
    if unit is None:
        return _plain_vnd(number)
    if _GROUPED.fullmatch(number):
        return int(re.sub(r"[.,]", "", number)) if unit in ("d", "dong") else None
    try:
        return round(float(number.replace(",", ".")) * _UNIT_VALUES[unit])
    except ValueError:
        return None


def _extract_budget(clean: str, fields: dict[str, Any], notes: list[str]) -> None:
    match = _BUDGET.search(clean)
    if match is None:
        return
    amount = _money(match[1], match[2])
    if amount is None:
        notes.append("Ngân sách chưa rõ đơn vị (triệu, k hoặc đồng); chưa điền.")
        return
    fields["budget_vnd"] = amount


def _word_key(word: str) -> str:
    return normalize_vietnamese(word).strip(_PUNCTUATION)


def _starts_preferences(key: str, following: list[str]) -> bool:
    if key == "thich":
        return True
    return key == "muon" and bool(following) and following[0] not in _NOT_A_PREFERENCE_AFTER_MUON


def _split_phrases(words: list[str]) -> list[str]:
    """Split the words after `thích` on commas, `và` and `với`, up to the next `.` or `;`."""
    phrases: list[str] = []
    current: list[str] = []
    for word in words:
        token = word.strip(_PUNCTUATION)
        if token and _word_key(token) not in _CONNECTORS:
            current.append(token)
        boundary = _word_key(token) in _CONNECTORS or word.endswith(",")
        if boundary and current:
            phrases.append(" ".join(current))
            current = []
        if word.endswith((".", ";")):
            break
    if current:
        phrases.append(" ".join(current))
    return list(dict.fromkeys(phrases))[:MAX_PREFERENCES]


def _extract_preferences(text: str, fields: dict[str, Any]) -> None:
    words = text.split()
    keys = [_word_key(word) for word in words]
    for index, key in enumerate(keys):
        if not _starts_preferences(key, keys[index + 1 : index + 2]):
            continue
        phrases = _split_phrases(words[index + 1 :])
        if phrases:
            fields["preferences"] = phrases
        return


def _check_end_after_start(fields: dict[str, Any], notes: list[str]) -> None:
    start, end = fields.get("start_date"), fields.get("end_date")
    if start is not None and end is not None and end < start:
        del fields["end_date"]
        notes.append("Ngày kết thúc không được trước ngày bắt đầu; chưa điền ngày kết thúc.")


def _build_request(fields: dict[str, Any], notes: list[str]) -> TripRequest | None:
    payload = {name: value for name, value in fields.items() if name in TripRequest.model_fields}
    try:
        return TripRequest(**payload)
    except ValidationError as error:
        notes.append(f"Thông tin chưa hợp lệ: {error.errors()[0]['msg']}")
        return None
