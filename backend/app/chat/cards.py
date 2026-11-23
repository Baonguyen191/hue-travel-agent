"""Build reply cards from stored plans and POIs. Every field is copied from the data."""

from __future__ import annotations

from typing import Any

from app.chat.schemas import BudgetOptionView, PlaceCard, PlanCard, PlanDay, PlanItem
from app.schemas.itinerary import ItineraryEvent, ItineraryResult
from app.schemas.place import Place
from app.services.poi_search import haversine_km

PHONE_KEY = "Điện thoại"
NEARBY_KM = 1.0
NEARBY_LIMIT = 5


def plan_card(plan: dict[str, Any], state: dict[str, Any]) -> PlanCard:
    """The plan summary: days with timed items, and the budget options with their totals."""
    payload = plan["payload"]
    itinerary = ItineraryResult.model_validate(payload["itinerary"])
    days = [
        PlanDay(date=day.date.isoformat(), items=[_item(event) for event in day.events if event.kind != "BUFFER"])
        for day in itinerary.days
    ]
    options = [
        BudgetOptionView(
            label=option["label"],
            known_total_vnd=option["known_total_vnd"],
            known_total_max_vnd=option["known_total_max_vnd"],
            budget_status=option["budget_status"],
        )
        for option in payload["budget"]["options"]
        if option.get("label")
    ]
    return PlanCard(
        thread_id=state["thread_id"],
        status=state["status"],
        version=plan["version"],
        days=days,
        budget_options=options,
    )


def place_card(place: Place) -> PlaceCard:
    return PlaceCard(
        poi_id=place.id,
        name=place.name,
        category=place.category,
        address=place.address,
        opening_hours_raw=place.opening_hours_raw,
        price_min_vnd=place.price_min_vnd,
        price_max_vnd=place.price_max_vnd,
        phone=phone_of(place),
        source_url=place.source_url,
        photo_illustrative=place.photo is not None and place.photo.kind == "commons_illustrative",
    )


def phone_of(place: Place) -> str | None:
    value = place.raw_attributes.get(PHONE_KEY)
    return str(value) if value else None


def nearby_places(place: Place, places: list[Place]) -> list[tuple[Place, float]]:
    """POIs within 1 km of `place` (not the place itself), nearest first, at most five."""
    found: list[tuple[Place, float]] = []
    for other in places:
        if other.id == place.id:
            continue
        distance = haversine_km(place.lat, place.lon, other.lat, other.lon)
        if distance <= NEARBY_KM:
            found.append((other, distance))
    found.sort(key=lambda item: (item[1], item[0].id))
    return found[:NEARBY_LIMIT]


def _item(event: ItineraryEvent) -> PlanItem:
    return PlanItem(
        time=event.start_at.strftime("%H:%M"), name=event.name, kind=event.kind, meal=event.meal,
        poi_id=event.poi_id, slot=event.slot, reason=event.reason, intro=event.intro,
    )
