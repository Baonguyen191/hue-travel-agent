"""Web app local để duyệt tay địa điểm. Chỉ bind 127.0.0.1 (xem cli.py)."""

import datetime as dt
from collections.abc import Iterator
from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import HTMLResponse

from travel_agent.data.osm import OSM_ATTRIBUTION
from travel_agent.domain.models import Category
from travel_agent.domain.opening_hours import parse_opening_hours
from travel_agent.review.models import Review, ReviewedPlace, ReviewInput, ReviewStatus
from travel_agent.review.store import ReviewStore
from travel_agent.sources.models import AddResult, LinkInput, LinkStatus
from travel_agent.sources.store import LinkStore

STATIC_DIR = Path(__file__).parent / "static"


def get_store(request: Request) -> Iterator[ReviewStore]:
    store = ReviewStore(request.app.state.db_path)
    try:
        yield store
    finally:
        store.close()


def get_link_store(request: Request) -> Iterator[LinkStore]:
    store = LinkStore(request.app.state.db_path)
    try:
        yield store
    finally:
        store.close()


StoreDep = Annotated[ReviewStore, Depends(get_store)]
LinkStoreDep = Annotated[LinkStore, Depends(get_link_store)]


def create_app(db_path: Path) -> FastAPI:
    app = FastAPI(title="Duyệt địa điểm")
    app.state.db_path = db_path

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        return (STATIC_DIR / "index.html").read_text(encoding="utf-8")

    @app.get("/api/meta")
    def meta(store: StoreDep) -> dict[str, Any]:
        return {
            "categories": [category.value for category in Category],
            "statuses": [status.value for status in ReviewStatus],
            "sources": store.sources(),
            "attribution": OSM_ATTRIBUTION,
        }

    @app.get("/api/stats")
    def stats(store: StoreDep, source: str | None = None) -> dict[str, int]:
        return store.stats(source=source or None)

    @app.get("/api/places")
    def list_places(
        store: StoreDep,
        status: ReviewStatus | None = None,
        category: Category | None = None,
        q: str | None = None,
        source: str | None = None,
        offset: Annotated[int, Query(ge=0)] = 0,
        limit: Annotated[int, Query(ge=1, le=200)] = 50,
    ) -> dict[str, Any]:
        items, total = store.query(status, category, q, offset, limit, source=source or None)
        return {"items": [to_item(item) for item in items], "total": total}

    @app.get("/api/place")
    def get_place(place_id: str, store: StoreDep) -> dict[str, Any]:
        item = store.get(place_id)
        if item is None:
            raise HTTPException(status_code=404, detail="Không tìm thấy địa điểm")
        return to_item(item)

    @app.put("/api/reviews")
    def save_review(body: ReviewInput, store: StoreDep) -> Review:
        try:
            return store.save(body, dt.datetime.now(dt.UTC))
        except KeyError:
            raise HTTPException(status_code=404, detail="Không tìm thấy địa điểm") from None

    @app.delete("/api/reviews", status_code=204)
    def clear_review(place_id: str, store: StoreDep) -> Response:
        store.clear(place_id)
        return Response(status_code=204)

    @app.get("/links", response_class=HTMLResponse)
    def links_page() -> str:
        return (STATIC_DIR / "links.html").read_text(encoding="utf-8")

    @app.get("/api/links")
    def list_links(links: LinkStoreDep, status: LinkStatus | None = None) -> dict[str, Any]:
        return {
            "items": [link.model_dump(mode="json") for link in links.list(status)],
            "counts": links.counts(),
        }

    @app.post("/api/links", status_code=201)
    def add_links(body: LinkInput, links: LinkStoreDep) -> AddResult:
        return links.add(body, dt.datetime.now(dt.UTC))

    @app.delete("/api/links/{link_id}", status_code=204)
    def delete_link(link_id: int, links: LinkStoreDep) -> Response:
        if not links.delete(link_id):
            raise HTTPException(status_code=404, detail="Không tìm thấy link")
        return Response(status_code=204)

    return app


def to_item(reviewed: ReviewedPlace) -> dict[str, Any]:
    place = reviewed.place
    effective = reviewed.effective_place()
    hours = effective.opening_hours_raw
    return {
        "place": place.model_dump(mode="json"),
        "effective": effective.model_dump(mode="json"),
        "status": reviewed.status.value,
        "review": None if reviewed.review is None else reviewed.review.model_dump(mode="json"),
        # None = không có dữ liệu giờ; False = có nhưng parser không hiểu (coi như unknown)
        "hours_parsed": None if hours is None else parse_opening_hours(hours) is not None,
        "osm_url": (
            f"https://www.openstreetmap.org/{place.source_place_id}"
            if place.source == "osm"
            else None
        ),
    }
