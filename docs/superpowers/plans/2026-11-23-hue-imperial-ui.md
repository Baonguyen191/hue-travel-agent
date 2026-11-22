# Huế "Cung đình" UI with Place Photos — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restyle the whole React frontend in one Huế imperial design system and show a place photo
wherever a place appears, served by a new backend endpoint that resizes and caches the source photos.

**Architecture:** A FastAPI endpoint `GET /api/v1/places/{poi_id}/photo?w=` downloads the POI's
`photo_url` from huetripo once, resizes it with Pillow to WebP and caches it on disk. The frontend
gets Tailwind v4 theme tokens, Google Fonts, CSS ornaments and a small `components/ui/` kit
(`Button`, `Chip`, `Card`, `Notice`, `PlacePhoto` with SVG fallbacks). Pages are then restyled
batch by batch; texts, routes, logic and API calls stay the same.

**Tech Stack:** FastAPI, httpx, Pillow, pytest; React 18, TypeScript, Tailwind CSS v4, Vite, Vitest,
Testing Library, react-leaflet.

**Spec:** `docs/superpowers/specs/2026-11-23-hue-imperial-ui-design.md`

## Global Constraints

- Photo endpoint widths: exactly `160`, `480`, `960`; anything else (or missing) is 422.
- Photo source host: exactly `huetripo.hue.gov.vn` over `https`; no other URL is ever fetched.
- Photo download: timeout 10 s, at most 15 MB, redirects followed only to the same host (max 3).
- Cache: `backend/data/photo_cache/{safe poi id}_{w}.webp`, WebP quality 80, temp file + `os.replace`; failures are never cached.
- Photo response headers: `Content-Type: image/webp`, `Cache-Control: public, max-age=2592000, immutable`.
- Status codes: unknown POI / no `photo_url` / disallowed host → 404; upstream error, timeout, oversize, undecodable → 502.
- Colour tokens (Tailwind `@theme` names → value): `son #7A1F1F`, `son-dark #5E1616`, `son-soft #F6E1DC`, `kim #B8913F`, `kim-soft #EFE3C8`, `giay #F6EFE1`, `nga #FFFAF0`, `vien #EAD9B0`, `muc #2B1A12`, `muc-soft #6D5A43`, `reu #3F5A3A`, `reu-soft #E3E9DC`, `on-son #FBECC8`, `canh-bao #FBF1DC`.
- `kim` is never a text colour on a light background. Text on `son` is `on-son` or `nga`; text on `kim` is `muc`.
- Fonts: Noto Serif 600/700 (headings, place names, logo), Be Vietnam Pro 400/500/600/700 (everything else), Google Fonts `display=swap`.
- Every existing Vietnamese text, aria label, role, route and API call is kept unless a task says otherwise.
- No Tailwind default palette classes (`slate-`, `teal-`, `amber-`, `emerald-`, `violet-`, `red-`, `rose-`, `indigo-`, `gray-`) remain in `frontend/src` after Task 7, test files included.
- Commits end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Never push.
- Backend tests: `.venv/Scripts/python -m pytest -q` from the repo root (baseline 685 passed). Frontend: `npx vitest run` and `npm run build` from `frontend/` (baseline 22 files, 177 tests).

## File map

| File | Task | Responsibility |
|---|---|---|
| `backend/app/services/photos.py` (new) | 1 | download, validate, resize, cache |
| `backend/app/api/places.py` | 1 | `/{poi_id}/photo` route, `get_photo_service` dependency |
| `backend/app/core/config.py` | 1 | `photo_cache_dir()` |
| `backend/app/chat/schemas.py`, `backend/app/chat/cards.py` | 1 | `PlanItem.poi_id` |
| `backend/requirements.txt`, `.gitignore` | 1 | Pillow; cache dir ignored |
| `tests/test_place_photos.py` (new), `tests/test_chat_service.py` | 1 | backend tests |
| `frontend/index.html`, `frontend/src/index.css` | 2 | fonts, tokens, ornaments |
| `frontend/src/components/ui/*` (new) | 2, 3 | UI kit, tone map, photo and illustrations |
| `frontend/src/lib/labels.ts` | 2 | harmonised category colours |
| Layout, chat page and chat components | 4 | |
| Plan layout, itinerary tab, itinerary map | 5 | |
| Budget tab, booking tab, notices, toast, skeletons | 6 | |
| Explore, place card, chips, places map, place detail, request page, form, 404 | 7 | |
| — | 8 | visual check and fixes |

## Restyle mapping (Tasks 4–7)

Apply this mapping to every file a restyle task touches. It is the single source for "what replaces
what".

| Old | New |
|---|---|
| page or panel background `bg-slate-50`, `bg-slate-100`, `bg-slate-100/60` | `bg-giay` (page-level) or `bg-nga` (inside a card) |
| card `rounded-lg border border-slate-200 bg-white p-4 shadow-sm` | `<Card>` (or `cardClass()` on a semantic element) |
| `border-slate-200`, `border-slate-300`, `ring-slate-200` | `border-vien`, `ring-vien` |
| `text-slate-900`, `text-slate-800` | `text-muc` |
| `text-slate-700`, `text-slate-600`, `text-slate-500` | `text-muc-soft` |
| h1 / h2 / h3 headings | add `font-serif text-son` (keep the size classes) |
| teal primary buttons | `<Button>` or `buttonClass("primary", size)` |
| teal outline buttons | `buttonClass("outline", size)` |
| teal text links (`text-teal-700 underline`) | `LINK` from `components/ui/tone.ts` |
| amber warning boxes | `<Notice variant="warning">` |
| red error boxes | `<Notice variant="error">` |
| emerald success boxes | `<Notice variant="success">` |
| local `TONE_CLASS` maps | `TONE_CLASS` imported from `components/ui/tone.ts` |
| violet "MÔ PHỎNG" badge | `<MockBadge />` |
| `focus:border-teal-600 focus:ring-teal-200` | `focus:border-kim focus:ring-kim/40` |
| category pill `bg-slate-100 text-slate-700` | `<CategoryChip category={…} />` |

---

### Task 1: Backend photo endpoint and `poi_id` in chat plan items

**Files:**
- Create: `backend/app/services/photos.py`
- Modify: `backend/app/api/places.py`, `backend/app/core/config.py`, `backend/app/chat/schemas.py` (`PlanItem`), `backend/app/chat/cards.py:76-77` (`_item`), `backend/requirements.txt`, `.gitignore`
- Test: `tests/test_place_photos.py` (new), `tests/test_chat_service.py`

**Interfaces:**
- Produces: `GET /api/v1/places/{poi_id}/photo?w=160|480|960` → `image/webp`; `PlanItem.poi_id: str | None`; `PhotoService(cache_dir: Path, transport: httpx.BaseTransport | None = None)` with `.get(poi_id: str, photo_url: str | None, width: int) -> Path`; `get_photo_service()` FastAPI dependency in `app.api.places`.

- [ ] **Step 1: Install Pillow**

Add the line `Pillow>=10.4` to `backend/requirements.txt` (keep alphabetical order if the file is sorted), then run `.venv/Scripts/python -m pip install "Pillow>=10.4"`.
Add to `.gitignore` under the other `backend/data/` lines: `backend/data/photo_cache/`.

- [ ] **Step 2: Write the failing tests** — `tests/test_place_photos.py`

```python
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
from app.schemas.place import Place  # noqa: E402
from app.services.photos import PhotoService  # noqa: E402

SOURCE = "https://huetripo.hue.gov.vn/uploads/a.jpg"


def jpeg(width: int = 1200, height: int = 800) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), (122, 31, 31)).save(buffer, "JPEG")
    return buffer.getvalue()


def place(poi_id: str = "huetripo:1", photo_url: str | None = SOURCE) -> Place:
    return Place.model_validate(
        {
            "id": poi_id,
            "name": "Đại Nội Huế",
            "category": "historic",
            "lat": 16.47,
            "lon": 107.58,
            "opening_hours_confidence": "UNVERIFIED",
            "price_status": "UNKNOWN",
            "source": "huetripo",
            "source_place_id": poi_id.split(":")[1],
            "collected_at": datetime(2026, 11, 1, tzinfo=timezone.utc),
            "photo_url": photo_url,
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
    client, upstream, _ = setup(ok, place(photo_url=url))
    assert client.get("/api/v1/places/huetripo:1/photo", params={"w": 160}).status_code == 404
    assert upstream.calls == []


def test_redirect_off_host_is_502(setup) -> None:
    client, _, cache = setup(lambda request: httpx.Response(302, headers={"location": "https://evil.example/x.jpg"}))
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
    client, _, cache = setup(handler)
    assert client.get("/api/v1/places/huetripo:1/photo", params={"w": 160}).status_code == 502
    assert not cache.exists() or list(cache.iterdir()) == []
```

