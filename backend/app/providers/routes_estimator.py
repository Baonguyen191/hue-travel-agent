"""Local straight-line route estimates; deliberately not road travel times."""

from __future__ import annotations

from app.schemas.offer import Coordinates, RouteEstimate
from app.services.poi_search import haversine_km


class HaversineRouteEstimator:
    """Return distance only, never an implied driving/walking ETA."""

    def estimate(self, origin: Coordinates, destination: Coordinates) -> RouteEstimate:
        return RouteEstimate(
            source="HAVERSINE",
            status="ESTIMATED",
            origin=origin,
            destination=destination,
            distance_km=round(haversine_km(origin.lat, origin.lon, destination.lat, destination.lon), 3),
            travel_time_minutes=None,
            warning="Straight-line Haversine distance only; road route and ETA are unverified.",
        )
