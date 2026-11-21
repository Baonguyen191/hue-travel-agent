"""Understand one chat message: the LLM copies phrases, code resolves and decides.

Path with an extractor (Ollama): the model returns verbatim phrases; code resolves dates
(`dates.resolve_date_text`), durations, budgets (`normalize`), preferences
(`preferences.map_preferences`) and place names (`link.link_places`), fills defaults, and
decides whether to ask a question. Path without one (or when Ollama fails): the rule parser
`vi_request_parser` gives the same kind of result with source RULES.

`missing_fields` lists what the user did not state, before defaults. Defaults (origin Huế,
1 person) only shape the TripRequest; the clarification asks for start date and duration only.
"""

from __future__ import annotations

import functools
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Protocol

from pydantic import ValidationError

from app.core.config import hue_database_path
from app.repositories.hue_places import HuePlacesRepository
from app.schemas.place import Place, PlaceCategory
from app.schemas.request import TripRequest
from app.services.preferences import map_preferences
from app.understanding.normalize import strip_diacritics
from app.services.vi_request_parser import HUE_NAME, parse_vietnamese_request
from app.understanding.dates import resolve_date_text
from app.understanding.extract import Extraction, ExtractionError
from app.understanding.link import link_places
from app.understanding.models import (
    ApproveOption,
    Intent,
    ParsedQuery,
    PlaceMention,
    PlanChange,
    PlanChangeKind,
    QuSource,
)
from app.understanding.normalize import parse_budget_vnd, parse_duration

DEFAULT_ORIGIN = HUE_NAME
DEFAULT_PEOPLE = 1
MAX_DAYS = 7
MAX_PEOPLE = 20
# Interest phrases the preference table does not cover (folded). Whole-word match, checked after
# map_preferences; they only add categories the user clearly asked for.
INTEREST_SYNONYMS: dict[str, tuple[PlaceCategory, ...]] = {
    "ngam canh": ("park", "attraction"),
    "tham quan": ("attraction",),
    "bien": ("attraction",),
    "van hoa": ("museum",),
    "an vat": ("restaurant",),
    "an sang": ("restaurant",),
    "an trua": ("restaurant",),
    "an toi": ("restaurant",),
    "hai san": ("restaurant",),
    "do an": ("restaurant",),
}
QUICK_START = ("Cuối tuần này", "Ngày mai", "Thứ 7 tới")
QUICK_DAYS = ("2 ngày 1 đêm", "3 ngày 2 đêm")


class Extractor(Protocol):
    """Anything that turns a message into an Extraction (OllamaExtractor, or a fake in tests)."""

    def extract(self, text: str, ref: date) -> Extraction:
        """Return the phrases of `text`; raise ExtractionError when they cannot be produced."""
        ...


@dataclass(frozen=True)
class ConversationContext:
    """What the chat already knows: the current plan request, if any."""

    request: TripRequest | None = None


@dataclass
class _Draft:
    """Resolved pieces of one message, before the ParsedQuery is built."""

    intent: Intent = Intent.PLAN_NEW
    source: QuSource = QuSource.RULES
    date_text: str | None = None
    start: date | None = None
    num_days: int | None = None
    origin: str | None = None
    destination: str | None = None
    people: int | None = None
    rooms: int | None = None
    budget: int | None = None
    phrases: list[str] = field(default_factory=list)
    soft: list[str] = field(default_factory=list)
    categories: list[PlaceCategory] = field(default_factory=list)
    exclude_categories: list[PlaceCategory] = field(default_factory=list)
    must: list[PlaceMention] = field(default_factory=list)
    exclude: list[PlaceMention] = field(default_factory=list)
    changes: list[PlanChange] = field(default_factory=list)
    place_query: PlaceMention | None = None
    approve: ApproveOption | None = None
    notes: list[str] = field(default_factory=list)


@functools.cache
def load_places() -> tuple[Place, ...]:
    """POIs of the Hue database, read once per process; empty when the file is absent."""
    path = hue_database_path()
    if not path.is_file():
        return ()
    return tuple(HuePlacesRepository(path).list_all())


def understand(
    text: str,
    ref_date: date | None = None,
    context: ConversationContext | None = None,
    *,
    extractor: Extractor | None = None,
    places: Sequence[Place] | None = None,
) -> ParsedQuery:
    """Understand one message. Without an extractor the rule parser is used alone."""
    ref = ref_date or date.today()
    if extractor is None:
        return _to_query(_draft_from_rules(text, ref), context)
    try:
        extraction = extractor.extract(text, ref)
    except ExtractionError as error:
        draft = _draft_from_rules(text, ref)
        draft.notes.append(f"Ollama không dùng được ({error}); hiểu bằng luật.")
        return _to_query(draft, context)
    catalog = load_places() if places is None else places
    return _to_query(_draft_from_extraction(text, ref, extraction, catalog), context)


