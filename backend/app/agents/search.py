"""Combine local Hue POIs and provider offers for a structured trip request."""

from __future__ import annotations

import asyncio
from collections.abc import Iterable, Sequence

from app.providers.base import HotelProvider, ProviderTimeoutError, TransportProvider
from app.repositories.hue_places import HuePlacesRepository
from app.schemas.offer import HotelOffer, HotelSearchRequest, TransportOffer, TransportSearchRequest
from app.schemas.place import Place, PlaceCategory, PlaceSearchResult
from app.schemas.request import TripRequest
from app.schemas.search import SearchResult
from app.services.constraints import is_allowed
from app.services.origin import is_hue_name, starts_in_hue
from app.services.poi_search import normalize_vietnamese, search_places
from app.services.preferences import (
    NATURE_THEME,
    extract_keyword_hints,
    is_food_market,
    is_hue_specialty,
    is_nature,
    is_view_cafe,
    map_preferences,
    request_themes,
)

_MAX_CANDIDATES = 120
# Meals are picked from the POI source by MealPicker, so the food lists need only a few.
_FOOD_CATEGORIES: tuple[PlaceCategory, ...] = ("restaurant", "cafe")
_FOOD_LIST_LIMIT = 8
_RESTAURANT_SCALE = 0.85
_SPECIALTY_LIFT = 15.0
_VIEW_CAFE_LIFT = 15.0
_DEFAULT_TOURIST_MIX: tuple[PlaceCategory, ...] = (
    "historic",
    "restaurant",
    "cafe",
    "attraction",
    "religious",
)


def is_hue_destination(destination: str) -> bool:
    """Accept common Hue destination forms without treating other cities as Hue."""
    return is_hue_name(destination)


class SearchAgent:
    """Read local POIs and providers concurrently; never creates offers itself."""

    def __init__(
        self,
        places: HuePlacesRepository,
        transport_provider: TransportProvider,
        hotel_provider: HotelProvider,
    ) -> None:
        self.places = places
        self.transport_provider = transport_provider
        self.hotel_provider = hotel_provider

    async def search(self, request: TripRequest) -> SearchResult:
        if not is_hue_destination(request.destination):
            return SearchResult(
                status="UNSUPPORTED_DESTINATION",
                poi_candidates=[],
                transport_offers=[],
                hotel_offers=[],
                warnings=["Only Hue destinations are supported by the current POI source."],
            )

        poi_task = asyncio.to_thread(self._find_pois, request)
        transport_task = self._transport_offers(request)
        hotel_task = asyncio.to_thread(self._hotel_offers, request)
        poi_result, transport_result, hotel_result = await asyncio.gather(
            poi_task, transport_task, hotel_task, return_exceptions=True
        )

        warnings: list[str] = []
        poi_candidates = self._result_or_warning(poi_result, "POI source", warnings)
        transport_offers = self._result_or_warning(transport_result, "Transport provider", warnings)
        hotel_offers = self._result_or_warning(hotel_result, "Hotel provider", warnings)
        transport_offers, mode_warnings = _matching_transport(transport_offers, request.transport_mode)
        hotel_offers, tier_warnings = _matching_hotels(hotel_offers, request.hotel_tier)
        warnings.extend([*mode_warnings, *tier_warnings])

        if not poi_candidates:
            warnings.append("No Hue POIs matched the requested filters.")
        if not transport_offers and not starts_in_hue(request):
            warnings.append("No transport quote is available; no price was inferred.")
        if not hotel_offers and not request.is_day_trip:
            warnings.append("No hotel quote is available; no price was inferred.")

        return SearchResult(
            status="READY" if not warnings else "PARTIAL",
            poi_candidates=poi_candidates,
            transport_offers=transport_offers,
            hotel_offers=hotel_offers,
            warnings=warnings,
        )

    async def _transport_offers(self, request: TripRequest) -> list[TransportOffer]:
        """A trip that starts in Huế needs no inter-city quote, so the provider is not called."""
        if starts_in_hue(request):
            return []
        return await asyncio.to_thread(
            self.transport_provider.search,
            TransportSearchRequest(
                origin=request.origin,
                destination=request.destination,
                departure_date=request.start_date,
                return_date=request.end_date,
                passengers=request.people,
            ),
        )

    def _hotel_offers(self, request: TripRequest) -> list[HotelOffer]:
        """A same-day trip needs no hotel, so the provider is not called at all."""
        if request.is_day_trip:
            return []
        return self.hotel_provider.search(
            HotelSearchRequest(
                destination=request.destination,
                check_in=request.start_date,
                check_out=request.end_date,
                rooms=request.rooms,
                guests=request.people,
            )
        )

    def _find_pois(self, request: TripRequest) -> list[PlaceSearchResult]:
        places = [place for place in self.places.list_all() if is_allowed(place, request)]
        hinted, residual = (
            extract_keyword_hints(request.keyword) if request.keyword else ([], None)
        )
        preferred, unmapped = map_preferences(request.preferences)
        query = residual or (" ".join(unmapped) or None)

        explicit = _unique([*request.categories, *preferred])
        categories = _unique([*explicit, *hinted])
        if categories:
            plan = [(category, category not in hinted) for category in categories]
        elif query:
            plan = [(None, False)]
        else:
            plan = [(category, False) for category in _DEFAULT_TOURIST_MIX]

        lists = []
        for category, allow_fallback in plan:
            items = _search_category(places, request, category, query, allow_fallback)
            if category in _FOOD_CATEGORIES:
                items = items[:_FOOD_LIST_LIMIT]
            lists.append(items)
        return _interleave(lists, _MAX_CANDIDATES)

    @staticmethod
    def _result_or_warning(result: object, name: str, warnings: list[str]):
        if isinstance(result, ProviderTimeoutError):
            warnings.append(f"{name} timed out; its offers were omitted.")
            return []
        if isinstance(result, Exception):
            warnings.append(f"{name} failed; its offers were omitted.")
            return []
        return result


