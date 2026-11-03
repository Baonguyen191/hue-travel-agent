"""Chuyển dữ liệu OpenStreetMap (Overpass JSON) thành `Place`.

Dữ liệu OSM theo giấy phép ODbL-1.0: khi hiển thị phải ghi "© OpenStreetMap contributors".
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping
from typing import Any

from travel_agent.domain.models import Category, Coordinates, Place

OSM_LICENSE = "ODbL-1.0"
OSM_ATTRIBUTION = "© OpenStreetMap contributors"

_AMENITY_CATEGORIES: dict[str, Category] = {
    "restaurant": Category.RESTAURANT,
    "fast_food": Category.RESTAURANT,
    "cafe": Category.CAFE,
    "marketplace": Category.MARKET,
    "place_of_worship": Category.RELIGIOUS,
}


def category_from_tags(tags: Mapping[str, str]) -> Category | None:
    amenity = _AMENITY_CATEGORIES.get(tags.get("amenity", ""))
    if amenity is not None:
        return amenity
    tourism = tags.get("tourism")
    if tourism == "museum":
        return Category.MUSEUM
    if tourism == "viewpoint":
        return Category.VIEWPOINT
    if "historic" in tags:
        return Category.HISTORIC
    if tags.get("leisure") == "park":
        return Category.PARK
    if tourism == "attraction":
        return Category.ATTRACTION
    return None


def build_overpass_query(bbox: tuple[float, float, float, float]) -> str:
    """bbox = (south, west, north, east), đúng thứ tự Overpass."""
    south, west, north, east = bbox
    box = f"{south},{west},{north},{east}"
    return (
        "[out:json][timeout:180];\n"
        "(\n"
        f'  nwr["tourism"~"^(attraction|museum|viewpoint)$"]({box});\n'
        f'  nwr["historic"]({box});\n'
        f'  nwr["amenity"~"^(restaurant|fast_food|cafe|marketplace|place_of_worship)$"]({box});\n'
        f'  nwr["leisure"="park"]({box});\n'
        ");\n"
        "out center tags;\n"
    )


def places_from_overpass(payload: Mapping[str, Any], collected_at: dt.datetime) -> list[Place]:
    places: dict[str, Place] = {}
    for element in payload.get("elements", []):
        place = _place_from_element(element, collected_at)
        if place is not None:
            places[place.id] = place
    return list(places.values())


def _place_from_element(element: Mapping[str, Any], collected_at: dt.datetime) -> Place | None:
    tags: Mapping[str, str] = element.get("tags") or {}
    name = (tags.get("name") or "").strip()
    category = category_from_tags(tags)
    if not name or category is None:
        return None
    position: Mapping[str, Any] = (
        element if element.get("type") == "node" else (element.get("center") or {})
    )
    lat, lon = position.get("lat"), position.get("lon")
    if lat is None or lon is None:
        return None
    source_place_id = f"{element['type']}/{element['id']}"
    opening_hours = (tags.get("opening_hours") or "").strip() or None
    return Place(
        id=f"osm:{source_place_id}",
        name=name,
        category=category,
        coords=Coordinates(lat=lat, lon=lon),
        opening_hours_raw=opening_hours,
        source="osm",
        source_place_id=source_place_id,
        license=OSM_LICENSE,
        collected_at=collected_at,
    )
