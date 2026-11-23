"""Text rendering for the Itinerary Agent demo: per-day timeline, summary and budget block."""

from __future__ import annotations

from app.demo.budget_view import label_text
from app.demo.formatting import money_range, request_lines, warning_lines
from app.schemas.budget import BudgetOption, BudgetResult
from app.schemas.itinerary import ItineraryDay, ItineraryEvent, ItineraryResult
from app.schemas.place import Place
from app.schemas.request import TripRequest

_MEAL_LABELS = {"LUNCH": "[Ăn trưa]", "DINNER": "[Ăn tối]", "CAFE": "[Cà phê]"}
_FREE_TEXT = "miễn phí theo nguồn"


def _span(event: ItineraryEvent) -> str:
    return f"{event.start_at:%H:%M}–{event.end_at:%H:%M}"


def _travel_text(event: ItineraryEvent) -> str:
    if event.travel_distance_km is None or event.travel_minutes_estimated is None:
        return "-"
    return f"{event.travel_distance_km:.1f} km ~{event.travel_minutes_estimated}'"


def _hours_text(place: Place | None) -> str:
    if place is None or not place.opening_hours_raw:
        return "giờ mở chưa rõ"
    return f"giờ mở {place.opening_hours_raw} (chưa xác minh)"


def _visit_price(place: Place | None) -> str:
    if place is not None and place.price_status == "REFERENCE_RANGE":
        return f"vé {money_range(place.price_min_vnd, place.price_max_vnd)}/người [DATA]"
    if place is not None and place.price_status == "FREE_CLAIM":
        return _FREE_TEXT
    return "vé chưa rõ"


def _meal_price(place: Place | None) -> str:
    if place is not None and place.price_status == "REFERENCE_RANGE":
        return f"{money_range(place.price_min_vnd, place.price_max_vnd)} (tham khảo)"
    if place is not None and place.price_status == "FREE_CLAIM":
        return _FREE_TEXT
    return "giá chưa rõ"


def _event_line(event: ItineraryEvent, places: dict[str, Place]) -> str:
    place = places.get(event.poi_id) if event.poi_id else None
    if event.kind == "VISIT":
        head = f"[Tham quan] {event.name} ({event.category})"
        details = [_travel_text(event), _visit_price(place), _hours_text(place), event.poi_id or "-"]
    elif event.kind == "MEAL":
        head = f"{_MEAL_LABELS.get(event.meal or '', '[Ăn]')} {event.name}"
        details = [_travel_text(event), _meal_price(place), _hours_text(place), event.poi_id or "-"]
    elif event.kind == "REST":
        return f"{_span(event)}  [Nghỉ trưa] {event.name}"
    else:
        return f"{_span(event)}  {_MEAL_LABELS['LUNCH']} {event.name}"
    return "  ".join([f"{_span(event)}  {head}", *details])


def _day_lines(index: int, day: ItineraryDay, places: dict[str, Place]) -> list[str]:
    lines = ["", f"== Day {index}: {day.date} =="]
    events = [event for event in day.events if event.kind != "BUFFER"]
    if not events:
        lines.append("  (no scheduled events)")
    lines.extend("  " + _event_line(event, places) for event in events)
    return lines


def _summary_lines(result: ItineraryResult) -> list[str]:
    warnings = list(result.warnings)
    for day in result.days:
        warnings.extend(f"{day.date}: {warning}" for warning in day.warnings)
    warnings.extend(result.validation.warnings)
    lines = [
        "",
        f"Unplanned POIs: {len(result.unplanned_poi_ids)} (ids in --json)",
        f"Excluded as too far from the centre: {len(result.excluded_poi_ids)}",
        f"Validation: {'valid' if result.validation.valid else 'invalid'}",
    ]
    lines.extend(warning_lines(warnings))
    return lines


def _admission_subtotal(option: BudgetOption) -> tuple[int, int, int]:
    """Return (low, high, unknown count) for sightseeing admissions in one option."""
    items = [item for item in option.items if item.code == "admission"]
    low = sum(item.amount_vnd or 0 for item in items)
    high = sum(
        item.amount_max_vnd if item.amount_max_vnd is not None else (item.amount_vnd or 0)
        for item in items
    )
    unknown = sum(item.amount_vnd is None for item in items)
    return low, high, unknown


def _budget_lines(budget: BudgetResult) -> list[str]:
    if not budget.options:
        return ["", "Budget: no options"]
    labelled = [option for option in budget.options if option.label is not None] or budget.options
    lines = ["", "Budget (visits and meals of this itinerary)"]
    for option in labelled:
        total = money_range(option.known_total_vnd, option.known_total_max_vnd)
        lines.append(
            f"  {label_text(option):<24} {total}  {option.budget_status}  unknown: {option.unknown_item_count}"
        )
    low, high, unknown = _admission_subtotal(labelled[0])
    lines.append(f"Admission subtotal (sightseeing): {money_range(low, high)}  unknown: {unknown}")
    return lines


def render_itinerary(
    request: TripRequest,
    result: ItineraryResult,
    budget: BudgetResult,
    places: dict[str, Place],
) -> str:
    """Render the request, each day's timeline, the summary and the budget block."""
    lines = request_lines(request)
    for index, day in enumerate(result.days, start=1):
        lines.extend(_day_lines(index, day, places))
    lines.extend(_summary_lines(result))
    lines.extend(_budget_lines(budget))
    return "\n".join(lines)
