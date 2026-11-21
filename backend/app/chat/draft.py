"""Merge understood messages into the plan draft, and build the TripRequest from it.

The draft holds only what the user stated or confirmed. Defaults (origin Huế, 1 person) are
written into the draft only by `confirm_defaults`, and `build_request` refuses to build while a
default is unconfirmed, so a plan never starts on a guessed origin or party size.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date, timedelta
from typing import Any

from app.schemas.request import TripRequest
from app.understanding.models import ParsedQuery
from app.understanding.understand import DEFAULT_ORIGIN, DEFAULT_PEOPLE, MAX_DAYS, QUICK_DAYS, QUICK_START

HUE = "Huế"
_MAX_PREFERENCES = 10
_SCALAR_FIELDS = ("origin", "people", "rooms", "budget_vnd", "num_days")
_DEFAULTABLE = ("origin", "people")


def merge_draft(draft: dict[str, Any], parsed: ParsedQuery) -> dict[str, Any]:
    """Return the draft with the values stated in `parsed` added; stated scalars overwrite."""
    merged = dict(draft)
    fields = parsed.fields
    for name in _SCALAR_FIELDS:
        if fields.get(name) is not None:
            merged[name] = fields[name]
    if fields.get("start_date") is not None:
        merged["start_date"] = fields["start_date"].isoformat()
    _extend(merged, "categories", fields.get("categories", []))
    _extend(merged, "exclude_categories", fields.get("exclude_categories", []))
    _extend(merged, "preferences", parsed.soft_preferences)
    _extend(merged, "must_include_poi_ids", [m.poi_id for m in parsed.must_include if m.poi_id])
    _extend(merged, "exclude_poi_ids", [m.poi_id for m in parsed.exclude if m.poi_id])
    return merged


def _extend(draft: dict[str, Any], key: str, values: Iterable[Any]) -> None:
    current = list(draft.get(key, []))
    for value in values:
        if value not in current:
            current.append(value)
    if key == "preferences":
        current = current[:_MAX_PREFERENCES]
    draft[key] = current


def missing_question(draft: dict[str, Any]) -> tuple[str, tuple[str, ...]] | None:
    """A Vietnamese question and quick replies when the start date or the length is unknown."""
    days = draft.get("num_days")
    if days is not None and days > MAX_DAYS:
        return (f"Mình chỉ lên lịch tối đa {MAX_DAYS} ngày. Bạn muốn đi mấy ngày?", QUICK_DAYS)
    if draft.get("start_date") is None and days is None:
        return ("Bạn muốn đi Huế từ ngày nào và đi mấy ngày?", QUICK_START)
    if draft.get("start_date") is None:
        return ("Bạn muốn đi Huế từ ngày nào?", QUICK_START)
    if days is None:
        return ("Bạn định đi Huế mấy ngày?", QUICK_DAYS)
    return None


def missing_defaults(draft: dict[str, Any]) -> list[str]:
    """Origin and party size the user has not stated or confirmed yet."""
    return [name for name in _DEFAULTABLE if draft.get(name) is None]


def confirm_defaults(draft: dict[str, Any]) -> dict[str, Any]:
    """Write the default origin and party size into the draft as confirmed values."""
    confirmed = dict(draft)
    if confirmed.get("origin") is None:
        confirmed["origin"] = DEFAULT_ORIGIN
    if confirmed.get("people") is None:
        confirmed["people"] = DEFAULT_PEOPLE
    return confirmed


def build_request(draft: dict[str, Any]) -> TripRequest:
    """The TripRequest of a complete, confirmed draft; raises ValueError while a default is open."""
    if missing_defaults(draft):
        raise ValueError("origin and people must be stated or confirmed before planning")
    start = date.fromisoformat(draft["start_date"])
    end = start + timedelta(days=int(draft["num_days"]) - 1)
    return TripRequest(
        origin=draft["origin"],
        destination=HUE,
        start_date=start,
        end_date=end,
        people=draft["people"],
        rooms=draft.get("rooms") or 1,
        budget_vnd=draft.get("budget_vnd"),
        categories=draft.get("categories", []),
        exclude_categories=draft.get("exclude_categories", []),
        preferences=draft.get("preferences", []),
        must_include_poi_ids=draft.get("must_include_poi_ids", []),
        exclude_poi_ids=draft.get("exclude_poi_ids", []),
    )
