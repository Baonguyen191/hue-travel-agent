"""Merge understood messages into the plan draft, ask for what is missing, and build the TripRequest.

The draft holds only what the user stated or answered. A plan starts only when every required
slot is filled (`pending_units` is empty); optional slots (transport, stay, pace, places) are
asked once, after the required ones, and settled by the next answer (see `app.chat.slots`).
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Sequence
from datetime import date, timedelta
from typing import Any

from app.chat import texts
from app.schemas.request import TripRequest
from app.services.origin import is_hue_name
from app.understanding.models import ParsedQuery
from app.understanding.understand import MAX_DAYS

HUE = "Huế"
_MAX_PREFERENCES = 10
_SCALAR_FIELDS = ("origin", "people", "rooms", "budget_vnd", "num_days")
REQUIRED_UNITS = ("when", "origin", "people", "budget", "interests")
# "budget_ok" is the early budget check (S2): pending only while the cheapest estimate is over budget.
OPTIONAL_UNITS = ("transport", "stay", "budget_ok", "pace", "places")
# The draft key that holds each optional unit's settled value; "places" settles with places_done.
UNIT_KEYS = {"transport": "transport_mode", "stay": "hotel_tier", "pace": "pace"}
# The request fields the cheapest estimate depends on (pace and the rest do not change the budget).
_PRECHECK_FIELDS = frozenset({
    "budget_vnd", "people", "rooms", "start_date", "end_date", "origin", "categories", "themes",
    "exclude_categories", "must_include_poi_ids", "exclude_poi_ids", "transport_mode", "hotel_tier",
})
_WEEKDAYS = ("thứ Hai", "thứ Ba", "thứ Tư", "thứ Năm", "thứ Sáu", "thứ Bảy", "Chủ nhật")


def merge_draft(draft: dict[str, Any], parsed: ParsedQuery) -> dict[str, Any]:
    """Return the draft with the values stated in `parsed` added; stated scalars overwrite."""
    merged = dict(draft)
    fields = parsed.fields
    for name in _SCALAR_FIELDS:
        if fields.get(name) is not None:
            merged[name] = fields[name]
    if isinstance(merged.get("origin"), str):
        merged["origin"] = " ".join(word[:1].upper() + word[1:] for word in merged["origin"].split())
    if fields.get("start_date") is not None:
        merged["start_date"] = fields["start_date"].isoformat()
    _extend(merged, "categories", fields.get("categories", []))
    _extend(merged, "exclude_categories", fields.get("exclude_categories", []))
    _extend(merged, "themes", fields.get("themes", []))
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


def _valid_days(draft: dict[str, Any]) -> int | None:
    """The stated length when it can be planned (at most MAX_DAYS), else None."""
    days = draft.get("num_days")
    return days if days is not None and days <= MAX_DAYS else None


def settled(unit: str, draft: dict[str, Any]) -> bool:
    """True when the draft has a value for the unit (a required unit is then never asked again)."""
    if unit == "when":
        return draft.get("start_date") is not None and _valid_days(draft) is not None
    if unit == "origin":
        return draft.get("origin") is not None
    if unit == "people":
        return draft.get("people") is not None
    if unit == "budget":
        return draft.get("budget_vnd") is not None
    if unit == "interests":
        return bool(draft.get("categories"))
    if unit == "places":
        return bool(draft.get("places_done"))
    if unit == "budget_ok":
        return not budget_check_open(draft)
    return draft.get(UNIT_KEYS[unit]) is not None


def skipped(unit: str, draft: dict[str, Any]) -> bool:
    """An optional unit that does not apply: transport when the trip starts in Huế, a stay on a 1-day trip."""
    if unit == "transport":
        origin = draft.get("origin")
        return origin is not None and is_hue_name(origin)
    if unit == "stay":
        return draft.get("num_days") == 1
    return False


def pending_units(draft: dict[str, Any]) -> list[str]:
    """Unsettled units in the order they are asked. Optional units wait until every required unit is settled."""
    required = [unit for unit in REQUIRED_UNITS if not settled(unit, draft)]
    if required:
        return required
    asked = draft.get("asked", [])
    return [unit for unit in OPTIONAL_UNITS if _open_optional(unit, draft, asked)]


def _open_optional(unit: str, draft: dict[str, Any], asked: Sequence[str]) -> bool:
    if unit == "budget_ok":
        # Not marked as asked for good: it stays open until a budget answer settles it.
        return budget_check_open(draft)
    return not settled(unit, draft) and not skipped(unit, draft) and unit not in asked


def precheck_key(draft: dict[str, Any]) -> str | None:
    """A stable string of what the cheapest estimate depends on; None while the draft cannot make a request."""
    try:
        request = build_request(draft)
    except ValueError:
        return None
    fields = request.model_dump(mode="json", include=_PRECHECK_FIELDS)
    return json.dumps(fields, sort_keys=True, ensure_ascii=False)


def precheck_due(draft: dict[str, Any]) -> bool:
    """True once every required slot and the transport and stay slots are settled, and the stored check is stale."""
    if any(not settled(unit, draft) for unit in REQUIRED_UNITS):
        return False
    if not all(settled(unit, draft) or skipped(unit, draft) for unit in ("transport", "stay")):
        return False
    key = precheck_key(draft)
    return key is not None and (draft.get("precheck") or {}).get("key") != key


def budget_check_open(draft: dict[str, Any]) -> bool:
    """The cheapest estimate is over the budget and the user has not accepted the budget as it is."""
    precheck = draft.get("precheck") or {}
    budget = draft.get("budget_vnd")
    if budget is None or precheck.get("min") is None or draft.get("budget_accepted"):
        return False
    return precheck["min"] > budget


def pending_soft_note(draft: dict[str, Any]) -> str | None:
    """The one-time note when the cheapest estimate fits the budget only partly (min <= budget < max)."""
    precheck = draft.get("precheck") or {}
    budget = draft.get("budget_vnd")
    if draft.get("precheck_noted") or budget is None or precheck.get("min") is None:
        return None
    if precheck["min"] <= budget < precheck["max"]:
        return texts.soft_budget_note(money_text(precheck["min"]), money_text(precheck["max"]))
    return None


def mark_asked(draft: dict[str, Any], units: Sequence[str]) -> dict[str, Any]:
    """Record the units a question turn sends: `last_asked` for the next answer, `asked` for good."""
    marked = dict(draft)
    marked["last_asked"] = list(units)
    asked = list(marked.get("asked", []))
    asked.extend(unit for unit in units if unit not in asked)
    marked["asked"] = asked
    return marked


def asked_units(draft: dict[str, Any]) -> list[str]:
    """The units the next question turn asks: the first two pending ones, or the budget check alone.

    The budget check is asked alone: an optional question asked beside it would be settled as
    "tùy" by the answer to the budget question and so lost. The chat marks exactly these units
    as asked, so the text and the bookkeeping cannot disagree.
    """
    units = pending_units(draft)[:2]
    if units and units[0] == "budget_ok":
        return units[:1]
    return units


def next_questions(draft: dict[str, Any]) -> str | None:
    """The whole turn text: a restated line when anything is known, then at most two questions.

    None when every slot is settled and the plan can start.
    """
    units = asked_units(draft)
    if not units:
        return None
    questions = [_question(unit, draft) for unit in units]
    body = questions[0] if len(questions) == 1 else f"1. {questions[0]}\n2. {questions[1]}"
    lines = [line for line in (restated(draft), pending_soft_note(draft)) if line]
    return "\n".join([*lines, body])


def _question(unit: str, draft: dict[str, Any]) -> str:
    if unit == "when":
        days = draft.get("num_days")
        if days is not None and days > MAX_DAYS:
            return texts.too_many_days(MAX_DAYS)
        return texts.when_question(need_start=draft.get("start_date") is None, need_days=days is None)
    if unit == "budget_ok":
        return _budget_warning(draft)
    return texts.QUESTIONS[unit]


def _budget_warning(draft: dict[str, Any]) -> str:
    """The over-budget warning with the cheapest option's range and the excess over the budget."""
    precheck = draft["precheck"]
    budget = int(draft["budget_vnd"])
    if draft.get("budget_raise"):
        # The user said "tăng ngân sách" without an amount: ask for it, do not repeat the warning.
        return texts.budget_raise_question(
            low=money_text(precheck["min"]), high=money_text(precheck["max"]),
            mode=precheck.get("mode"), tier=precheck.get("tier"),
        )
    return texts.budget_warning(
        low=money_text(precheck["min"]),
        high=money_text(precheck["max"]),
        over_low=money_text(precheck["min"] - budget),
        over_high=money_text(precheck["max"] - budget),
        budget=money_text(budget),
        mode=precheck.get("mode"),
        tier=precheck.get("tier"),
    )


