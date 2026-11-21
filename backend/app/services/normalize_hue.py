"""Safe field extraction for Hue POI source records.

These functions preserve uncertainty. They do not manufacture a price unit,
opening-day schedule, or missing duration.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any

from app.schemas.place import Place

ADDRESS_KEY = "Địa chỉ"
RATING_KEY = "Đánh giá"
VISIT_MINUTES_KEY = "Thời gian trải nghiệm TB (phút)"
PRICE_KEY = "Giá tham khảo (theo nguồn)"
FREE_KEY = "Miễn phí"
SUMMARY_KEY = "Tóm tắt"
PHOTO_KEY = "Ảnh đại diện"
SOURCE_URL_KEY = "Trang nguồn"

_RATING_PATTERN = re.compile(
    r"(?P<value>\d+(?:[.,]\d+)?)\s*/\s*5(?:\s*\((?P<details>[^)]*)\))?",
    re.IGNORECASE,
)
_COUNT_PATTERN = re.compile(r"(?P<count>[\d.,]+)\s*lượt", re.IGNORECASE)
_INTEGER_PATTERN = re.compile(r"\d+")
_VND_NUMBER_PATTERN = re.compile(r"(?<!\d)(\d{1,3}(?:[.,]\d{3})+|\d+)(?:\s*(?:đ|vnđ|vnd))?", re.I)


def optional_text(value: object) -> str | None:
    """Return a stripped source string, treating empty values as absent."""
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None


def parse_rating(value: object) -> tuple[float | None, int | None, str | None]:
    """Parse the documented rating format without assuming a rating provider."""
    text = optional_text(value)
    if text is None:
        return None, None, None
    match = _RATING_PATTERN.search(text)
    if match is None:
        return None, None, None
    rating_value = float(match.group("value").replace(",", "."))
    if not 0 <= rating_value <= 5:
        return None, None, None

    details = match.group("details") or ""
    count_match = _COUNT_PATTERN.search(details)
    rating_count = None
    if count_match:
        rating_count = int(re.sub(r"[.,]", "", count_match.group("count")))

    rating_source = None
    if "," in details:
        rating_source = optional_text(details.split(",", 1)[1])
    return rating_value, rating_count, rating_source


def parse_visit_minutes(value: object) -> int | None:
    """Parse a positive source duration in minutes, leaving malformed data unset."""
    text = optional_text(value)
    if text is None or not re.fullmatch(r"\d+", text):
        return None
    minutes = int(text)
    return minutes if minutes > 0 else None


def _vnd_numbers(value: str) -> list[int]:
    numbers: list[int] = []
    for match in _VND_NUMBER_PATTERN.finditer(value):
        number_text = match.group(1)
        normalized = re.sub(r"[.,]", "", number_text)
        numbers.append(int(normalized))
    return numbers


def parse_reference_price_range(value: object) -> tuple[int | None, int | None, str | None]:
    """Extract a VND reference range and keep the unspecified pricing unit UNKNOWN."""
    text = optional_text(value)
    if text is None:
        return None, None, None
    numbers = _vnd_numbers(text)
    if not numbers or len(numbers) > 2:
        return None, None, None
    minimum, maximum = min(numbers), max(numbers)
    return minimum, maximum, "UNKNOWN"


def parse_attributes(value: object) -> dict[str, Any]:
    """Parse an attributes object safely; malformed values remain an empty mapping."""
    if isinstance(value, Mapping):
        return dict(value)
    if not isinstance(value, str):
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def normalize_place(row: Mapping[str, Any]) -> Place:
    """Map one SQLite row to the PHASE 1 API contract."""
    attributes = parse_attributes(row["attributes_json"])
    rating_value, rating_count, rating_source = parse_rating(attributes.get(RATING_KEY))
    price_min_vnd, price_max_vnd, price_unit = parse_reference_price_range(
        attributes.get(PRICE_KEY)
    )
    is_free_claim = optional_text(attributes.get(FREE_KEY)) == "có"

    if price_min_vnd is not None:
        price_status = "REFERENCE_RANGE"
    elif is_free_claim:
        price_status = "FREE_CLAIM"
        price_unit = "UNKNOWN"
    else:
        price_status = "UNKNOWN"

    opening_hours_raw = optional_text(row["opening_hours_raw"])
    return Place(
        id=row["id"],
        name=row["name"],
        category=row["category"],
        lat=row["lat"],
        lon=row["lon"],
        address=optional_text(attributes.get(ADDRESS_KEY)),
        rating_value=rating_value,
        rating_count=rating_count,
        rating_source=rating_source,
        opening_hours_raw=opening_hours_raw,
        opening_hours_confidence="UNVERIFIED" if opening_hours_raw else "UNKNOWN",
        visit_minutes=parse_visit_minutes(attributes.get(VISIT_MINUTES_KEY)),
        price_min_vnd=price_min_vnd,
        price_max_vnd=price_max_vnd,
        price_unit=price_unit,
        price_status=price_status,
        is_free_claim=is_free_claim,
        summary=optional_text(attributes.get(SUMMARY_KEY)),
        photo_url=optional_text(attributes.get(PHOTO_KEY)),
        source=row["source"],
        source_url=optional_text(attributes.get(SOURCE_URL_KEY)),
        source_place_id=row["source_place_id"],
        collected_at=row["collected_at"],
        raw_attributes=attributes,
    )
