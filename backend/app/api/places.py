"""Read-only endpoints for POIs from the Hue source dataset."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.config import hue_database_path
from app.repositories.hue_places import HuePlacesRepository
from app.schemas.place import Place, PlaceCategory, PlacePage, PlaceSearchPage
from app.services.poi_search import search_places

router = APIRouter(prefix="/api/v1/places", tags=["places"])


def get_repository() -> HuePlacesRepository:
    return HuePlacesRepository(hue_database_path())


Repository = Annotated[HuePlacesRepository, Depends(get_repository)]


@router.get("", response_model=PlacePage)
def list_places(
    repository: Repository,
    category: PlaceCategory | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> PlacePage:
    """List source POIs, optionally restricted to an exact source category."""
    try:
        items = repository.list_page(category=category, limit=limit, offset=offset)
        total = repository.count(category=category)
    except FileNotFoundError as error:
        raise HTTPException(status_code=503, detail="Hue SQLite source file is unavailable.") from error
    return PlacePage(items=items, total=total, limit=limit, offset=offset)


@router.get("/search", response_model=PlaceSearchPage)
def search(
    repository: Repository,
    q: Annotated[str, Query(min_length=1, max_length=200)],
    category: PlaceCategory | None = None,
    lat: Annotated[float | None, Query(ge=-90, le=90)] = None,
    lon: Annotated[float | None, Query(ge=-180, le=180)] = None,
    radius_km: Annotated[float | None, Query(gt=0, le=100)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> PlaceSearchPage:
    """Search Hue POIs locally, including Vietnamese diacritic-insensitive text."""
    try:
        results = search_places(
            repository.list_all(), category=category, query=q, lat=lat, lon=lon, radius_km=radius_km
        )
    except FileNotFoundError as error:
        raise HTTPException(status_code=503, detail="Hue SQLite source file is unavailable.") from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return PlaceSearchPage(items=results[offset : offset + limit], total=len(results), limit=limit, offset=offset)


@router.get("/nearby", response_model=PlaceSearchPage)
def nearby(
    repository: Repository,
    lat: Annotated[float, Query(ge=-90, le=90)],
    lon: Annotated[float, Query(ge=-180, le=180)],
    radius_km: Annotated[float, Query(gt=0, le=100)] = 5,
    category: PlaceCategory | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> PlaceSearchPage:
    """Return POIs ordered by straight-line proximity, within a requested radius."""
    try:
        results = search_places(
            repository.list_all(), category=category, lat=lat, lon=lon, radius_km=radius_km
        )
    except FileNotFoundError as error:
        raise HTTPException(status_code=503, detail="Hue SQLite source file is unavailable.") from error
    return PlaceSearchPage(items=results[offset : offset + limit], total=len(results), limit=limit, offset=offset)


@router.get("/{poi_id}", response_model=Place)
def get_place(poi_id: str, repository: Repository) -> Place:
    """Return one POI by its original SQLite ID."""
    try:
        place = repository.get_by_id(poi_id)
    except FileNotFoundError as error:
        raise HTTPException(status_code=503, detail="Hue SQLite source file is unavailable.") from error
    if place is None:
        raise HTTPException(status_code=404, detail="POI was not found in the Hue source.")
    return place