def restated(draft: dict[str, Any]) -> str | None:
    """"Mình ghi nhận: Hà Nội → Huế, 2 người, …." from what the draft knows besides the destination."""
    origin = draft.get("origin")
    extras: list[str] = []
    if draft.get("people") is not None:
        extras.append(f"{draft['people']} người")
    dates = _dates_text(draft)
    if dates is not None:
        extras.append(dates)
    if draft.get("budget_vnd") is not None:
        extras.append(f"ngân sách {money_text(int(draft['budget_vnd']))}")
    interests = interest_names(draft.get("categories") or [], draft.get("themes") or [])
    if interests:
        extras.append("thích " + ", ".join(interests))
    if not extras and origin is None:
        return None
    route = HUE if origin is None or is_hue_name(origin) else f"{origin} → {HUE}"
    return "Mình ghi nhận: " + ", ".join([route, *extras]) + "."


def interest_names(categories: Sequence[str], themes: Sequence[str]) -> list[str]:
    """The interests as the user would say them: food categories read "ẩm thực", nature attractions
    "thiên nhiên, ngắm cảnh"; any other category keeps its own name."""
    wanted = set(categories)
    names: list[str] = []
    if "restaurant" in wanted:
        names.append("ẩm thực")
        wanted -= {"restaurant", "cafe", "market"}
    if "attraction" in wanted and "nature" in themes:
        names.append("thiên nhiên, ngắm cảnh")
        wanted.discard("attraction")
    own = {"historic": "di tích", "religious": "chùa chiền", "cafe": "cà phê", "market": "chợ",
           "attraction": "tham quan", "park": "công viên", "museum": "bảo tàng"}
    names.extend(own.get(code, texts.category_name(code)) for code in categories if code in wanted)
    return names


