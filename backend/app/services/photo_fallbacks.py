"""Choose the photo shown for a Huế POI: its source photo, a curated Commons photo of that place, or a
curated generic photo of its category (labelled as illustrative by the UI)."""

from __future__ import annotations

import functools
import json
import zlib
from pathlib import Path
from typing import Any

from app.schemas.place import PlacePhoto
from app.services.photos import is_source_host

FALLBACKS_PATH = Path(__file__).resolve().parents[1] / "data" / "photo_fallbacks.json"


@functools.cache
def load_fallbacks() -> dict[str, Any]:
    return json.loads(FALLBACKS_PATH.read_text(encoding="utf-8"))


def _pick_category_photo(poi_id: str, name: str, category: str) -> dict[str, Any] | None:
    rules = load_fallbacks()["categories"].get(category)
    if not rules:
        return None
    lowered = name.lower()
    for rule in rules:
        keywords = rule["keywords"]
        if not keywords or any(keyword in lowered for keyword in keywords):
            photos = rule["photos"]
            return photos[zlib.crc32(poi_id.encode("utf-8")) % len(photos)]
    return None


def illustrative_photo(poi_id: str, name: str, category: str) -> PlacePhoto | None:
    """A generic Commons photo for the category, chosen deterministically from the POI id."""
    photo = _pick_category_photo(poi_id, name, category)
    if photo is None:
        return None
    return PlacePhoto(
        kind="commons_illustrative",
        url=photo["url"],
        author=photo.get("author"),
        license=photo.get("license"),
        credit_url=photo.get("page_url"),
    )


def resolve_photo(poi_id: str, name: str, category: str, photo_url: str | None) -> PlacePhoto | None:
    """The photo to show for a place, in order of preference: source, place-specific Commons, category."""
    if is_source_host(photo_url):
        return PlacePhoto(kind="source", url=photo_url)
    curated = load_fallbacks()["places"].get(poi_id)
    if curated is not None:
        return PlacePhoto(
            kind="commons_place",
            url=curated["url"],
            author=curated.get("author"),
            license=curated.get("license"),
            credit_url=curated.get("page_url"),
        )
    return illustrative_photo(poi_id, name, category)