# ---------------------------------------------------------------------------
# Drafts: from the rule parser, or from the LLM extraction plus rules for gaps
# ---------------------------------------------------------------------------


def _rules_days(fields: dict[str, Any]) -> int | None:
    if "duration_days" in fields:
        return int(fields["duration_days"])
    start, end = fields.get("start_date"), fields.get("end_date")
    if start is not None and end is not None:
        return (end - start).days + 1
    return None


def _phrase_categories(phrase: str) -> list[PlaceCategory]:
    """Categories of one interest phrase: the preference table first, then the synonyms."""
    matched, _ = map_preferences([phrase])
    if matched:
        return matched
    folded = f" {strip_diacritics(phrase)} "
    for key, categories in INTEREST_SYNONYMS.items():
        if f" {key} " in folded:
            return list(categories)
    return []


def _map_interest_phrases(phrases: Sequence[str]) -> tuple[list[PlaceCategory], list[str]]:
    """(categories in first-seen order, phrases that map to nothing)."""
    categories: list[PlaceCategory] = []
    unmapped: list[str] = []
    for phrase in phrases:
        found = _phrase_categories(phrase)
        if not found:
            unmapped.append(phrase)
        for category in found:
            if category not in categories:
                categories.append(category)
    return categories, unmapped


def _is_other_city(destination: str | None) -> bool:
    return destination is not None and destination != HUE_NAME


def _draft_from_rules(text: str, ref: date) -> _Draft:
    fields = parse_vietnamese_request(text, ref).fields
    draft = _Draft(source=QuSource.RULES)
    draft.origin = fields.get("origin")
    draft.destination = fields.get("destination")
    draft.start = fields.get("start_date")
    draft.num_days = _rules_days(fields)
    draft.people = fields.get("people")
    draft.rooms = fields.get("rooms")
    draft.budget = fields.get("budget_vnd")
    draft.phrases = list(fields.get("preferences", []))
    draft.categories, draft.soft = _map_interest_phrases(draft.phrases)
    if _is_other_city(draft.destination):
        draft.intent = Intent.OUT_OF_SCOPE
    return draft


def _resolve_start(date_text: str | None, rules: dict[str, Any], ref: date) -> date | None:
    if date_text:
        resolved = resolve_date_text(date_text, ref)
        if resolved is not None:
            return resolved
    return rules.get("start_date")


def _resolve_days(extraction: Extraction, text: str, rules: dict[str, Any]) -> int | None:
    if extraction.duration_text:
        spec = parse_duration(extraction.duration_text)
        if spec is not None:
            return spec.num_days
    spec = parse_duration(text)
    if spec is not None:
        return spec.num_days
    return _rules_days(rules)


def _valid_people(value: int | None) -> int | None:
    if value is not None and 1 <= value <= MAX_PEOPLE:
        return value
    return None


def _draft_from_extraction(
    text: str, ref: date, extraction: Extraction, catalog: Sequence[Place]
) -> _Draft:
    rules = parse_vietnamese_request(text, ref).fields
    draft = _Draft(source=QuSource.OLLAMA, intent=extraction.intent, date_text=extraction.date_text)
    draft.start = _resolve_start(extraction.date_text, rules, ref)
    draft.num_days = _resolve_days(extraction, text, rules)
    draft.origin = extraction.origin or rules.get("origin")
    draft.destination = extraction.city or rules.get("destination")
    draft.people = _valid_people(extraction.people) or rules.get("people")
    draft.rooms = extraction.rooms or rules.get("rooms")
    draft.budget = parse_budget_vnd(extraction.budget_text or "") or rules.get("budget_vnd")
    draft.phrases = list(extraction.interest_phrases)
    draft.categories, unmapped = _map_interest_phrases(draft.phrases)
    draft.soft = [*unmapped, *extraction.soft_preferences]
    draft.exclude_categories, _ = map_preferences(extraction.exclude_category_phrases)
    draft.must = link_places(extraction.must_include_mentions, catalog, draft.notes)
    draft.exclude = link_places(extraction.exclude_mentions, catalog, draft.notes)
    draft.changes = [_to_change(item, catalog) for item in extraction.changes]
    draft.approve = extraction.approve_option
    _settle_intent(draft)
    return draft


