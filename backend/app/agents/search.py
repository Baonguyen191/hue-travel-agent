"""Combine local Hue POIs and provider offers for a structured trip request."""

from __future__ import annotations

import asyncio

from app.providers.base import HotelProvider, ProviderTimeoutError, TransportProvider
from app.repositories.hue_places import HuePlacesRepository
from app.schemas.offer import HotelSearchRequest, TransportSearchRequest
from app.schemas.request import TripRequest
from app.schemas.search import SearchResult
from app.services.poi_search import normalize_vietnamese, search_places

_HUE_DESTINATIONS = frozenset({"hue", "thanh pho hue", "thua thien hue"})


def is_hue_destination(destination: str) -> bool:
    """Accept common Hue destination forms without treating other cities as Hue."""
    return normalize_vietnamese(destination) in _HUE_DESTINATIONS


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
        transport_task = asyncio.to_thread(
            self.transport_provider.search,
            TransportSearchRequest(
                origin=request.origin,
                destination=request.destination,
                departure_date=request.start_date,
                return_date=request.end_date,
                passengers=request.people,
            ),
        )
        hotel_task = asyncio.to_thread(
            self.hotel_provider.search,
            HotelSearchRequest(
                destination=request.destination,
                check_in=request.start_date,
                check_out=request.end_date,
                rooms=request.rooms,
                guests=request.people,
            ),
        )
        poi_result, transport_result, hotel_result = await asyncio.gather(
            poi_task, transport_task, hotel_task, return_exceptions=True
        )

        warnings: list[str] = []
        poi_candidates = self._result_or_warning(poi_result, "POI source", warnings)
        transport_offers = self._result_or_warning(transport_result, "Transport provider", warnings)
        hotel_offers = self._result_or_warning(hotel_result, "Hotel provider", warnings)

        if not poi_candidates:
            warnings.append("No Hue POIs matched the requested filters.")
        if not transport_offers:
            warnings.append("No transport quote is available; no price was inferred.")
        if not hotel_offers:
            warnings.append("No hotel quote is available; no price was inferred.")

        return SearchResult(
            status="READY" if not warnings else "PARTIAL",
            poi_candidates=poi_candidates,
            transport_offers=transport_offers,
            hotel_offers=hotel_offers,
            warnings=warnings,
        )

    def _find_pois(self, request: TripRequest):
        categories = request.categories or [None]
        query = request.keyword or " ".join(request.preferences) or None
        candidates = []
        seen_ids: set[str] = set()
        for category in categories:
            for result in search_places(
                self.places.list_all(),
                query=query,
                category=category,
                lat=request.center_lat,
                lon=request.center_lon,
                radius_km=request.radius_km,
            ):
                if result.place.id not in seen_ids:
                    seen_ids.add(result.place.id)
                    candidates.append(result)
        return sorted(candidates, key=lambda result: (-result.score, result.place.id))[:50]

    @staticmethod
    def _result_or_warning(result: object, name: str, warnings: list[str]):
        if isinstance(result, ProviderTimeoutError):
            warnings.append(f"{name} timed out; its offers were omitted.")
            return []
        if isinstance(result, Exception):
            warnings.append(f"{name} failed; its offers were omitted.")
            return []
        return result