def _day_text(value: date) -> str:
    return f"{_WEEKDAYS[value.weekday()]} {value.day:02d}/{value.month:02d}"


def _dates_text(draft: dict[str, Any]) -> str | None:
    """"thứ Ba 24/11 – thứ Năm 26/11 (3 ngày 2 đêm)"; without a start "3 ngày 2 đêm"; without a length "từ thứ Ba 24/11"."""
    days = _valid_days(draft)
    start_iso = draft.get("start_date")
    start = date.fromisoformat(start_iso) if start_iso is not None else None
    length = None
    if days is not None:
        length = "1 ngày" if days == 1 else f"{days} ngày {days - 1} đêm"
    if start is not None and days is not None:
        span = _day_text(start)
        if days > 1:
            span = f"{span} – {_day_text(start + timedelta(days=days - 1))}"
        return f"{span} ({length})"
    if start is not None:
        return f"từ {_day_text(start)}"
    return length


def money_text(amount: int) -> str:
    """"6 triệu", "6,5 triệu", "6,35 triệu" from a million up; "800.000 đ" below a million."""
    if amount >= 1_000_000:
        millions = f"{round(amount / 1_000_000, 2):g}".replace(".", ",")
        return f"{millions} triệu"
    return f"{amount:,}".replace(",", ".") + " đ"


def summary_lines(draft: dict[str, Any], name_of: Callable[[str], str | None]) -> dict[str, str]:
    """The summary lines of a complete draft, each one as shown (label included), keyed by line.

    The chat stores this dict; the next summary marks every line whose text differs from it.
    """
    lines: dict[str, str] = {}
    origin = draft.get("origin")
    route = HUE if origin is None or is_hue_name(origin) else f"{origin} → {HUE}"
    lines["trip"] = "Hành trình: " + ", ".join(part for part in (route, _dates_text(draft)) if part)
    lines["party"] = f"Đoàn: {draft['people']} người, {draft.get('rooms') or 1} phòng"
    lines["budget"] = _budget_line(draft)
    travel = _travel_line(draft)
    if travel is not None:
        lines["travel"] = travel
    lines["pace"] = "Nhịp độ: " + texts.SUMMARY_PACE.get(draft.get("pace") or "moderate", texts.SUMMARY_PACE["moderate"])
    interests = interest_names(draft.get("categories") or [], draft.get("themes") or [])
    if interests:
        lines["interests"] = "Ưu tiên: " + ", ".join(interests)
    places = _places_line(draft, name_of)
    if places is not None:
        lines["places"] = places
    return lines


