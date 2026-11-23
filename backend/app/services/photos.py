"""Resized, cached copies of the photos shown for Huế POIs.

Source photos come from huetripo.hue.gov.vn; Wikimedia Commons thumbnails are fetched only when a
curated fallback (see `photo_fallbacks`) names them. Only https URLs on these hosts are fetched, so a
client can never make the server download an arbitrary URL. Failures are not cached; the next request
tries again.
"""

from __future__ import annotations

import io
import logging
import os
import tempfile
import zlib
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from PIL import Image, ImageOps, UnidentifiedImageError

from app.schemas.place import PlacePhoto

SOURCE_HOST = "huetripo.hue.gov.vn"
ALLOWED_HOSTS = frozenset({SOURCE_HOST, "thumb.wikimedia.org", "upload.wikimedia.org"})
USER_AGENT = "HueTravelAgent/0.1 (https://www.mediawiki.org/wiki/API:Etiquette) httpx"
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
    """True for an https URL on one of the hosts this service may download from."""
    if not url:
        return False
    parts = urlsplit(url)
    return parts.scheme == "https" and parts.hostname in ALLOWED_HOSTS


def is_source_host(url: str | None) -> bool:
    """True only for an https URL on the Hue source host (huetripo)."""
    if not url:
        return False
    parts = urlsplit(url)
    return parts.scheme == "https" and parts.hostname == SOURCE_HOST


def cache_key_for(poi_id: str, photo: PlacePhoto) -> str:
    """Source photos are cached per place; Commons photos per file, so places sharing one share a copy."""
    if photo.kind == "source":
        return poi_id
    return "commons_" + format(zlib.crc32(photo.url.encode("utf-8")), "08x")


def cache_path(cache_dir: Path, poi_id: str, width: int) -> Path:
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in poi_id)
    return cache_dir / f"{safe}_{width}.webp"


def resize_to_webp(data: bytes, width: int) -> bytes:
    """Fit the image into `width` x 2*`width` (never upscale), keep the aspect ratio, encode WebP."""
    try:
        with Image.open(io.BytesIO(data)) as source:
            image = ImageOps.exif_transpose(source).convert("RGB")
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as error:
        raise PhotoUpstreamError(f"cannot decode photo: {error}") from error
    scale = min(width / image.width, (2 * width) / image.height, 1.0)
    if scale < 1:
        size = (max(1, round(image.width * scale)), max(1, round(image.height * scale)))
        image = image.resize(size, Image.Resampling.LANCZOS)
    out = io.BytesIO()
    try:
        image.save(out, "WEBP", quality=WEBP_QUALITY)
    except (OSError, ValueError) as error:
        raise PhotoUpstreamError(f"cannot encode photo: {error}") from error
    return out.getvalue()


class PhotoService:
    """Safe to share across FastAPI's thread pool: the cache write is atomic."""

    def __init__(self, cache_dir: Path, transport: httpx.BaseTransport | None = None) -> None:
        self.cache_dir = cache_dir
        self._client = httpx.Client(
            timeout=TIMEOUT_SECONDS,
            transport=transport,
            follow_redirects=False,
            headers={"User-Agent": USER_AGENT},
        )

    def get(self, cache_key: str, photo_url: str | None, width: int) -> Path:
        if not allowed_source(photo_url):
            if photo_url:
                logger.warning("photo source not allowed for %s: %s", cache_key, photo_url)
            raise PhotoUnavailable(cache_key)
        target = cache_path(self.cache_dir, cache_key, width)
        if target.exists():
            return target
        encoded = resize_to_webp(self._download(photo_url), width)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        handle, temp_name = tempfile.mkstemp(dir=self.cache_dir, suffix=".tmp")
        try:
            with os.fdopen(handle, "wb") as temp_file:
                temp_file.write(encoded)
        except BaseException:
            Path(temp_name).unlink(missing_ok=True)
            raise
        try:
            os.replace(temp_name, target)
        except OSError as error:
            # Windows refuses to replace a file another request is streaming; that file is the same photo.
            Path(temp_name).unlink(missing_ok=True)
            if target.exists():
                return target
            raise PhotoUpstreamError(f"cannot write cache file: {error}") from error
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
