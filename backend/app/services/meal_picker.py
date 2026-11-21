"""Pick restaurants and cafes for meal slots, never using one venue twice in a trip."""

from __future__ import annotations

from collections.abc import Iterable

from app.repositories.hue_places import HuePlacesRepository
from app.schemas.place import Place
from app.services.poi_search import haversine_km
from app.services.preferences import is_hue_specialty


class MealPicker:
    """Ranks unused venues by meal-radius, Hue specialty, rating and distance."""

    def __init__(
        self,
        candidates: Iterable[Place],
        places: HuePlacesRepository | None,
        radius_km: float,
    ) -> None:
        self._candidates = list(candidates)
        self._places = places
        self._radius_km = radius_km
        self._used: set[str] = set()
        self._pools: dict[str, list[Place]] = {}

    def pick(self, category: str, lat: float, lon: float) -> Place | None:
        """Return the best unused venue of `category` for a meal near (lat, lon)."""
        available = [place for place in self._pool(category) if place.id not in self._used]
        if not available:
            return None
        return min(available, key=lambda place: self._rank(place, lat, lon))

    def mark_used(self, place: Place) -> None:
        self._used.add(place.id)

    def used_ids(self) -> frozenset[str]:
        """Snapshot of venues already used, so a discarded day attempt can be undone."""
        return frozenset(self._used)

    def restore(self, snapshot: frozenset[str]) -> None:
        self._used = set(snapshot)

    def _pool(self, category: str) -> list[Place]:
        if category not in self._pools:
            self._pools[category] = self._build_pool(category)
        return self._pools[category]

    def _build_pool(self, category: str) -> list[Place]:
        pool: dict[str, Place] = {}
        for place in self._candidates:
            if place.category == category:
                pool.setdefault(place.id, place)
        if self._places is not None:
            for place in self._places.list_by_category(category):
                pool.setdefault(place.id, place)
        return list(pool.values())

    def _rank(self, place: Place, lat: float, lon: float) -> tuple[bool, bool, float, float, str]:
        distance = haversine_km(lat, lon, place.lat, place.lon)
        return (
            distance > self._radius_km,
            not is_hue_specialty(place),
            -(place.rating_value or 0.0),
            distance,
            place.id,
        )