Also add to `tests/test_chat_service.py`, next to the other plan-card tests, a test that uses the
existing `_plan_card(reply)` helper and the existing plan fixture in that file, and asserts that at
least one item has a `poi_id` starting with `"huetripo:"` and that every item whose `kind` is
`"MEAL_BREAK"` has `poi_id is None`.

- [ ] **Step 3: Run tests to verify they fail**

Run: `.venv/Scripts/python -m pytest -q tests/test_place_photos.py`
Expected: FAIL with `ImportError: cannot import name 'get_photo_service'` (or `No module named 'app.services.photos'`).

- [ ] **Step 4: Implement** `backend/app/services/photos.py`

```python
"""Resized, cached copies of the source photos of Huế POIs.

Only `photo_url` values on huetripo.hue.gov.vn over https are fetched, so a client can never make
the server download an arbitrary URL. Failures are not cached; the next request tries again.
"""

from __future__ import annotations

import io
import logging
import os
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from PIL import Image, ImageOps, UnidentifiedImageError

ALLOWED_HOST = "huetripo.hue.gov.vn"
WIDTHS = (160, 480, 960)
MAX_BYTES = 15 * 1024 * 1024
TIMEOUT_SECONDS = 10.0
MAX_REDIRECTS = 3
WEBP_QUALITY = 80

logger = logging.getLogger(__name__)


class PhotoUnavailable(Exception):
    """No photo can be served for this place (HTTP 404)."""


class PhotoUpstreamError(Exception):
    """The source photo could not be fetched or decoded (HTTP 502)."""


def allowed_source(url: str | None) -> bool:
    if not url:
        return False
    parts = urlsplit(url)
    return parts.scheme == "https" and parts.hostname == ALLOWED_HOST


def cache_path(cache_dir: Path, poi_id: str, width: int) -> Path:
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in poi_id)
    return cache_dir / f"{safe}_{width}.webp"


def resize_to_webp(data: bytes, width: int) -> bytes:
    """Fit the image to `width` (never upscale), keep the aspect ratio, encode WebP."""
    try:
        with Image.open(io.BytesIO(data)) as source:
            image = ImageOps.exif_transpose(source).convert("RGB")
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as error:
        raise PhotoUpstreamError(f"cannot decode photo: {error}") from error
    if image.width > width:
        height = max(1, round(image.height * width / image.width))
        image = image.resize((width, height), Image.Resampling.LANCZOS)
    out = io.BytesIO()
    image.save(out, "WEBP", quality=WEBP_QUALITY)
    return out.getvalue()


class PhotoService:
    """Safe to share across FastAPI's thread pool: the cache write is atomic."""

    def __init__(self, cache_dir: Path, transport: httpx.BaseTransport | None = None) -> None:
        self.cache_dir = cache_dir
        self._client = httpx.Client(timeout=TIMEOUT_SECONDS, transport=transport, follow_redirects=False)

    def get(self, poi_id: str, photo_url: str | None, width: int) -> Path:
        if not allowed_source(photo_url):
            if photo_url:
                logger.warning("photo source not allowed for %s: %s", poi_id, photo_url)
            raise PhotoUnavailable(poi_id)
        target = cache_path(self.cache_dir, poi_id, width)
        if target.exists():
            return target
        encoded = resize_to_webp(self._download(photo_url), width)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        handle, temp_name = tempfile.mkstemp(dir=self.cache_dir, suffix=".tmp")
        try:
            with os.fdopen(handle, "wb") as temp_file:
                temp_file.write(encoded)
            os.replace(temp_name, target)
        except BaseException:
            Path(temp_name).unlink(missing_ok=True)
            raise
        return target

    def _download(self, url: str) -> bytes:
        current = url
        try:
            for _ in range(MAX_REDIRECTS + 1):
                with self._client.stream("GET", current) as response:
                    if response.is_redirect:
                        location = str(response.next_request.url) if response.next_request else ""
                        if not allowed_source(location):
                            raise PhotoUpstreamError(f"redirect off the allowed host: {location}")
                        current = location
                        continue
                    if response.status_code != 200:
                        raise PhotoUpstreamError(f"upstream status {response.status_code}")
                    chunks: list[bytes] = []
                    size = 0
                    for chunk in response.iter_bytes():
                        size += len(chunk)
                        if size > MAX_BYTES:
                            raise PhotoUpstreamError("source photo is larger than 15 MB")
                        chunks.append(chunk)
                    return b"".join(chunks)
            raise PhotoUpstreamError("too many redirects")
        except httpx.HTTPError as error:
            raise PhotoUpstreamError(str(error)) from error
```

In `backend/app/core/config.py`, next to `hue_database_path`:

```python
def photo_cache_dir() -> Path:
    """Where resized place photos are cached; PHOTO_CACHE_DIR overrides it."""
    configured = os.environ.get("PHOTO_CACHE_DIR")
    return Path(configured) if configured else DATA_DIR / "photo_cache"
```

In `backend/app/api/places.py` add the imports `import functools`, `import logging`,
`from fastapi.responses import FileResponse`, `photo_cache_dir` from `app.core.config`, and
`from app.services.photos import WIDTHS, PhotoService, PhotoUnavailable, PhotoUpstreamError`; add
`logger = logging.getLogger(__name__)`; then, after `get_place`:

```python
@functools.cache
def get_photo_service() -> PhotoService:
    return PhotoService(photo_cache_dir())


PHOTO_CACHE_CONTROL = "public, max-age=2592000, immutable"


@router.get("/{poi_id}/photo", response_class=FileResponse)
def get_place_photo(
    poi_id: str,
    repository: Repository,
    photos: Annotated[PhotoService, Depends(get_photo_service)],
    w: Annotated[int, Query(description="Width in pixels: 160, 480 or 960")],
) -> FileResponse:
    """A resized WebP copy of the POI's source photo, cached on disk after the first request."""
    if w not in WIDTHS:
        raise HTTPException(status_code=422, detail=f"w must be one of {list(WIDTHS)}.")
    try:
        place = repository.get_by_id(poi_id)
    except FileNotFoundError as error:
        raise HTTPException(status_code=503, detail="Hue SQLite source file is unavailable.") from error
    if place is None:
        raise HTTPException(status_code=404, detail="POI was not found in the Hue source.")
    try:
        path = photos.get(poi_id, place.photo_url, w)
    except PhotoUnavailable as error:
        raise HTTPException(status_code=404, detail="This place has no photo.") from error
    except PhotoUpstreamError as error:
        logger.warning("photo for %s unavailable: %s", poi_id, error)
        raise HTTPException(status_code=502, detail="The source photo could not be loaded.") from error
    return FileResponse(path, media_type="image/webp", headers={"Cache-Control": PHOTO_CACHE_CONTROL})
```

In `backend/app/chat/schemas.py`, `PlanItem` gets a last field `poi_id: str | None = None`. In
`backend/app/chat/cards.py`:

```python
def _item(event: ItineraryEvent) -> PlanItem:
    return PlanItem(
        time=event.start_at.strftime("%H:%M"), name=event.name, kind=event.kind, meal=event.meal, poi_id=event.poi_id
    )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/Scripts/python -m pytest -q tests/test_place_photos.py tests/test_chat_service.py` — PASS.
Run: `.venv/Scripts/python -m pytest -q` — all pass (685 + new).

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/photos.py backend/app/api/places.py backend/app/core/config.py backend/app/chat/schemas.py backend/app/chat/cards.py backend/requirements.txt .gitignore tests/test_place_photos.py tests/test_chat_service.py
git commit -m "feat(places): resized cached place photos and poi_id in chat plan items"
```

---

### Task 2: Design tokens, fonts, ornaments and the UI kit

**Files:**
- Modify: `frontend/index.html`, `frontend/src/index.css`, `frontend/src/lib/labels.ts:4-13`
- Create: `frontend/src/components/ui/Button.tsx`, `Chip.tsx`, `Card.tsx`, `SectionHeading.tsx`, `Ornament.tsx`, `MockBadge.tsx`, `Notice.tsx`, `tone.ts`, `index.ts`
- Test: `frontend/src/components/ui/ui.test.tsx`

**Interfaces:**
- Produces (all exported from `components/ui/index.ts`): `Button`, `buttonClass(variant?, size?)`, `ButtonVariant = "primary" | "secondary" | "outline"`, `Chip`, `CategoryChip`, `Card`, `cardClass(extra?)`, `SectionHeading`, `Ornament`, `MockBadge`, `Notice`, and from `tone.ts`: `TONE_CLASS: Record<StatusTone, string>`, `PILL`, `LINK`.

- [ ] **Step 1: Write the failing test** — `frontend/src/components/ui/ui.test.tsx`

```tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Button, CategoryChip, MockBadge, Notice, SectionHeading, buttonClass } from ".";

