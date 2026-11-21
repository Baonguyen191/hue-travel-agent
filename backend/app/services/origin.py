"""Where a trip starts. A trip that starts in Huế needs no inter-city transport quote."""

from __future__ import annotations

from app.schemas.request import TripRequest
from app.services.poi_search import normalize_vietnamese

HUE_FORMS = frozenset({"hue", "thanh pho hue", "thua thien hue"})


def is_hue_name(name: str) -> bool:
    """Accept common Hue forms ("Huế", "Thành phố Huế") and reject every other place."""
    return normalize_vietnamese(name) in HUE_FORMS


def starts_in_hue(request: TripRequest) -> bool:
    """True when the traveller is already in Huế, so no transport provider is asked."""
    return is_hue_name(request.origin)