_TRANSPORT_MODE_CODES = {"bus": "BUS", "train": "TRAIN", "flight": "FLIGHT"}
_HOTEL_TIER_CODES = {"homestay": "HOMESTAY", "hotel": "THREE_STAR", "resort": "FOUR_STAR"}


def _matching_transport(
    offers: list[TransportOffer], mode: str | None
) -> tuple[list[TransportOffer], list[str]]:
    """Keep the offers of the chosen mode per leg (offers with no mode are kept).

    A leg with offers but none of the chosen mode keeps all its offers and gets one warning.
    """
    if mode is None:
        return offers, []
    code = _TRANSPORT_MODE_CODES[mode]
    fallback_legs = {
        leg
        for leg in ("OUTBOUND", "RETURN")
        if any(offer.leg == leg for offer in offers)
        and not any(offer.leg == leg and offer.mode in (None, code) for offer in offers)
    }
    kept = [offer for offer in offers if offer.leg in fallback_legs or offer.mode in (None, code)]
    warnings = [f"No {code} offer is available; showing all transport modes."] if fallback_legs else []
    return kept, warnings


def _matching_hotels(
    offers: list[HotelOffer], tier: str | None
) -> tuple[list[HotelOffer], list[str]]:
    """Keep the hotels of the chosen tier (hotels with no tier are kept); all of them when none match."""
    if tier is None:
        return offers, []
    code = _HOTEL_TIER_CODES[tier]
    matching = [offer for offer in offers if offer.tier in (None, code)]
    if offers and not matching:
        return offers, [f"No {code} offer is available; showing all hotel tiers."]
    return matching, []


def _unique(items: Iterable[PlaceCategory]) -> list[PlaceCategory]:
    """Keep the first occurrence of each category, preserving order."""
    ordered: list[PlaceCategory] = []
    for item in items:
        if item not in ordered:
            ordered.append(item)
    return ordered


def _search_category(
    places: Sequence[Place],
    request: TripRequest,
    category: PlaceCategory | None,
    query: str | None,
    allow_fallback: bool,
) -> list[PlaceSearchResult]:
    """Rank one category; retry without the query if an explicit category is empty.

    A market must be a food market (unless the request names a keyword). Under the nature
    theme the attractions are ranked nature places first, then the other attractions.
    """
    themes = request_themes(request)
    if category == "attraction" and NATURE_THEME in themes:
        return _nature_first(places, request, query, allow_fallback)
    results = _rank(_pool(places, request, category), request, category, query)
    if not results and query is not None and allow_fallback:
        results = _rank(_pool(places, request, category), request, category, None)
    results = _apply_specialty_boost(results)
    if category == "cafe" and NATURE_THEME in themes:
        results = _apply_view_boost(results)
    return results