describe("ui kit", () => {
  it("renders a primary button by default with the son colour and type=button", () => {
    render(<Button>Duyệt</Button>);
    const button = screen.getByRole("button", { name: "Duyệt" });
    expect(button).toHaveAttribute("type", "button");
    expect(button.className).toContain("bg-son");
  });

  it("gives outline and secondary variants their own colours", () => {
    expect(buttonClass("outline")).toContain("border-son");
    expect(buttonClass("secondary")).toContain("bg-kim");
  });

  it("labels a category chip in Vietnamese", () => {
    render(<CategoryChip category="historic" />);
    expect(screen.getByText("Di tích")).toBeInTheDocument();
  });

  it("shows the simulated badge text", () => {
    render(<MockBadge />);
    expect(screen.getByText("MÔ PHỎNG")).toBeInTheDocument();
  });

  it("passes role through on a notice", () => {
    render(
      <Notice variant="error" role="alert">
        Lỗi
      </Notice>,
    );
    expect(screen.getByRole("alert")).toHaveTextContent("Lỗi");
  });

  it("renders the heading level asked for in the serif font", () => {
    render(<SectionHeading as="h2">Ngày 1</SectionHeading>);
    const heading = screen.getByRole("heading", { level: 2, name: "Ngày 1" });
    expect(heading.className).toContain("font-serif");
  });
});
```

- [ ] **Step 2: Run to verify it fails** — `npx vitest run src/components/ui` → FAIL (module `.` not found).

- [ ] **Step 3: Implement**

`frontend/index.html` — inside `<head>`, before the existing stylesheet/script tags:

```html
<link rel="preconnect" href="https://fonts.googleapis.com" />
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
<link
  href="https://fonts.googleapis.com/css2?family=Be+Vietnam+Pro:wght@400;500;600;700&family=Noto+Serif:wght@600;700&display=swap"
  rel="stylesheet"
/>
<meta name="theme-color" content="#7a1f1f" />
```

`frontend/src/index.css` (replace the whole file):

```css
@import "tailwindcss";

@theme {
  --color-son: #7a1f1f;
  --color-son-dark: #5e1616;
  --color-son-soft: #f6e1dc;
  --color-kim: #b8913f;
  --color-kim-soft: #efe3c8;
  --color-giay: #f6efe1;
  --color-nga: #fffaf0;
  --color-vien: #ead9b0;
  --color-muc: #2b1a12;
  --color-muc-soft: #6d5a43;
  --color-reu: #3f5a3a;
  --color-reu-soft: #e3e9dc;
  --color-on-son: #fbecc8;
  --color-canh-bao: #fbf1dc;
  --font-serif: "Noto Serif", Georgia, serif;
  --font-sans: "Be Vietnam Pro", system-ui, sans-serif;
}

body {
  background-color: var(--color-giay);
  color: var(--color-muc);
  font-family: var(--font-sans);
}

/* Hồi văn band: son and kim stripes. */
.ornament-band {
  height: 6px;
  background: repeating-linear-gradient(
    90deg,
    var(--color-kim) 0 10px,
    transparent 10px 14px,
    var(--color-son) 14px 18px,
    transparent 18px 22px
  );
}

/* Ô hộc grid: faint kim lines for heroes and empty states. */
.o-hoc {
  background-image:
    linear-gradient(90deg, rgb(184 145 63 / 0.14) 1px, transparent 1px),
    linear-gradient(rgb(184 145 63 / 0.14) 1px, transparent 1px);
  background-size: 18px 18px;
}

.leaflet-container {
  font-family: var(--font-sans);
}
```

`frontend/src/lib/labels.ts` — replace only the `color` values in `CATEGORY_OPTIONS` (labels and
order unchanged): restaurant `#a23b2a`, cafe `#7b4f2c`, historic `#7a1f1f`, attraction `#2f6f73`,
market `#b8742f`, religious `#7b4a8e`, park `#3f5a3a`, museum `#5b4636`. Update the comment to
"Category order and colours (Cung đình palette) for chips, markers and legends."

`frontend/src/components/ui/tone.ts`:

```ts
import type { StatusTone } from "../../lib/plan";

/** Status pill colours shared by the chat cards, plan header, budget and booking tabs. */
export const TONE_CLASS: Record<StatusTone, string> = {
  approved: "bg-reu-soft text-reu ring-reu/30",
  waiting: "bg-canh-bao text-muc ring-kim/50",
  failed: "bg-son-soft text-son ring-son/30",
  neutral: "bg-nga text-muc-soft ring-vien",
};

export const PILL = "inline-block rounded-full px-2.5 py-0.5 text-xs font-semibold ring-1";

/** Inline text link: son text, kim underline. */
export const LINK = "font-medium text-son underline decoration-kim underline-offset-2 hover:text-son-dark";
```

`frontend/src/components/ui/Button.tsx`:

```tsx
import type { ButtonHTMLAttributes } from "react";

export type ButtonVariant = "primary" | "secondary" | "outline";
export type ButtonSize = "sm" | "md";

const VARIANT: Record<ButtonVariant, string> = {
  primary: "bg-son text-on-son hover:bg-son-dark",
  secondary: "bg-kim text-muc hover:brightness-95",
  outline: "border-[1.5px] border-son bg-transparent text-son hover:bg-son-soft",
};

const SIZE: Record<ButtonSize, string> = {
  sm: "px-3 py-1.5 text-sm",
  md: "px-5 py-2.5 text-base",
};

/** Class string for anything that should look like a button (buttons, links, NavLinks). */
export function buttonClass(variant: ButtonVariant = "primary", size: ButtonSize = "md"): string {
  return [
    "inline-flex items-center justify-center gap-2 rounded-full font-semibold transition-colors",
    "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-kim",
    "disabled:cursor-not-allowed disabled:opacity-50",
    VARIANT[variant],
    SIZE[size],
  ].join(" ");
}

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
}

export function Button({ variant = "primary", size = "md", className = "", type = "button", ...rest }: ButtonProps) {
  return <button type={type} className={`${buttonClass(variant, size)} ${className}`.trim()} {...rest} />;
}
```

`frontend/src/components/ui/Chip.tsx`:

```tsx
import type { ReactNode } from "react";
import { CATEGORY_LABEL } from "../../lib/labels";

export type ChipTone = "son" | "soft" | "reu" | "neutral";

const TONE: Record<ChipTone, string> = {
  son: "bg-son text-on-son",
  soft: "bg-kim-soft text-son",
  reu: "bg-reu-soft text-reu",
  neutral: "bg-nga text-muc-soft ring-1 ring-vien",
};

export function Chip({ tone = "soft", children, className = "" }: { tone?: ChipTone; children: ReactNode; className?: string }) {
  return (
    <span className={`inline-block rounded-full px-2.5 py-0.5 text-xs font-medium ${TONE[tone]} ${className}`.trim()}>
      {children}
    </span>
  );
}

const CATEGORY_TONE: Record<string, ChipTone> = {
  historic: "son",
  religious: "son",
  museum: "son",
  restaurant: "soft",
  cafe: "soft",
  market: "soft",
  park: "reu",
  attraction: "reu",
};

/** A chip with the Vietnamese category label; unknown categories show their code. */
export function CategoryChip({ category, className }: { category: string | null; className?: string }) {
  if (!category) return null;
  const label = CATEGORY_LABEL[category as keyof typeof CATEGORY_LABEL] ?? category;
  return (
    <Chip tone={CATEGORY_TONE[category] ?? "neutral"} className={className}>
      {label}
    </Chip>
  );
}
```

`frontend/src/components/ui/Card.tsx`:

```tsx
import type { HTMLAttributes } from "react";
import { Ornament } from "./Ornament";

export function cardClass(extra = ""): string {
  return `overflow-hidden rounded-2xl border border-vien bg-nga shadow-[0_1px_3px_rgb(43_26_18/0.06)] ${extra}`.trim();
}

interface CardProps extends HTMLAttributes<HTMLDivElement> {
  /** Draw the hồi văn band along the top edge. */
  ornament?: boolean;
}

export function Card({ ornament = false, className = "", children, ...rest }: CardProps) {
  return (
    <div className={cardClass(className)} {...rest}>
      {ornament ? <Ornament /> : null}
      {children}
    </div>
  );
}
```

`frontend/src/components/ui/Ornament.tsx`:

```tsx
export function Ornament({ className = "" }: { className?: string }) {
  return <div aria-hidden="true" className={`ornament-band ${className}`.trim()} />;
}
```

`frontend/src/components/ui/SectionHeading.tsx`:

```tsx
import type { ReactNode } from "react";

type Level = "h1" | "h2" | "h3" | "h4";

const SIZE: Record<Level, string> = {
  h1: "text-2xl md:text-3xl",
  h2: "text-lg md:text-xl",
  h3: "text-base md:text-lg",
  h4: "text-base",
};

export function SectionHeading({
  as = "h2",
  id,
  className = "",
  children,
}: {
  as?: Level;
  id?: string;
  className?: string;
  children: ReactNode;
}) {
  const Tag = as;
  return (
    <Tag id={id} className={`font-serif font-semibold leading-snug text-son ${SIZE[as]} ${className}`.trim()}>
      {children}
    </Tag>
  );
}
```

