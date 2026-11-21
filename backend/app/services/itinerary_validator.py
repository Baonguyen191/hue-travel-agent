"""Invariant checks for generated itineraries."""

from __future__ import annotations

from app.schemas.itinerary import ItineraryDay, ItineraryValidation

_FOOD_CATEGORIES = frozenset({"restaurant", "cafe"})


def validate_itinerary(days: list[ItineraryDay]) -> ItineraryValidation:
    """Detect overlaps, duplicate POIs, food used as a visit, missing lunch and long legs."""
    warnings: list[str] = []
    seen_poi_ids: set[str] = set()
    for day in days:
        previous_end = None
        for event in sorted(day.events, key=lambda item: item.start_at):
            if event.start_at.date() != day.date or event.end_at.date() != day.date:
                warnings.append(f"Event '{event.name}' is outside itinerary date {day.date}.")
            if previous_end is not None and event.start_at < previous_end:
                warnings.append(f"Overlapping events found on {day.date}.")
            previous_end = max(previous_end, event.end_at) if previous_end else event.end_at
            if event.poi_id:
                if event.poi_id in seen_poi_ids:
                    warnings.append(f"POI {event.poi_id} is scheduled more than once.")
                seen_poi_ids.add(event.poi_id)
            if event.kind == "VISIT" and event.category in _FOOD_CATEGORIES:
                warnings.append(f"'{event.name}' is a {event.category} scheduled as a visit.")
            if event.travel_distance_km is not None and event.travel_distance_km > 20:
                warnings.append(f"Long estimated straight-line leg ({event.travel_distance_km} km) to '{event.name}'.")
        if _has_visit(day) and not _has_lunch(day):
            warnings.append(f"Day {day.date} has visits but no lunch.")
    return ItineraryValidation(valid=not warnings, warnings=warnings)


def _has_visit(day: ItineraryDay) -> bool:
    return any(event.kind == "VISIT" for event in day.events)


def _has_lunch(day: ItineraryDay) -> bool:
    return any(
        event.kind == "MEAL_BREAK" or (event.kind == "MEAL" and event.meal == "LUNCH")
        for event in day.events
    )
