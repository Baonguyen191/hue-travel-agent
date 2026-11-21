"""Deterministic, local-only search and geo ranking for Hue POIs."""

from __future__ import annotations

import math
import re
import unicodedata
from collections.abc import Iterable

from rapidfuzz import fuzz

from app.schemas.place import Place, PlaceCategory, PlaceSearchResult

_SPACE_PATTERN = re.compile(r"\s+")
_EARTH_RADIUS_KM = 6_371.0088


def normalize_vietnamese(text: str) -> str:
    """Case-fold text and remove Vietnamese diacritics for local matching."""
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    without_marks = "".join(
        character for character in decomposed if not unicodedata.combining(character)
    )
    return _SPACE_PATTERN.sub(" ", without_marks.replace("đ", "d")).strip()


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Return straight-line distance in kilometres between two coordinates."""
    latitude_delta = math.radians(lat2 - lat1)
    longitude_delta = math.radians(lon2 - lon1)
    a = (
        math.sin(latitude_delta / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(longitude_delta / 2) ** 2
    )
    return _EARTH_RADIUS_KM * 2 * math.asin(math.sqrt(a))


def _searchable_text(place: Place) -> tuple[str, str, str, str]:
    return (
        normalize_vietnamese(place.name),
        normalize_vietnamese(place.summary or ""),
        normalize_vietnamese(place.address or ""),
        normalize_vietnamese(str(place.raw_attributes.get("Loại hình (theo nguồn)", ""))),
    )


def _rating_confidence(place: Place) -> float:
    if place.rating_value is None:
        return 0.0
    review_confidence = min(math.log1p(place.rating_count or 0) / math.log1p(1_000), 1.0)
    return (place.rating_value / 5) * (0.4 + 0.6 * review_confidence)


def search_places(
    places: Iterable[Place],
    *,
    query: str | None = None,
    category: PlaceCategory | None = None,
    lat: float | None = None,
    lon: float | None = None,
    radius_km: float | None = None,
) -> list[PlaceSearchResult]:
    """Filter and rank already-normalized POIs without modifying their source DB.

    A textual query is matched against name, summary, address and the source's
    type field. Geographic filtering always uses straight-line distance.
    """
    if (lat is None) != (lon is None):
        raise ValueError("lat and lon must be supplied together")
    if radius_km is not None and (lat is None or radius_km <= 0):
        raise ValueError("radius_km requires coordinates and must be positive")

    normalized_query = normalize_vietnamese(query or "")
    results: list[PlaceSearchResult] = []
    for place in places:
        if category is not None and place.category != category:
            continue

        distance_km = (
            haversine_km(lat, lon, place.lat, place.lon) if lat is not None and lon is not None else None
        )
        if radius_km is not None and distance_km is not None and distance_km > radius_km:
            continue

        if normalized_query:
            name, summary, address, source_type = _searchable_text(place)
            # `ratio` deliberately avoids partial-match inflation: a short word
            # appearing anywhere in an unrelated long name must not outrank a
            # close full-name match.
            text_score = max(
                fuzz.ratio(normalized_query, name),
                fuzz.ratio(normalized_query, summary) * 0.78,
                fuzz.ratio(normalized_query, address) * 0.70,
                fuzz.ratio(normalized_query, source_type) * 0.65,
            )
            # Avoid returning arbitrary POIs for a query that has no useful match.
            if text_score < 60:
                continue
            score = text_score * 0.90 + _rating_confidence(place) * 7
            if distance_km is not None:
                score += 3 / (1 + distance_km)
        elif distance_km is not None:
            score = 95 / (1 + distance_km) + _rating_confidence(place) * 5
        else:
            score = _rating_confidence(place) * 100

        results.append(
            PlaceSearchResult(
                place=place,
                score=round(min(score, 100), 3),
                distance_km=round(distance_km, 3) if distance_km is not None else None,
            )
        )
    return sorted(results, key=lambda result: (-result.score, result.place.id))
