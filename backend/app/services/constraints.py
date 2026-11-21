"""Must-include and exclude constraints shared by Search, Itinerary, Meals and Budget.

An excluded POI or category never reaches any agent's candidate list, so it cannot be
scheduled as a visit, a meal or a cafe break. A must-include POI must exist in the POI
source and must not sit in an excluded category.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.schemas.place import Place
from app.schemas.request import TripRequest

if TYPE_CHECKING:
    from app.repositories.hue_places import HuePlacesRepository


class UnknownPoiError(ValueError):
    """A must-include poi_id is not in the POI source."""


class ConstraintConflictError(ValueError):
    """A must-include POI is also excluded by category."""


def is_allowed(place: Place, request: TripRequest) -> bool:
    """True unless the request excludes this POI by id or by its category."""
    if place.id in request.exclude_poi_ids:
        return False
    return place.category not in request.exclude_categories


def check_constraints(request: TripRequest, places: HuePlacesRepository | None) -> None:
    """Refuse a request whose must-include ids are unknown or contradict an exclusion."""
    for poi_id in request.must_include_poi_ids:
        place = places.get_by_id(poi_id) if places is not None else None
        if place is None:
            raise UnknownPoiError(f"Unknown poi_id in must_include_poi_ids: {poi_id}")
        if place.category in request.exclude_categories:
            raise ConstraintConflictError(
                f"{place.name} is in an excluded category ({place.category}) and cannot be included."
            )
