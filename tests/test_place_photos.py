"""Photo proxy: download once, resize to WebP, cache, and refuse anything but huetripo."""

from __future__ import annotations

import io
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.api.places import get_photo_service, get_repository  # noqa: E402
from app.main import app  # noqa: E402
from app.schemas.place import Place, PlacePhoto  # noqa: E402
from app.services.photo_fallbacks import resolve_photo  # noqa: E402
from app.services.photos import PhotoService, cache_key_for, cache_path  # noqa: E402

SOURCE = "https://huetripo.hue.gov.vn/uploads/a.jpg"
COMMONS = "https://thumb.wikimedia.org/wikipedia/commons/thumb/a/a.jpg"
AUTO = object()


def jpeg(width: int = 1200, height: int = 800) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), (122, 31, 31)).save(buffer, "JPEG")
    return buffer.getvalue()


def place(
    poi_id: str = "huetripo:1",
    photo_url: str | None = SOURCE,
    photo: object = AUTO,
    category: str = "historic",
) -> Place:
    if photo is AUTO:
        photo = PlacePhoto(kind="source", url=photo_url) if photo_url == SOURCE else None
    return Place.model_validate(
        {
            "id": poi_id,
            "name": "Đại Nội Huế",
            "category": category,
            "lat": 16.47,
            "lon": 107.58,
            "opening_hours_confidence": "UNVERIFIED",
            "price_status": "UNKNOWN",
            "source": "huetripo",
            "source_place_id": poi_id.split(":")[1],
            "collected_at": datetime(2026, 11, 1, tzinfo=timezone.utc),
            "photo_url": photo_url,
            "photo": photo,
            "raw_attributes": {},
        }
    )


class FakeRepository:
    def __init__(self, *places: Place) -> None:
        self.by_id = {item.id: item for item in places}

    def get_by_id(self, poi_id: str) -> Place | None:
        return self.by_id.get(poi_id)


class Upstream:
    """A fake huetripo: counts calls and answers with a fixed handler."""

    def __init__(self, handler) -> None:
        self.calls: list[str] = []
        self.handler = handler

    def transport(self) -> httpx.MockTransport:
        def handle(request: httpx.Request) -> httpx.Response:
            self.calls.append(str(request.url))
            return self.handler(request)

        return httpx.MockTransport(handle)


@pytest.fixture
def setup(tmp_path: Path):
    def build(handler, *places: Place):
        upstream = Upstream(handler)
        service = PhotoService(tmp_path / "cache", transport=upstream.transport())
        app.dependency_overrides[get_repository] = lambda: FakeRepository(*(places or (place(),)))
        app.dependency_overrides[get_photo_service] = lambda: service
        return TestClient(app), upstream, tmp_path / "cache"

    yield build
    app.dependency_overrides.clear()


def ok(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, content=jpeg(), headers={"content-type": "image/jpeg"})


def test_first_request_resizes_to_webp_and_second_is_served_from_cache(setup) -> None:
    client, upstream, cache = setup(ok)
    first = client.get("/api/v1/places/huetripo:1/photo", params={"w": 480})
    assert first.status_code == 200
    assert first.headers["content-type"] == "image/webp"
    assert first.headers["cache-control"] == "public, max-age=2592000, immutable"
    image = Image.open(io.BytesIO(first.content))
    assert image.format == "WEBP"
    assert image.size == (480, 320)
    second = client.get("/api/v1/places/huetripo:1/photo", params={"w": 480})
    assert second.status_code == 200
    assert second.content == first.content
    assert len(upstream.calls) == 1
    assert (cache / "huetripo_1_480.webp").exists()


def test_small_source_is_not_upscaled(setup) -> None:
    client, _, _ = setup(lambda request: httpx.Response(200, content=jpeg(300, 200)))
    response = client.get("/api/v1/places/huetripo:1/photo", params={"w": 960})
    assert response.status_code == 200
    assert Image.open(io.BytesIO(response.content)).size == (300, 200)


@pytest.mark.parametrize("params", [{"w": 500}, {"w": "abc"}, {}])
def test_bad_width_is_422(setup, params) -> None:
    client, upstream, _ = setup(ok)
    assert client.get("/api/v1/places/huetripo:1/photo", params=params).status_code == 422
    assert upstream.calls == []


def test_unknown_place_and_place_without_photo_are_404(setup) -> None:
    client, upstream, _ = setup(ok, place("huetripo:2", photo_url=None))
    assert client.get("/api/v1/places/huetripo:9/photo", params={"w": 160}).status_code == 404
    assert client.get("/api/v1/places/huetripo:2/photo", params={"w": 160}).status_code == 404
    assert upstream.calls == []


@pytest.mark.parametrize(
    "url",
    [
        "https://evil.example/a.jpg",
        "http://huetripo.hue.gov.vn/a.jpg",
        "https://huetripo.hue.gov.vn.evil.example/a.jpg",
        "file:///etc/passwd",
    ],
)
def test_disallowed_source_is_404_without_network(setup, url) -> None:
    client, upstream, _ = setup(ok, place(photo_url=url, photo=PlacePhoto(kind="source", url=url)))
    assert client.get("/api/v1/places/huetripo:1/photo", params={"w": 160}).status_code == 404
    assert upstream.calls == []