def _nature_first(
    places: Sequence[Place], request: TripRequest, query: str | None, allow_fallback: bool
) -> list[PlaceSearchResult]:
    """Nature attractions first, then the other attractions, so a short nature list is filled.

    The two parts are concatenated, not merged by score, so nature places keep their place
    at the front of the list.
    """
    natural = [place for place in places if place.category == "attraction" and is_nature(place)]
    other = [place for place in places if place.category == "attraction" and not is_nature(place)]
    results = _rank(natural, request, "attraction", query) + _rank(other, request, "attraction", query)
    if not results and query is not None and allow_fallback:
        results = _rank(natural, request, "attraction", None) + _rank(other, request, "attraction", None)
    return results


def _pool(
    places: Sequence[Place], request: TripRequest, category: PlaceCategory | None
) -> Sequence[Place]:
    """The places a category search may rank, after the market filter."""
    if category == "market" and not request.keyword:
        return [place for place in places if is_food_market(place)]
    return places


def _rank(
    places: Sequence[Place],
    request: TripRequest,
    category: PlaceCategory | None,
    query: str | None,
) -> list[PlaceSearchResult]:
    return search_places(
        places,
        query=query,
        category=category,
        lat=request.center_lat,
        lon=request.center_lon,
        radius_km=request.radius_km,
    )


def _apply_specialty_boost(results: list[PlaceSearchResult]) -> list[PlaceSearchResult]:
    """Rescore restaurants: score * 0.85, plus 15 for a Hue specialty.

    The proportional scaling keeps every score at or below 100 without a cap,
    so restaurants do not saturate and tie. Non-restaurant results are unchanged.
    """
    adjusted: list[PlaceSearchResult] = []
    for result in results:
        if result.place.category == "restaurant":
            lift = _SPECIALTY_LIFT if is_hue_specialty(result.place) else 0.0
            new_score = round(result.score * _RESTAURANT_SCALE + lift, 3)
            result = result.model_copy(update={"score": new_score})
        adjusted.append(result)
    return sorted(adjusted, key=lambda result: (-result.score, result.place.id))


def _apply_view_boost(results: list[PlaceSearchResult]) -> list[PlaceSearchResult]:
    """Rescore cafes under the nature theme: score * 0.85, plus 15 for a view cafe.

    Same proportional scaling as the restaurant boost, so scores stay at or below 100. A
    score lift alone does not always beat a higher-rated plain cafe, so view cafes are also
    listed before the other cafes.
    """
    adjusted: list[PlaceSearchResult] = []
    for result in results:
        if result.place.category == "cafe":
            lift = _VIEW_CAFE_LIFT if is_view_cafe(result.place) else 0.0
            new_score = round(result.score * _RESTAURANT_SCALE + lift, 3)
            result = result.model_copy(update={"score": new_score})
        adjusted.append(result)
    return sorted(
        adjusted,
        key=lambda result: (
            result.place.category == "cafe" and not is_view_cafe(result.place),
            -result.score,
            result.place.id,
        ),
    )


def _interleave(lists: list[list[PlaceSearchResult]], limit: int) -> list[PlaceSearchResult]:
    """Take rank 1 of each list, then rank 2, and so on.

    Skips a POI already taken by id, or by normalized name (the first, higher
    ranked, occurrence is kept).
    """
    merged: list[PlaceSearchResult] = []
    seen_ids: set[str] = set()
    seen_names: set[str] = set()
    depth = max((len(items) for items in lists), default=0)
    for rank in range(depth):
        for items in lists:
            if rank >= len(items):
                continue
            candidate = items[rank]
            name_key = normalize_vietnamese(candidate.place.name)
            if candidate.place.id in seen_ids or name_key in seen_names:
                continue
            seen_ids.add(candidate.place.id)
            seen_names.add(name_key)
            merged.append(candidate)
            if len(merged) == limit:
                return merged
    return merged
