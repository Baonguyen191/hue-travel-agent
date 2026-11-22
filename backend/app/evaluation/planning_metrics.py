"""Travel-planning metrics on saved plan payloads (the JSON dicts PlanStore returns)."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, time
from typing import Any

from app.evaluation.gold import BudgetExpect, ConstraintExpect
from app.schemas.place import Place
from app.services.itinerary_optimizer import parse_simple_opening_window

WITHIN = frozenset({"WITHIN_BUDGET", "WITHIN_BUDGET_EXCLUDING_UNKNOWN"})
DAY_END = time(21, 0)


def budget_compliant(budget: Mapping[str, Any], expect: BudgetExpect) -> bool:
    """Feasible gold: an option fits and no WITHIN_BUDGET label is false. Infeasible gold: shortfall
    is reported and no option claims to fit."""
    options = list(budget.get("options", []))
    honest = all(
        option["known_total_max_vnd"] <= expect.budget_vnd
        for option in options
        if option.get("budget_status") == "WITHIN_BUDGET"
    )
    if expect.feasible:
        fits = any(option["known_total_max_vnd"] <= expect.budget_vnd for option in options)
        return bool(options) and fits and honest
    claims_fit = any(option.get("budget_status") in WITHIN for option in options)
    return budget.get("shortfall_vnd") is not None and not claims_fit


def _events(itinerary: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    return [event for day in itinerary.get("days", []) for event in day.get("events", [])]


def schedule_feasible(
    itinerary: Mapping[str, Any], places_by_id: Mapping[str, Place]
) -> tuple[bool, int, list[str]]:
    """Validator clean, visits inside parsable opening windows, nothing ends after DAY_END."""
    problems = list(itinerary.get("validation", {}).get("warnings", []))
    unchecked = 0
    for event in _events(itinerary):
        start = datetime.fromisoformat(str(event["start_at"]))
        end = datetime.fromisoformat(str(event["end_at"]))
        if end.time() > DAY_END or end.date() != start.date():
            problems.append(f"{event.get('name', event.get('poi_id'))} ends after {DAY_END:%H:%M}")
        if event.get("kind") != "VISIT" or not event.get("poi_id"):
            continue
        place = places_by_id.get(event["poi_id"])
        window = parse_simple_opening_window(place.opening_hours_raw) if place else None
        if window is None:
            unchecked += 1
        elif start.time() < window[0] or end.time() > window[1]:
            problems.append(
                f"{event['poi_id']} visited {start:%H:%M}-{end:%H:%M} outside {window[0]:%H:%M}-{window[1]:%H:%M}"
            )
    return not problems, unchecked, problems


def constraint_checks(itinerary: Mapping[str, Any], expect: ConstraintExpect) -> dict[str, bool]:
    """One pass/fail per constraint type the gold states."""
    events = _events(itinerary)
    poi_ids = {event["poi_id"] for event in events if event.get("poi_id")}
    categories = {event["category"] for event in events if event.get("category")}
    days = list(itinerary.get("days", []))
    checks: dict[str, bool] = {}
    if expect.must_include:
        checks["must_include"] = set(expect.must_include) <= poi_ids
    if expect.exclude:
        checks["exclude"] = not (set(expect.exclude) & poi_ids)
    if expect.exclude_categories:
        checks["exclude_categories"] = not (set(expect.exclude_categories) & categories)
    if expect.categories:
        checks["categories"] = set(expect.categories) <= categories
    if expect.num_days is not None:
        checks["num_days"] = len(days) == expect.num_days
    if expect.start_date is not None:
        checks["start_date"] = bool(days) and str(days[0]["date"]) == expect.start_date.isoformat()
    return checks