def test_redirect_off_host_is_502(setup) -> None:
    client, _, cache = setup(
        lambda request: httpx.Response(302, headers={"location": "https://evil.example/x.jpg"}),
        place(category="park"),  # no curated stand-in for this category, so the failure stays a 502
    )
    assert client.get("/api/v1/places/huetripo:1/photo", params={"w": 160}).status_code == 502
    assert not cache.exists() or list(cache.iterdir()) == []


def timeout(request: httpx.Request) -> httpx.Response:
    raise httpx.ReadTimeout("slow", request=request)


@pytest.mark.parametrize(
    "handler",
    [
        lambda request: httpx.Response(500),
        timeout,
        lambda request: httpx.Response(200, content=b"not an image"),
        lambda request: httpx.Response(200, content=b"0" * (15 * 1024 * 1024 + 1)),
    ],
    ids=["status-500", "timeout", "garbage", "oversize"],
)
def test_upstream_failures_are_502_and_never_cached(setup, handler) -> None:
    client, _, cache = setup(handler, place(category="park"))  # no curated stand-in, so the failure stays a 502
    assert client.get("/api/v1/places/huetripo:1/photo", params={"w": 160}).status_code == 502
    assert not cache.exists() or list(cache.iterdir()) == []


def deny_replace(*args, **kwargs):
    raise PermissionError("target is open in another request")


def test_concurrent_cache_write_keeps_the_file_the_other_request_wrote(setup, monkeypatch) -> None:
    """The other request finished and is streaming the file while this one tries to replace it."""
    cache_holder: list[Path] = []

    def handler(request: httpx.Request) -> httpx.Response:
        # The competing request lands its file while this request is still downloading.
        target = cache_path(cache_holder[0], "huetripo:1", 160)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"RIFFother")
        return httpx.Response(200, content=jpeg())

    client, _, cache = setup(handler)
    cache_holder.append(cache)
    monkeypatch.setattr("app.services.photos.os.replace", deny_replace)
    response = client.get("/api/v1/places/huetripo:1/photo", params={"w": 160})
    assert response.status_code == 200
    assert response.content == b"RIFFother"
    assert list(cache.glob("*.tmp")) == []


def test_unwritable_cache_without_a_winner_is_502_and_leaves_no_temp_file(setup, monkeypatch) -> None:
    client, _, cache = setup(ok)
    monkeypatch.setattr("app.services.photos.os.replace", deny_replace)
    assert client.get("/api/v1/places/huetripo:1/photo", params={"w": 160}).status_code == 502
    assert list(cache.glob("*.tmp")) == []


def test_very_tall_source_is_fitted_into_the_webp_limit(setup) -> None:
    client, _, _ = setup(lambda request: httpx.Response(200, content=jpeg(1000, 20000)))
    response = client.get("/api/v1/places/huetripo:1/photo", params={"w": 160})
    assert response.status_code == 200
    width, height = Image.open(io.BytesIO(response.content)).size
    assert width <= 160
    assert height <= 320


def test_place_without_source_photo_is_served_from_commons(setup) -> None:
    illustrative = resolve_photo("huetripo:88", "Bún bò", "restaurant", None)
    restaurant = place("huetripo:88", photo_url=None, photo=illustrative, category="restaurant")
    client, upstream, cache = setup(ok, restaurant)
    response = client.get("/api/v1/places/huetripo:88/photo", params={"w": 480})
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/webp"
    assert response.headers["cache-control"] == "public, max-age=2592000, immutable"
    assert upstream.calls == [restaurant.photo.url]
    cached = list(cache.glob("*.webp"))
    assert len(cached) == 1
    assert cached[0].name.startswith("commons_")
    assert cached[0].name == f"{cache_key_for('huetripo:88', restaurant.photo)}_480.webp"


def test_places_sharing_one_commons_photo_share_one_download(setup) -> None:
    shared = PlacePhoto(kind="commons_illustrative", url=COMMONS)
    first = place("huetripo:a", photo_url=None, photo=shared, category="cafe")
    second = place("huetripo:b", photo_url=None, photo=shared, category="cafe")
    client, upstream, cache = setup(ok, first, second)
    assert client.get("/api/v1/places/huetripo:a/photo", params={"w": 160}).status_code == 200
    assert client.get("/api/v1/places/huetripo:b/photo", params={"w": 160}).status_code == 200
    assert upstream.calls == [COMMONS]
    assert len(list(cache.glob("*.webp"))) == 1


def test_failed_source_falls_back_to_illustrative_photo_and_is_not_cached(setup) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "huetripo.hue.gov.vn":
            return httpx.Response(500)
        return ok(request)

    client, upstream, cache = setup(handler, place("huetripo:1", category="historic"))
    response = client.get("/api/v1/places/huetripo:1/photo", params={"w": 160})
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/webp"
    assert response.headers["cache-control"] == "public, max-age=3600"
    assert upstream.calls[0] == SOURCE
    assert upstream.calls[1].startswith("https://thumb.wikimedia.org/")
    names = [path.name for path in cache.glob("*.webp")]
    assert len(names) == 1
    assert names[0].startswith("commons_")
    assert not (cache / "huetripo_1_160.webp").exists()