def summary_text(draft: dict[str, Any], name_of: Callable[[str], str | None], previous: dict[str, str] | None = None) -> str:
    """The summary before planning (S4). A line whose text differs from `previous` gets the changed mark (S5)."""
    rows = []
    for key, line in summary_lines(draft, name_of).items():
        changed = previous is not None and previous.get(key) != line
        rows.append(f"- {line}{texts.CHANGED_MARK if changed else ''}")
    return "\n".join([texts.SUMMARY_HEAD, *rows, texts.SUMMARY_TAIL])


def _budget_line(draft: dict[str, Any]) -> str:
    """"Ngân sách: 6 triệu (ước tính 5,15–6,16 triệu)"; the note says "chọn phương án tiết kiệm nhất" when over budget."""
    budget = int(draft["budget_vnd"])
    precheck = draft.get("precheck") or {}
    line = f"Ngân sách: {money_text(budget)}"
    if precheck.get("min") is None or precheck.get("max") is None:
        return line
    estimate = texts.money_range(money_text(precheck["min"]), money_text(precheck["max"]))
    if precheck["min"] > budget:
        return f"{line} (chọn phương án tiết kiệm nhất, ước tính {estimate})"
    return f"{line} (ước tính {estimate})"


def _travel_line(draft: dict[str, Any]) -> str | None:
    """"Đi lại: xe giường nằm · Chỗ ở: homestay"; a part that does not apply is left out, and so is the line."""
    parts = []
    if not skipped("transport", draft):
        mode = texts.SUMMARY_TRANSPORT.get(draft.get("transport_mode") or "", texts.CHEAPEST)
        parts.append(f"Đi lại: {mode}")
    if not skipped("stay", draft):
        tier = texts.SUMMARY_STAY.get(draft.get("hotel_tier") or "", texts.CHEAPEST)
        parts.append(f"Chỗ ở: {tier}")
    return " · ".join(parts) or None


def _places_line(draft: dict[str, Any], name_of: Callable[[str], str | None]) -> str | None:
    """"Muốn đến: Đại Nội Huế · Tránh: Chợ Đông Ba Huế"; places with no name are left out."""
    wants = [name for poi_id in draft.get("must_include_poi_ids", []) if (name := name_of(poi_id))]
    avoids = [name for poi_id in draft.get("exclude_poi_ids", []) if (name := name_of(poi_id))]
    avoids.extend(texts.category_name(code) for code in draft.get("exclude_categories", []))
    parts = []
    if wants:
        parts.append("Muốn đến: " + ", ".join(wants))
    if avoids:
        parts.append("Tránh: " + ", ".join(avoids))
    return " · ".join(parts) or None


def build_request(draft: dict[str, Any]) -> TripRequest:
    """The TripRequest of a complete draft; raises ValueError while origin or party size is missing."""
    missing = [name for name in ("origin", "people") if draft.get(name) is None]
    if missing:
        raise ValueError(f"{' and '.join(missing)} must be stated before planning")
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
        themes=draft.get("themes", []),
        exclude_categories=draft.get("exclude_categories", []),
        preferences=draft.get("preferences", []),
        must_include_poi_ids=draft.get("must_include_poi_ids", []),
        exclude_poi_ids=draft.get("exclude_poi_ids", []),
        transport_mode=_choice(draft.get("transport_mode")),
        hotel_tier=_choice(draft.get("hotel_tier")),
        pace=_choice(draft.get("pace")) or "moderate",
    )


def _choice(value: Any) -> str | None:
    """A stated slot value; "any" or a missing slot is None (the TripRequest default)."""
    return None if value in (None, "any") else value