def _settle_intent(draft: _Draft) -> None:
    """Out-of-scope cities win; a place question keeps only the place; others keep their intent."""
    if draft.intent is Intent.OUT_OF_SCOPE or _is_other_city(draft.destination):
        draft.intent = Intent.OUT_OF_SCOPE
    if draft.intent is Intent.PLACE_INFO and draft.must:
        draft.place_query = draft.must[0]
        draft.must = []


def _to_change(item: Any, catalog: Sequence[Place]) -> PlanChange:
    return PlanChange(kind=item.kind, value=_change_value(item, catalog), text=item.text)


def _change_value(item: Any, catalog: Sequence[Place]) -> str | int | None:
    if item.kind in (PlanChangeKind.ADD_DAYS, PlanChangeKind.REMOVE_DAYS):
        spec = parse_duration(item.text)
        if spec is not None:
            return spec.num_days
        return _int_or_none(item.value)
    if item.kind in (PlanChangeKind.ADD_PLACE, PlanChangeKind.REMOVE_PLACE):
        linked = link_places([item.text], catalog)
        return linked[0].poi_id if linked else None
    return item.value


# ---------------------------------------------------------------------------
# ParsedQuery per intent
# ---------------------------------------------------------------------------


def _to_query(draft: _Draft, context: ConversationContext | None) -> ParsedQuery:
    if draft.intent is Intent.MODIFY_PLAN:
        return _modify_query(draft, context)
    if draft.intent is Intent.PLAN_NEW:
        return _plan_query(draft)
    return ParsedQuery(
        intent=draft.intent,
        fields=_fields(draft),
        date_text=draft.date_text,
        must_include=draft.must,
        exclude=draft.exclude,
        exclude_categories=draft.exclude_categories,
        soft_preferences=draft.soft,
        place_query=draft.place_query,
        approve_option=draft.approve,
        source=draft.source,
        notes=draft.notes,
    )


def _modify_query(draft: _Draft, context: ConversationContext | None) -> ParsedQuery:
    request = context.request if context is not None else None
    notes = list(draft.notes)
    if request is not None:
        request, change_notes = apply_changes(request, draft.changes)
        notes.extend(change_notes)
    return ParsedQuery(
        intent=Intent.MODIFY_PLAN,
        request=request,
        fields=_fields(draft),
        date_text=draft.date_text,
        must_include=draft.must,
        exclude=draft.exclude,
        exclude_categories=draft.exclude_categories,
        soft_preferences=draft.soft,
        changes=draft.changes,
        source=draft.source,
        notes=notes,
    )


def _plan_query(draft: _Draft) -> ParsedQuery:
    question = _clarification(draft)
    request, problem = (None, None) if question else _build_request(draft)
    text, replies = question or (problem, [])
    return ParsedQuery(
        intent=Intent.PLAN_NEW,
        request=request,
        fields=_fields(draft),
        date_text=draft.date_text,
        missing_fields=_missing(draft),
        clarification=text,
        quick_replies=list(replies),
        must_include=draft.must,
        exclude=draft.exclude,
        exclude_categories=draft.exclude_categories,
        soft_preferences=draft.soft,
        source=draft.source,
        notes=draft.notes,
    )


def _missing(draft: _Draft) -> list[str]:
    """Required names not stated. The end date is unknown whenever the start or duration is."""
    checks = {
        "origin": draft.origin is None,
        "start_date": draft.start is None,
        "end_date": draft.start is None or draft.num_days is None,
        "people": draft.people is None,
    }
    return [name for name, absent in checks.items() if absent]


def _clarification(draft: _Draft) -> tuple[str, tuple[str, ...]] | None:
    """A Vietnamese question and quick replies when the start date or duration is unknown."""
    if draft.num_days is not None and draft.num_days > MAX_DAYS:
        return (f"Mình chỉ lên lịch tối đa {MAX_DAYS} ngày. Bạn muốn đi mấy ngày?", QUICK_DAYS)
    if draft.start is None and draft.num_days is None:
        return ("Bạn muốn đi Huế từ ngày nào và đi mấy ngày?", QUICK_START)
    if draft.start is None:
        return _start_question(draft)
    if draft.num_days is None:
        return ("Bạn định đi Huế mấy ngày?", QUICK_DAYS)
    return None


def _start_question(draft: _Draft) -> tuple[str, tuple[str, ...]]:
    if draft.date_text:
        return (f'Mình chưa hiểu ngày đi "{draft.date_text}". Bạn muốn đi từ ngày nào?', QUICK_START)
    return ("Bạn muốn đi Huế từ ngày nào?", QUICK_START)


