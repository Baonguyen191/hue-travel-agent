"""Invariant checks for generated itineraries."""

from __future__ import annotations

from app.schemas.itinerary import ItineraryResult, ItineraryValidation


def validate_itinerary(days) -> ItineraryValidation:
    """Detect overlaps, duplicate POIs and unusually long straight-line legs."""
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
            if event.travel_distance_km is not None and event.travel_distance_km > 20:
                warnings.append(f"Long estimated straight-line leg ({event.travel_distance_km} km) to '{event.name}'.")
    return ItineraryValidation(valid=not warnings, warnings=warnings)