`frontend/src/components/ui/MockBadge.tsx`:

```tsx
/** Marks transport, hotel and booking data that comes from mock providers. */
export function MockBadge({ className = "" }: { className?: string }) {
  return (
    <span className={`rounded bg-muc px-1.5 py-0.5 text-[11px] font-semibold tracking-wider text-on-son ${className}`.trim()}>
      MÔ PHỎNG
    </span>
  );
}
```

`frontend/src/components/ui/Notice.tsx`:

```tsx
import type { HTMLAttributes } from "react";

export type NoticeVariant = "warning" | "error" | "success";

const VARIANT: Record<NoticeVariant, string> = {
  warning: "border-kim bg-canh-bao",
  error: "border-son bg-son-soft",
  success: "border-reu bg-reu-soft",
};

interface NoticeProps extends HTMLAttributes<HTMLDivElement> {
  variant: NoticeVariant;
}

/** A bar notice: coloured left border, muc text. Pass role="alert" or role="status" where needed. */
export function Notice({ variant, className = "", children, ...rest }: NoticeProps) {
  return (
    <div className={`rounded-md border-l-4 px-4 py-3 text-sm text-muc ${VARIANT[variant]} ${className}`.trim()} {...rest}>
      {children}
    </div>
  );
}
```

`frontend/src/components/ui/index.ts`:

```ts
export { Button, buttonClass, type ButtonVariant, type ButtonSize } from "./Button";
export { Card, cardClass } from "./Card";
export { CategoryChip, Chip, type ChipTone } from "./Chip";
export { MockBadge } from "./MockBadge";
export { Notice, type NoticeVariant } from "./Notice";
export { Ornament } from "./Ornament";
export { SectionHeading } from "./SectionHeading";
export { LINK, PILL, TONE_CLASS } from "./tone";
```

- [ ] **Step 4: Run** `npx vitest run` (all 22 files + new pass) and `npm run build` (no type errors).

- [ ] **Step 5: Commit**

```bash
git add frontend/index.html frontend/src/index.css frontend/src/lib/labels.ts frontend/src/components/ui
git commit -m "feat(frontend): Cung đình design tokens, fonts, ornaments and UI kit"
```

---

### Task 3: `PlacePhoto` and category illustrations

**Files:**
- Create: `frontend/src/components/ui/PlacePhoto.tsx`, `frontend/src/components/ui/PlaceIllustration.tsx`
- Modify: `frontend/src/components/ui/index.ts`
- Test: `frontend/src/components/ui/PlacePhoto.test.tsx`

**Interfaces:**
- Consumes: `API_BASE` from `frontend/src/api/client.ts` (value `"/api/v1"`).
- Produces: `PlacePhoto({ poiId: string | null; name: string; category: string | null; size: "sm" | "md" | "lg"; aspect?: "4/3" | "16/9" | "1/1"; className?: string })`, `photoUrl(poiId: string, size: PhotoSize): string`, `PHOTO_WIDTH`, `PlaceIllustration({ category: string | null; className?: string })` rendering a root element with `data-testid="place-illustration"` and `data-category`.

- [ ] **Step 1: Write the failing test** — `frontend/src/components/ui/PlacePhoto.test.tsx`

```tsx
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { PlacePhoto, photoUrl } from ".";

describe("PlacePhoto", () => {
  it("builds the proxy URL for each size", () => {
    expect(photoUrl("huetripo:531787", "sm")).toBe("/api/v1/places/huetripo%3A531787/photo?w=160");
    expect(photoUrl("huetripo:531787", "md")).toBe("/api/v1/places/huetripo%3A531787/photo?w=480");
    expect(photoUrl("huetripo:531787", "lg")).toBe("/api/v1/places/huetripo%3A531787/photo?w=960");
  });

  it("renders a lazy image with the place name as alt text", () => {
    render(<PlacePhoto poiId="huetripo:1" name="Đại Nội Huế" category="historic" size="md" />);
    const image = screen.getByRole("img", { name: "Đại Nội Huế" });
    expect(image).toHaveAttribute("src", "/api/v1/places/huetripo%3A1/photo?w=480");
    expect(image).toHaveAttribute("loading", "lazy");
  });

  it("swaps to the category illustration when the image fails", () => {
    render(<PlacePhoto poiId="huetripo:1" name="Đại Nội Huế" category="historic" size="sm" />);
    fireEvent.error(screen.getByRole("img", { name: "Đại Nội Huế" }));
    expect(screen.queryByRole("img", { name: "Đại Nội Huế" })).not.toBeInTheDocument();
    expect(screen.getByTestId("place-illustration")).toHaveAttribute("data-category", "historic");
    expect(screen.getByText("Đại Nội Huế")).toHaveClass("sr-only");
  });

  it("shows the illustration straight away without a poi id", () => {
    render(<PlacePhoto poiId={null} name="Nghỉ trưa" category={null} size="sm" />);
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
    expect(screen.getByTestId("place-illustration")).toHaveAttribute("data-category", "default");
  });
});
```

- [ ] **Step 2: Run to verify it fails** — `npx vitest run src/components/ui/PlacePhoto.test.tsx` → FAIL (`photoUrl` not exported).

- [ ] **Step 3: Implement**

`frontend/src/components/ui/PlaceIllustration.tsx`:

```tsx
import type { ReactNode } from "react";

const KIM = "var(--color-kim)";

/** Line art in son with kim accents, one per category; viewBox 96x72. */
const ART: Record<string, ReactNode> = {
  historic: (
    <>
      <path d="M8 64h80M14 64V40h68v24M10 40l38-20 38 20" />
      <path d="M38 64V52a10 10 0 0 1 20 0v12" />
      <path d="M34 24h28M40 18h16M48 18v-8" stroke={KIM} />
    </>
  ),
  religious: (
    <>
      <path d="M30 64h36M34 64V54h28v10M30 54l18-6 18 6M37 48v-8h22v8M33 40l15-5 15 5M40 35v-7h16v7M37 28l11-4 11 4" />
      <path d="M48 24V12" stroke={KIM} />
    </>
  ),
  restaurant: (
    <>
      <path d="M18 38h60a30 30 0 0 1-60 0z" />
      <path d="M60 10L46 38M70 12L52 38" stroke={KIM} />
      <path d="M36 28c-4-4 4-8 0-12M46 28c-4-4 4-8 0-12" />
    </>
  ),
  cafe: (
    <>
      <path d="M30 44h36v6a14 14 0 0 1-14 14h-8a14 14 0 0 1-14-14z" />
      <path d="M34 30h28l-4 14H38zM38 22h20v8H38z" />
      <path d="M22 66h52M66 48h4a6 6 0 0 1 0 12h-4" stroke={KIM} />
    </>
  ),
  market: (
    <>
      <path d="M14 50L48 18l34 32z" />
      <path d="M14 50q34 10 68 0M24 64h48" stroke={KIM} />
    </>
  ),
  park: (
    <>
      <path d="M6 50h84M10 50q12-18 24 0M34 50q14-18 28 0M62 50q12-18 24 0" />
      <path d="M8 62q6-4 12 0t12 0t12 0t12 0t12 0t12 0" stroke={KIM} />
    </>
  ),
  museum: (
    <>
      <path d="M14 30l34-16 34 16zM18 30h60M24 34v24M38 34v24M58 34v24M72 34v24M14 62h68" />
      <path d="M44 22h8" stroke={KIM} />
    </>
  ),
  default: (
    <>
      <path d="M48 58c-10-8-10-24 0-36 10 12 10 28 0 36zM48 58c-16-2-24-14-22-26 12 2 20 12 22 26zM48 58c16-2 24-14 22-26-12 2-20 12-22 26z" />
      <path d="M20 64h56" stroke={KIM} />
    </>
  ),
};

/** Decorative stand-in for a missing photo. Hidden from screen readers; callers add the name. */
export function PlaceIllustration({ category, className = "" }: { category: string | null; className?: string }) {
  const key = category && category in ART ? category : "default";
  return (
    <div
      aria-hidden="true"
      data-testid="place-illustration"
      data-category={key}
      className={`o-hoc flex items-center justify-center bg-kim-soft text-son ${className}`.trim()}
    >
      <svg
        viewBox="0 0 96 72"
        className="h-3/5 max-h-28 w-3/5"
        fill="none"
        stroke="currentColor"
        strokeWidth={2}
        strokeLinecap="round"
        strokeLinejoin="round"
      >
        {ART[key]}
      </svg>
    </div>
  );
}
```

`frontend/src/components/ui/PlacePhoto.tsx`:

```tsx
import { useState } from "react";
import { API_BASE } from "../../api/client";
import { PlaceIllustration } from "./PlaceIllustration";

export type PhotoSize = "sm" | "md" | "lg";
export type PhotoAspect = "4/3" | "16/9" | "1/1";

export const PHOTO_WIDTH: Record<PhotoSize, number> = { sm: 160, md: 480, lg: 960 };

const ASPECT: Record<PhotoAspect, string> = {
  "4/3": "aspect-[4/3]",
  "16/9": "aspect-video",
  "1/1": "aspect-square",
};

export function photoUrl(poiId: string, size: PhotoSize): string {
  return `${API_BASE}/places/${encodeURIComponent(poiId)}/photo?w=${PHOTO_WIDTH[size]}`;
}

interface PlacePhotoProps {
  poiId: string | null;
  name: string;
  category: string | null;
  size: PhotoSize;
  aspect?: PhotoAspect;
  className?: string;
}

/** The place photo from the backend proxy, in a fixed-ratio box; the category illustration when there is none. */
export function PlacePhoto({ poiId, name, category, size, aspect = "4/3", className = "" }: PlacePhotoProps) {
  const src = poiId ? photoUrl(poiId, size) : null;
  const [failedSrc, setFailedSrc] = useState<string | null>(null);
  const [loadedSrc, setLoadedSrc] = useState<string | null>(null);
  const showImage = src !== null && failedSrc !== src;
  return (
    <div className={`relative overflow-hidden bg-kim-soft ${ASPECT[aspect]} ${className}`.trim()}>
      {showImage ? (
        <img
          key={src}
          src={src}
          alt={name}
          loading="lazy"
          decoding="async"
          onLoad={() => setLoadedSrc(src)}
          onError={() => setFailedSrc(src)}
          className={`h-full w-full object-cover transition-opacity duration-300 ${loadedSrc === src ? "opacity-100" : "opacity-0"}`}
        />
      ) : (
        <>
          <PlaceIllustration category={category} className="absolute inset-0" />
          <span className="sr-only">{name}</span>
        </>
      )}
    </div>
  );
}
```

Add to `frontend/src/components/ui/index.ts`:

```ts
export { PHOTO_WIDTH, PlacePhoto, photoUrl, type PhotoAspect, type PhotoSize } from "./PlacePhoto";
export { PlaceIllustration } from "./PlaceIllustration";
```

- [ ] **Step 4: Run** `npx vitest run` and `npm run build` — both pass.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/ui
git commit -m "feat(frontend): place photo with lazy loading and category illustrations"
```

---

### Task 4: Layout, chat page and chat cards

**Files:**
- Modify: `frontend/src/components/Layout.tsx`, `frontend/src/pages/ChatPage.tsx`, `frontend/src/components/chat/Composer.tsx`, `frontend/src/components/chat/MessageBubble.tsx`, `frontend/src/components/chat/ChatCards.tsx`, `frontend/src/api/types.ts` (`ChatPlanItem`)
- Create: `frontend/src/components/chat/ChatWelcome.tsx`
- Test: `frontend/src/pages/ChatPage.test.tsx`, new `frontend/src/components/chat/ChatCards.test.tsx`

**Interfaces:**
- Consumes: Task 2 kit, Task 3 `PlacePhoto`, backend `ChatPlanItem.poi_id` (Task 1).
- Produces: `Composer` prop `prefill?: { text: string; nonce: number }`; `ChatWelcome({ onPick: (text: string) => void })`; `SAMPLE_QUESTIONS: readonly string[]` exported from `ChatWelcome.tsx`; `ChatPage` reads `location.state?.prefill` (a string) — Task 7 navigates with it.

- [ ] **Step 1: Write the failing tests**

`frontend/src/components/chat/ChatCards.test.tsx`:

```tsx
import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import type { ChatPlanCard } from "../../api/types";
import { ChatCardView } from "./ChatCards";

const card: ChatPlanCard = {
  kind: "plan_summary",
  thread_id: "t1",
  status: "AWAITING_APPROVAL",
  version: 1,
  days: [
    {
      date: "2026-12-20",
      items: [
        { time: "08:00", name: "Đại Nội Huế", kind: "VISIT", meal: null, poi_id: "huetripo:531787" },
        { time: "11:30", name: "Nghỉ ăn trưa", kind: "MEAL_BREAK", meal: null, poi_id: null },
      ],
    },
  ],
  budget_options: [],
};

describe("plan card photos", () => {
  it("shows a photo for each item with a poi id and an illustration otherwise", () => {
    render(
      <MemoryRouter>
        <ChatCardView card={card} live={false} disabled={false} onSend={vi.fn()} />
      </MemoryRouter>,
    );
    const section = screen.getByRole("region", { name: "Lịch trình" });
    expect(within(section).getByRole("img", { name: "Đại Nội Huế" })).toHaveAttribute(
      "src",
      "/api/v1/places/huetripo%3A531787/photo?w=160",
    );
    expect(within(section).getAllByTestId("place-illustration")).toHaveLength(1);
    expect(within(section).getByText("08:00")).toBeInTheDocument();
  });
});
```

Add to `frontend/src/pages/ChatPage.test.tsx`, reusing the file's existing mocks for a history fetch
with no messages:

```tsx
it("fills the composer from a sample question without sending", async () => {
  // render the empty chat the same way the existing empty-history test does
  const button = await screen.findByRole("button", { name: SAMPLE_QUESTIONS[1] });
  await userEvent.click(button);
  expect(screen.getByRole("textbox", { name: "Tin nhắn" })).toHaveValue(SAMPLE_QUESTIONS[1]);
  // assert the existing send mock (the POST to /chat) was not called
});

it("fills the composer from router state", async () => {
  // render inside <MemoryRouter initialEntries={[{ pathname: "/", state: { prefill: "Đại Nội Huế có gì hay?" } }]}>
  expect(await screen.findByRole("textbox", { name: "Tin nhắn" })).toHaveValue("Đại Nội Huế có gì hay?");
});
```

(Fill the two comment lines with the file's own render helper and send mock; import `SAMPLE_QUESTIONS`
from `../components/chat/ChatWelcome`.) Also add `poi_id: null` (or a real id) to every
`ChatPlanItem` literal in existing tests so they type-check.

- [ ] **Step 2: Run to verify they fail** — `npx vitest run src/components/chat src/pages/ChatPage.test.tsx` → FAIL.

- [ ] **Step 3: Implement**

`frontend/src/api/types.ts`: `ChatPlanItem` gets `poi_id: string | null;` with the doc comment
"Null for breaks and stops without a source POI."

`frontend/src/components/Layout.tsx` (replace the file; every text is kept):

```tsx
import { useState } from "react";
import { NavLink, Outlet } from "react-router-dom";
import { getUserId, shortUserId } from "../lib/userId";
import { Ornament } from "./ui";

const NAV_LINK = "border-b-2 px-1 py-1 text-sm font-medium transition-colors";

function navClass({ isActive }: { isActive: boolean }): string {
  return `${NAV_LINK} ${isActive ? "border-kim text-on-son" : "border-transparent text-on-son/75 hover:text-on-son"}`;
}

export function Layout() {
  const [userId] = useState(() => getUserId());

  return (
    <div className="flex min-h-screen flex-col bg-giay">
      <header className="bg-son text-on-son">
        <div className="mx-auto flex max-w-5xl flex-col gap-2 px-4 py-3 md:flex-row md:items-center md:justify-between">
          <div className="flex flex-col gap-1 md:flex-row md:items-center md:gap-8">
            <span className="font-serif text-xl font-bold tracking-wide">Hue Travel</span>
            <nav aria-label="Chính" className="flex flex-wrap gap-5">
              <NavLink to="/" end className={navClass}>
                Trò chuyện
              </NavLink>
              <NavLink to="/explore" className={navClass}>
                Khám phá Huế
              </NavLink>
            </nav>
          </div>
          <span className="text-xs text-on-son/80">Người dùng thử: {shortUserId(userId)} — chưa phải đăng nhập</span>
        </div>
      </header>
      <Ornament />

      <main className="mx-auto w-full max-w-5xl flex-1 px-4 py-6">
        <Outlet />
      </main>

      <footer className="border-t border-vien bg-nga">
        <p className="mx-auto max-w-5xl px-4 py-4 text-xs leading-relaxed text-muc-soft">
          Xe, khách sạn và đặt chỗ là <strong>MÔ PHỎNG</strong>. Dữ liệu địa điểm: huetripo.hue.gov.vn (giấy phép
          chưa rõ).
        </p>
      </footer>
    </div>
  );
}
```

`frontend/src/components/chat/ChatWelcome.tsx`:

```tsx
import { PlacePhoto, SectionHeading } from "../ui";

export const SAMPLE_QUESTIONS = [
  "Từ Hà Nội, 2 người, đi Huế 2 ngày từ 20/12",
  "Đại Nội mấy giờ mở cửa?",
  "Quán cà phê nào gần Đại Nội?",
  "Từ Đà Nẵng, 3 người, đi Huế 3 ngày, thích lăng tẩm",
] as const;