def _build_request(draft: _Draft) -> tuple[TripRequest | None, str | None]:
    """A TripRequest with defaults applied, or (None, reason) when the values are not valid."""
    assert draft.start is not None and draft.num_days is not None
    payload: dict[str, Any] = {
        "origin": draft.origin or DEFAULT_ORIGIN,
        "destination": draft.destination or HUE_NAME,
        "start_date": draft.start,
        "end_date": draft.start + timedelta(days=draft.num_days - 1),
        "people": draft.people or DEFAULT_PEOPLE,
        "rooms": draft.rooms or 1,
        "budget_vnd": draft.budget,
        "categories": list(draft.categories),
        "preferences": draft.phrases[:10],
    }
    try:
        return TripRequest(**payload), None
    except ValidationError as error:
        return None, f"Thông tin chưa hợp lệ: {error.errors()[0]['msg']}. Bạn kiểm tra lại giúp mình nhé?"


def _fields(draft: _Draft) -> dict[str, Any]:
    """Stated or resolved values; keys with no value are left out, as in the rule parser."""
    fields: dict[str, Any] = {
        "origin": draft.origin,
        "destination": draft.destination or HUE_NAME,
        "start_date": draft.start,
        "num_days": draft.num_days,
        "people": draft.people,
        "rooms": draft.rooms,
        "budget_vnd": draft.budget,
        "categories": list(draft.categories),
        "exclude_categories": list(draft.exclude_categories),
    }
    if draft.num_days is not None:
        fields["duration_days"] = draft.num_days
        fields["nights"] = draft.num_days - 1
    if draft.start is not None and draft.num_days is not None:
        fields["end_date"] = draft.start + timedelta(days=draft.num_days - 1)
    return {name: value for name, value in fields.items() if value is not None}


# ---------------------------------------------------------------------------
# Plan changes
# ---------------------------------------------------------------------------


def _int_or_none(value: str | int | None) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _apply_days(data: dict[str, Any], change: PlanChange, notes: list[str]) -> None:
    days = _int_or_none(change.value)
    if days is None:
        notes.append(f"Chưa rõ số ngày để {change.kind.value}: '{change.text}'.")
        return
    if change.kind is PlanChangeKind.ADD_DAYS:
        data["end_date"] = data["end_date"] + timedelta(days=days)
        return
    new_end = data["end_date"] - timedelta(days=days)
    if new_end < data["start_date"]:
        notes.append("Không thể bỏ nhiều ngày hơn lịch hiện có.")
        return
    data["end_date"] = new_end


def _apply_dates(data: dict[str, Any], change: PlanChange, notes: list[str]) -> None:
    try:
        new_start = date.fromisoformat(str(change.value))
    except ValueError:
        notes.append(f"Chưa rõ ngày mới: '{change.text}'.")
        return
    length = data["end_date"] - data["start_date"]
    data["start_date"] = new_start
    data["end_date"] = new_start + length


def _apply_category(data: dict[str, Any], change: PlanChange) -> None:
    value = str(change.value) if change.value is not None else ""
    categories = list(data["categories"])
    if change.kind is PlanChangeKind.INCLUDE_CATEGORY and value not in categories:
        categories.append(value)
    if change.kind is PlanChangeKind.EXCLUDE_CATEGORY and value in categories:
        categories.remove(value)
    data["categories"] = categories


def _apply_one(data: dict[str, Any], change: PlanChange, notes: list[str]) -> None:
    kind = change.kind
    if kind in (PlanChangeKind.ADD_DAYS, PlanChangeKind.REMOVE_DAYS):
        _apply_days(data, change, notes)
    elif kind is PlanChangeKind.SET_DATES:
        _apply_dates(data, change, notes)
    elif kind is PlanChangeKind.SET_PEOPLE:
        data["people"] = _int_or_none(change.value) or data["people"]
    elif kind is PlanChangeKind.SET_BUDGET:
        data["budget_vnd"] = _int_or_none(change.value) or data["budget_vnd"]
    elif kind in (PlanChangeKind.INCLUDE_CATEGORY, PlanChangeKind.EXCLUDE_CATEGORY):
        _apply_category(data, change)
    else:
        notes.append(f"Chưa tự động áp dụng '{change.kind.value}': {change.text or change.value}.")


def apply_changes(
    request: TripRequest, changes: Sequence[PlanChange]
) -> tuple[TripRequest, list[str]]:
    """Apply the changes to a copy of `request`; return the copy and notes for what was skipped.

    Place changes (add_place, remove_place) are left to the orchestrator and reported as notes.
    An invalid result returns the original request with a note.
    """
    data = request.model_dump()
    notes: list[str] = []
    for change in changes:
        _apply_one(data, change, notes)
    try:
        return TripRequest(**data), notes
    except ValidationError as error:
        return request, [*notes, f"Không áp dụng được thay đổi: {error.errors()[0]['msg']}."]