const HERO_POI = "huetripo:531787";

/** Empty chat: a Huế photo, a greeting and sample questions that fill the composer. */
export function ChatWelcome({ onPick }: { onPick: (text: string) => void }) {
  return (
    <div className="overflow-hidden rounded-2xl border border-vien bg-nga">
      <div className="relative">
        <PlacePhoto poiId={HERO_POI} name="Đại Nội Huế" category="historic" size="lg" aspect="16/9" />
        <div className="absolute inset-0 bg-gradient-to-t from-muc/80 via-muc/20 to-transparent" aria-hidden="true" />
        <p className="absolute bottom-3 left-4 right-4 font-serif text-xl font-semibold text-nga md:text-2xl">
          Chào bạn, mình là trợ lý du lịch Huế
        </p>
      </div>
      <div className="space-y-3 p-4">
        <p className="text-sm leading-relaxed text-muc">
          Hãy kể chuyến đi Huế của bạn: ngày đi, số ngày, xuất phát từ đâu, số người và ngân sách. Bạn cũng có thể hỏi
          giờ mở cửa của một địa điểm.
        </p>
        <SectionHeading as="h2" className="text-sm md:text-base">
          Thử hỏi
        </SectionHeading>
        <ul className="flex flex-wrap gap-2">
          {SAMPLE_QUESTIONS.map((question) => (
            <li key={question}>
              <button
                type="button"
                onClick={() => onPick(question)}
                className="rounded-full border border-vien bg-giay px-3 py-1.5 text-left text-sm text-muc hover:border-kim hover:bg-kim-soft"
              >
                {question}
              </button>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
```

`frontend/src/components/chat/Composer.tsx` (replace the file):

```tsx
import { useEffect, useState, type FormEvent, type KeyboardEvent } from "react";
import { buttonClass } from "../ui";

interface ComposerProps {
  disabled: boolean;
  onSend: (text: string) => void;
  /** Text to put in the field (not sent). A new nonce refills even with the same text. */
  prefill?: { text: string; nonce: number };
}

/** Message input. Enter sends; Shift+Enter starts a new line; IME composition never sends. */
export function Composer({ disabled, onSend, prefill }: ComposerProps) {
  const [draft, setDraft] = useState(prefill?.text ?? "");
  const canSend = !disabled && draft.trim() !== "";

  useEffect(() => {
    if (prefill) setDraft(prefill.text);
  }, [prefill?.nonce, prefill?.text]);

  function send() {
    if (!canSend) return;
    onSend(draft);
    setDraft("");
  }

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    send();
  }

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key !== "Enter" || event.shiftKey || event.nativeEvent.isComposing) return;
    event.preventDefault();
    send();
  }

  return (
    <form onSubmit={onSubmit} className="flex flex-col gap-2 sm:flex-row sm:items-end">
      <label htmlFor="chat-input" className="sr-only">
        Tin nhắn
      </label>
      <textarea
        id="chat-input"
        rows={2}
        value={draft}
        onChange={(event) => setDraft(event.target.value)}
        onKeyDown={onKeyDown}
        placeholder="Ví dụ: Tôi đi Huế 3 ngày 2 đêm từ 05/12, xuất phát Hà Nội, 2 người"
        className="min-h-[3rem] w-full flex-1 resize-y rounded-2xl border border-vien bg-nga px-4 py-2.5 text-base text-muc placeholder:text-muc-soft/70 focus:border-kim focus:outline-none focus:ring-2 focus:ring-kim/40"
      />
      <button type="submit" disabled={!canSend} className={buttonClass("primary")}>
        Gửi
      </button>
      <p className="text-xs text-muc-soft">Enter để gửi, Shift+Enter để xuống dòng.</p>
    </form>
  );
}
```

`frontend/src/pages/ChatPage.tsx`:
- Import `useLocation` from `react-router-dom`, `ChatWelcome` and `SectionHeading`.
- Add:

```tsx
const location = useLocation();
const [prefill, setPrefill] = useState<{ text: string; nonce: number } | undefined>(() => {
  const text = (location.state as { prefill?: unknown } | null)?.prefill;
  return typeof text === "string" && text ? { text, nonce: 0 } : undefined;
});
const pick = (text: string) => setPrefill((current) => ({ text, nonce: (current?.nonce ?? 0) + 1 }));
```

- Replace the empty-state `<p>` with `<ChatWelcome onPick={pick} />` (same condition
  `!loading && messages.length === 0`).
- Pass `prefill={prefill}` to `<Composer>`.
- The `h1` becomes `<SectionHeading as="h1">Trò chuyện</SectionHeading>`; the conversation
  section className becomes `flex min-h-[12rem] flex-col gap-3 rounded-2xl p-1 md:p-2`; the
  "đang suy nghĩ…" bubble uses the bot bubble classes below plus `animate-pulse`; the loading text
  uses `text-muc-soft`.

`frontend/src/components/chat/MessageBubble.tsx`: user bubble
`rounded-2xl rounded-br-sm border border-vien bg-nga px-4 py-2 text-muc`; bot bubble
`rounded-2xl rounded-bl-sm bg-son px-4 py-2 text-on-son`; quick replies `buttonClass("outline", "sm")`;
links inside a bot bubble `text-on-son underline decoration-kim`. Keep every text and role.

`frontend/src/components/chat/ChatCards.tsx`:
- Delete the local `TONE_CLASS`, `PILL`, `CARD`, `SIMULATED_BADGE`; import `TONE_CLASS`, `PILL`,
  `LINK`, `MockBadge`, `Ornament`, `PlacePhoto`, `CategoryChip`, `buttonClass`, `cardClass` from `../ui`.
- Each card `<section>` gets `className={cardClass("mt-2 text-sm")}`, starts with `<Ornament />` and
  wraps its content in `<div className="p-3">`.
- Plan card day list: replace the `<ol>` of text rows with

```tsx
<ol className="mt-2 grid grid-cols-3 gap-2 sm:grid-cols-4">
  {day.items.map((item, itemIndex) => (
    <li key={`${day.date}-${itemIndex}`} className="min-w-0">
      <PlacePhoto poiId={item.poi_id} name={item.name} category={null} size="sm" className="rounded-lg" />
      <p className="mt-1 text-xs leading-tight">
        <span className="font-semibold text-son">{item.time}</span> <span className="text-muc">{item.name}</span>{" "}
        <span className="text-muc-soft">({planItemKindLabel(item.kind, item.meal)})</span>
      </p>
    </li>
  ))}
</ol>
```

- Card title (text unchanged: "Lịch trình {n} ngày · version {v}") and day headings use
  `font-serif text-son`. Budget options become a `grid gap-2 sm:grid-cols-3` of
  `rounded-xl border border-vien bg-giay p-2` boxes; the approve button `buttonClass("primary", "sm")`.
  "Xem chi tiết" keeps its text and uses `LINK`. The data has no "recommended" flag, so no option is
  highlighted (spec §5 assumed one; ruling recorded in the ledger).
- Place card: right after the ornament,
  `<PlacePhoto poiId={card.poi_id} name={card.name} category={card.category} size="md" aspect="16/9" />`;
  the category line becomes `<CategoryChip category={card.category} />`; `dt` text `text-muc-soft`;
  links use `LINK`.
- Booking card: `<MockBadge />` replaces the violet badge; status pills use the shared
  `TONE_CLASS`/`PILL`; inner boxes `rounded-xl bg-giay p-2 ring-1 ring-vien`; contact links use `LINK`.

- [ ] **Step 4: Run** `npx vitest run` and `npm run build` — all pass. Run
  `grep -rnE "(slate|teal|amber|emerald|violet|red|rose|indigo|gray)-[0-9]" src/components/Layout.tsx src/components/chat src/pages/ChatPage.tsx src/pages/ChatPage.test.tsx`
  — no output.

- [ ] **Step 5: Commit**

```bash
git add frontend/src
git commit -m "feat(frontend): Cung đình chat with welcome screen and photo strips in plan cards"
```

---

### Task 5: Plan layout, itinerary tab and itinerary map

**Files:**
- Modify: `frontend/src/pages/PlanLayout.tsx`, `frontend/src/pages/ItineraryTab.tsx`, `frontend/src/components/ItineraryMap.tsx`
- Test: extend the existing itinerary/plan tests (search `src/pages` for `ItineraryTab` and `PlanLayout` tests; create `frontend/src/pages/ItineraryTab.test.tsx` if none exists, reusing the `PlanRecord` fixture the other plan tests use)

**Interfaces:**
- Consumes: Task 2 kit, Task 3 `PlacePhoto`.
- Produces: `heroPoi(record: PlanRecord): { poiId: string; name: string; category: string | null } | null` exported from `PlanLayout.tsx` — the first `VISIT` event with a `poi_id` across all days, in day order.

- [ ] **Step 1: Write the failing tests**
- `heroPoi` returns the first VISIT with a `poi_id`, and `null` for a record whose events have none.
- The itinerary tab renders an `img` named after each VISIT event that has a `poi_id`, with `src`
  ending `?w=480`.
- A `MEAL_BREAK` event without `poi_id` renders no `img` and still shows `eventKindLabel(event)`.
- The day tabs keep `role="tab"` and `aria-selected`.

- [ ] **Step 2: Run to verify they fail.**

- [ ] **Step 3: Implement**

`PlanLayout.tsx`:
- Export `heroPoi`:

```tsx
export function heroPoi(record: PlanRecord): { poiId: string; name: string; category: string | null } | null {
  for (const day of record.payload.itinerary.days) {
    for (const event of day.events) {
      if (event.kind === "VISIT" && event.poi_id) return { poiId: event.poi_id, name: event.name, category: event.category };
    }
  }
  return null;
}
```

- Replace the `<header>` with a hero card:

```tsx
const hero = heroPoi(record);
// …
<header className={cardClass()}>
  <div className="relative">
    <PlacePhoto
      poiId={hero?.poiId ?? null}
      name={hero?.name ?? `${request.origin} → ${request.destination}`}
      category={hero?.category ?? "historic"}
      size="lg"
      aspect="16/9"
      className="max-h-72"
    />
    <div aria-hidden="true" className="absolute inset-0 bg-gradient-to-t from-muc/85 via-muc/25 to-transparent" />
    <div className="absolute inset-x-4 bottom-3 text-nga">
      <h1 className="font-serif text-2xl font-semibold md:text-3xl">
        {request.origin} → {request.destination}
      </h1>
      <p className="text-sm text-nga/90">
        {formatDate(request.start_date)} – {formatDate(request.end_date)} · {request.people} người · {request.rooms} phòng
      </p>
    </div>
  </div>
  <Ornament />
  <div className="flex flex-wrap items-center gap-2 p-3">
    <span className={`${PILL} ${TONE_CLASS[statusTone(status)]}`}>{statusLabel(status)}</span>
    <span className="text-xs text-muc-soft">Phiên bản v{record.version}</span>
    <span className="text-xs text-muc-soft">Mã kế hoạch {record.plan_id.slice(0, 8)}</span>
    {waiting && !editing ? (
      <button
        type="button"
        onClick={() => {
          setEditError(null);
          setEditing(true);
        }}
        className={`${buttonClass("outline", "sm")} ml-auto`}
      >
        Sửa yêu cầu
      </button>
    ) : null}
  </div>
</header>
```

- Remove the local `TONE_CLASS` and `TAB_CLASS`; import from `../components/ui`.
- The edit section uses `cardClass("space-y-4 p-4 sm:p-6")`; its heading `font-serif text-son`;
  "Hủy sửa" uses `LINK`.
- Plan tabs nav: `className="flex flex-wrap gap-2"`; every `NavLink` className
  `({ isActive }) => \`rounded-full px-4 py-1.5 text-sm font-semibold ring-1 \${isActive ? "bg-son text-on-son ring-son" : "bg-nga text-son ring-vien hover:ring-kim"}\``.
  Texts unchanged ("Lịch trình", "Ngân sách & duyệt", "Đặt chỗ").
- The "Không tìm thấy kế hoạch" and "Kế hoạch thuộc người dùng khác" blocks use `cardClass("p-6")`
  and serif son headings.

`ItineraryTab.tsx`:
- Day tab buttons: `shrink-0 rounded-full px-4 py-1.5 text-sm font-semibold ring-1`, selected
  `bg-son text-on-son ring-son`, otherwise `bg-nga text-son ring-vien`.
- The shared-notes `<ul aria-label="Ghi chú chung cho ngày">` is wrapped in `<Notice variant="warning">`
  (the `aria-label` stays on the `ul`); its classes become `list-disc space-y-1 pl-5 text-xs`.
- The events `<ol>` className becomes `relative ml-3 space-y-3 border-l-2 border-dashed border-kim pl-6`.
- `markerColor` returns `"#7a1f1f"` for every event (category colours stay on the explore map).
- `EventItem` gets a `number: number` prop (the 1-based position in the day) and becomes:

```tsx
function EventItem({ event, number, place, priceText, shared }: { event: ItineraryEvent; number: number; place: Place | undefined; priceText: string; shared: Set<string> }) {
  const ownNotes = translateWarnings(event.warnings).filter((note) => !shared.has(note));
  const isPlace = event.kind === "VISIT" || event.kind === "MEAL";
  const showPhoto = Boolean(event.poi_id) && isPlace;
  return (
    <li className={cardClass("relative overflow-visible p-3 sm:flex sm:gap-4")}>
      <span
        aria-hidden="true"
        className="absolute -left-[2.3rem] top-4 flex h-6 w-6 items-center justify-center rounded-full bg-son text-xs font-bold text-on-son ring-2 ring-kim"
      >
        {number}
      </span>
      {showPhoto ? (
        <PlacePhoto
          poiId={event.poi_id}
          name={event.name}
          category={event.category}
          size="md"
          className="mb-3 w-full shrink-0 rounded-xl sm:mb-0 sm:w-44"
        />
      ) : (
        <div aria-hidden="true" className="mb-3 flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-kim-soft text-2xl sm:mb-0">
          {event.kind === "MEAL" || event.kind === "MEAL_BREAK" ? "🍜" : "•"}
        </div>
      )}
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <time className="text-sm font-semibold text-son">{timeRange(event)}</time>
          <Chip tone="soft">{eventKindLabel(event)}</Chip>
        </div>
        <h3 className="mt-1 font-serif text-base font-semibold leading-snug text-muc">
          {event.poi_id ? (
            <Link to={placeDetailPath(event.poi_id)} className="hover:text-son hover:underline decoration-kim">
              {event.name}
            </Link>
          ) : (
            event.name
          )}
        </h3>
        <dl className="mt-2 grid grid-cols-[7.5rem_1fr] gap-x-2 gap-y-1 text-sm">
          <dt className="text-muc-soft">Loại</dt>
          <dd>{categoryLabel(event.category)}</dd>
          <dt className="text-muc-soft">Di chuyển</dt>
          <dd>{travelText(event)}</dd>
          {event.kind === "VISIT" ? (
            <>
              <dt className="text-muc-soft">Thời gian tham quan</dt>
              <dd>{formatMinutes(event.visit_minutes)}</dd>
            </>
          ) : null}
          {isPlace ? (
            <>
              <dt className="text-muc-soft">Giá tham khảo</dt>
              <dd>{priceText}</dd>
              <dt className="text-muc-soft">Giờ mở cửa</dt>
              <dd>{place ? openingHoursText(place) : "chưa xác minh"}</dd>
            </>
          ) : null}
        </dl>
        {ownNotes.length > 0 ? (
          <ul className="mt-3 list-disc space-y-1 pl-5 text-xs text-muc marker:text-kim">
            {ownNotes.map((warning) => (
              <li key={warning}>{warning}</li>
            ))}
          </ul>
        ) : null}
      </div>
    </li>
  );
}
```

  and the list passes `number={position + 1}`.
- Empty states use `text-muc-soft`; "Kế hoạch chưa có ngày nào." box becomes
  `rounded-2xl border border-dashed border-vien bg-nga p-6 text-sm text-muc-soft`.

`ItineraryMap.tsx`: polyline `pathOptions={{ color: "#b8913f", weight: 3, dashArray: "6 8" }}`;
markers `radius={9}` and `pathOptions={{ color: "#b8913f", weight: 2, fillColor: point.color, fillOpacity: 0.95 }}`;
the map wrapper gets `rounded-2xl border border-vien overflow-hidden`. Tooltips and popups unchanged.

- [ ] **Step 4: Run** `npx vitest run`, `npm run build`, and the palette grep on the three files and their tests — clean.

- [ ] **Step 5: Commit**

```bash
git add frontend/src
git commit -m "feat(frontend): plan hero photo, pill tabs and photo timeline for the itinerary"
```

---

### Task 6: Budget tab, booking tab and shared notices

**Files:**
- Modify: `frontend/src/pages/BudgetTab.tsx`, `frontend/src/pages/BookingTab.tsx`, `frontend/src/components/WarningsPanel.tsx`, `frontend/src/components/ErrorBanner.tsx`, `frontend/src/components/Toast.tsx`, `frontend/src/components/Skeletons.tsx`, `frontend/src/components/PlanProgress.tsx`
- Test: the existing tests of these files (no new behaviour; update only assertions on old classes)

**Interfaces:**
- Consumes: Task 2 kit.

- [ ] **Step 1: Restyle with the mapping**
- `ErrorBanner` → `<Notice variant="error" role="alert">{message}</Notice>`.
- `WarningsPanel` → the outer box becomes `<Notice variant="warning">`, keeping `aria-labelledby` and
  its heading id `warnings-heading` (heading `font-serif text-son`).
- `Toast` → keep `role="status"` and timing; classes
  `rounded-full bg-muc px-4 py-2 text-sm text-on-son shadow-lg`.
- `Skeletons` → blocks `bg-kim-soft animate-pulse rounded-xl`.
- `PlanProgress` → done steps `bg-kim`, the current step `bg-son ring-2 ring-kim`, pending
  `bg-vien`; labels `text-muc-soft`, the current label `text-son font-semibold`.
- `BudgetTab`: shared `TONE_CLASS`/`PILL`; the options become `grid gap-3 md:grid-cols-3` of
  `cardClass("p-4")`, the option name `font-serif text-son`; approve buttons `buttonClass("primary")`;
  cost-item lists `divide-y divide-vien`, source labels `text-muc-soft`; the shortfall section is a
  `<Notice variant="error">` and the approved section a `<Notice variant="success">`, both keeping
  `aria-labelledby` and the heading ids `shortfall-heading` / `approved-heading`; the items section
  keeps `items-heading`.
- `BookingTab`: shared `TONE_CLASS`/`PILL`; `<MockBadge />` for every standalone "MÔ PHỎNG" badge
  (button text "Đặt MÔ PHỎNG" and status text "Đã đặt (MÔ PHỎNG)" stay as they are); offer cards
  `cardClass("p-4")`; headings `book-heading` / `result-heading` serif son; booked-state chips
  `bg-reu-soft text-reu`; buttons via `buttonClass`; retry and contact behaviour unchanged.

- [ ] **Step 2: Run** `npx vitest run`, `npm run build`, and the palette grep on the listed files — clean.

- [ ] **Step 3: Commit**

```bash
git add frontend/src
git commit -m "feat(frontend): Cung đình budget and booking tabs, notices, toast and skeletons"
```

---

### Task 7: Explore, place detail, request form and 404

**Files:**
- Modify: `frontend/src/pages/ExplorePage.tsx`, `frontend/src/components/PlaceCard.tsx`, `frontend/src/components/CategoryChips.tsx`, `frontend/src/components/PlacesMap.tsx`, `frontend/src/pages/PlaceDetailPage.tsx`, `frontend/src/pages/RequestPage.tsx`, `frontend/src/components/TripRequestForm.tsx`, `frontend/src/pages/NotFoundPage.tsx`
- Test: `frontend/src/components/PlaceCard.test.tsx`, `frontend/src/pages/PlaceDetailPage.test.tsx` (create if absent), `frontend/src/components/TripRequestForm.test.tsx`

**Interfaces:**
- Consumes: Task 2 kit, Task 3 `PlacePhoto`/`PlaceIllustration`, Task 4 `ChatPage` reading `location.state.prefill`.
- Produces: `askAssistantText(name: string): string` exported from `PlaceDetailPage.tsx`:

```tsx
export function askAssistantText(name: string): string {
  return `${name} có gì hay? Giờ mở cửa và giá vé thế nào?`;
}
```

- [ ] **Step 1: Write the failing tests**
- `PlaceCard.test.tsx`: the card renders an `img` named after the place with `src` ending `?w=480`.
- `PlaceDetailPage.test.tsx`: a link named "Hỏi trợ lý về nơi này"; clicking it navigates to `/`.
  Render inside `MemoryRouter` with `<Routes>` holding the detail route and a `/` route whose element
  is a probe that prints `JSON.stringify(useLocation().state)`; after the click the probe shows
  `{"prefill":"<askAssistantText(place.name)>"}`. Mock the place fetch the way the existing explore
  tests do.
- `TripRequestForm.test.tsx:46`: replace `expect(origin).toHaveClass("border-red-500")` with
  `expect(origin).toHaveAttribute("aria-invalid", "true")`.

- [ ] **Step 2: Run to verify they fail.**

- [ ] **Step 3: Implement**
- `PlaceCard`: the `<article>` gets `cardClass("flex flex-col")`; its first child is
  `<PlacePhoto poiId={place.id} name={place.name} category={place.category} size="md" />`; the rest
  sits in `<div className="flex flex-col gap-3 p-4">`; the title link
  `font-serif text-son hover:underline decoration-kim`; the category pill →
  `<CategoryChip category={place.category} />`; `dt` `text-muc-soft`.
- `CategoryChips`: selected chip `bg-son text-on-son ring-son`, others
  `bg-nga text-son ring-vien hover:ring-kim` (all `rounded-full px-3 py-1.5 text-sm font-medium ring-1`);
  keep roles and `aria-pressed`.
- `ExplorePage`: `<SectionHeading as="h1">Khám phá Huế</SectionHeading>`; the search input uses the
  composer field classes; results `grid gap-4 sm:grid-cols-2 lg:grid-cols-3`; the map wrapper
  `rounded-2xl border border-vien overflow-hidden`; pagination buttons `buttonClass("outline", "sm")`.
- `PlacesMap`: markers keep their category colour with `color: "#fffaf0", weight: 1.5`.
- `PlaceDetailPage`: a hero block

```tsx
<div className={cardClass()}>
  <div className="relative">
    <PlacePhoto poiId={place.id} name={place.name} category={place.category} size="lg" aspect="16/9" className="max-h-80" />
    <div aria-hidden="true" className="absolute inset-0 bg-gradient-to-t from-muc/85 via-muc/20 to-transparent" />
    <h1 className="absolute inset-x-4 bottom-3 font-serif text-2xl font-semibold leading-snug text-nga md:text-3xl">{place.name}</h1>
  </div>
  <Ornament />
  <div className="flex flex-wrap items-center gap-3 p-4">
    <CategoryChip category={place.category} />
    <Link to="/" state={{ prefill: askAssistantText(place.name) }} className={buttonClass("primary", "sm")}>
      Hỏi trợ lý về nơi này
    </Link>
    {/* the existing source link, styled with LINK */}
  </div>
</div>
```

  replacing the old `h1` block. The warnings section becomes `<Notice variant="warning">` (keep
  `aria-labelledby="warnings-heading"`); the info, summary and raw sections use `cardClass("p-4")`
  with serif son headings (ids unchanged). "Không tìm thấy địa điểm" uses `cardClass("p-6")` with
  `<PlaceIllustration category={null} className="mb-4 h-32 rounded-xl" />` above the heading.
- `RequestPage` / `TripRequestForm`: headings serif son (`describe-heading` id kept); sections
  `cardClass("p-4 sm:p-6")`; inputs and selects
  `rounded-xl border border-vien bg-nga px-3 py-2 text-muc focus:border-kim focus:outline-none focus:ring-2 focus:ring-kim/40`;
  invalid inputs `border-son` and `aria-invalid="true"` (and `aria-invalid` absent or `"false"` when
  valid); error texts `text-son`; the submit button `buttonClass("primary")`.
- `NotFoundPage`: `cardClass("p-8 text-center")` holding
  `<PlaceIllustration category="historic" className="mx-auto mb-4 h-32 w-48 rounded-xl" />`, the
  existing heading in serif son, the existing text in `text-muc-soft`, and the home link with
  `buttonClass("outline")`.

- [ ] **Step 4: Run** `npx vitest run`, `npm run build`, and
  `grep -rnE "(slate|teal|amber|emerald|violet|red|rose|indigo|gray)-[0-9]" frontend/src` — no output anywhere.

- [ ] **Step 5: Commit**

```bash
git add frontend/src
git commit -m "feat(frontend): Cung đình explore, place detail with ask-assistant, form and 404"
```

---

### Task 8: Visual check and fixes (controller)

**Files:** whatever the check finds; no planned edits.

- [ ] **Step 1: Start the app** with the rules extractor and no Ollama: backend
  `QU_ENABLED=false RAG_ENABLED=false` → `..\.venv\Scripts\python -m uvicorn app.main:app --port 8000`
  from `backend/` (background); frontend `npx vite --port 5173` from `frontend/` (background).
- [ ] **Step 2: Create data** — send "Từ Hà Nội, 2 người, đi Huế 2 ngày từ 20/12" in the chat so the
  plan pages have a record; open a place detail page and the explore page.
- [ ] **Step 3: Screenshots at 1280×800 and 390×844** of: chat empty, chat with the plan card, plan
  Lịch trình / Ngân sách / Đặt chỗ, explore, place detail, `/form`, a 404 path.
- [ ] **Step 4: Check** each screenshot: Vietnamese diacritics render in both fonts; no kim text on a
  light background; no horizontal scroll at 390 px; photos load (the first load of each photo fills
  the cache and can take a few seconds) and illustrations appear where a place has no photo; the
  ornament band sits under the nav and on large cards.
- [ ] **Step 5: Fix** what the check finds in one dispatch, re-run tests, build and grep, and re-take
  the affected screenshots.
- [ ] **Step 6: Commit** `fix(frontend): visual check fixes` if anything changed.
