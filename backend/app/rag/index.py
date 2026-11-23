"""Embedding index for place RAG: one document per POI, vectors in a separate SQLite file.

Run from `backend/`:  python -m app.rag.index [--model bge-m3]
Only POIs whose document text or model changed are embedded again.
"""

from __future__ import annotations

import argparse
import hashlib
import sqlite3
import sys
from collections.abc import Iterable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import httpx
import numpy as np

from app.core.config import hue_database_path, ollama_url, rag_embed_model, rag_index_path
from app.core.usage import add_usage
from app.repositories.hue_places import HuePlacesRepository
from app.schemas.place import Place
from app.services.guide import guide_for

DEFAULT_TIMEOUT = 120.0
EMBED_BATCH = 32
PHONE_KEY = "Điện thoại"
TYPE_KEY = "Loại hình (theo nguồn)"
CATEGORY_LABELS = {
    "restaurant": "quán ăn",
    "cafe": "quán cà phê",
    "historic": "di tích",
    "attraction": "điểm tham quan",
    "market": "chợ",
    "religious": "tôn giáo",
    "park": "công viên",
    "museum": "bảo tàng",
}
_SCHEMA = """
CREATE TABLE IF NOT EXISTS place_embeddings (
    poi_id TEXT PRIMARY KEY,
    model TEXT NOT NULL,
    text_hash TEXT NOT NULL,
    dim INTEGER NOT NULL,
    vector BLOB NOT NULL
)
"""


def _vnd(value: int) -> str:
    return f"{value:,}".replace(",", ".") + "đ"


def price_text(place: Place) -> str | None:
    """Reference price as written in answers, e.g. '30.000đ – 50.000đ'; None when unknown."""
    low, high = place.price_min_vnd, place.price_max_vnd
    if low is not None and high is not None and high != low:
        return f"{_vnd(low)} – {_vnd(high)}"
    if low is not None:
        return _vnd(low)
    if place.is_free_claim:
        return "miễn phí"
    return None


def document_text(place: Place) -> str:
    """The text that is embedded, searched and shown to the generator for one POI."""
    parts = [place.name, CATEGORY_LABELS.get(place.category, place.category)]
    source_type = place.raw_attributes.get(TYPE_KEY)
    if source_type:
        parts.append(f"Loại hình: {source_type}")
    if place.address:
        parts.append(f"Địa chỉ: {place.address}")
    if place.opening_hours_raw:
        parts.append(f"Giờ mở cửa: {place.opening_hours_raw}")
    price = price_text(place)
    if price:
        parts.append(f"Giá: {price}")
    phone = place.raw_attributes.get(PHONE_KEY)
    if phone:
        parts.append(f"Điện thoại: {phone}")
    if place.rating_value is not None:
        parts.append(f"Đánh giá: {place.rating_value}/5 ({place.rating_count or 0} lượt)")
    if place.summary:
        parts.append(place.summary.strip().rstrip("."))
    # The guide lead is part of the document only for POIs in the guide corpus, so other documents keep their
    # text and hash; the index re-embeds just the documents whose text changed.
    guide = guide_for(place.id)
    if guide is not None:
        parts.append(f"Giới thiệu: {guide.text.rstrip('.')}")
    return ". ".join(parts) + ("." if place.summary or guide is not None else "")


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class EmbedError(RuntimeError):
    """Ollama did not return one embedding per input."""


class EmbedClient:
    """Calls Ollama `POST /api/embed`."""

    def __init__(
        self,
        base_url: str,
        model: str,
        timeout: float = DEFAULT_TIMEOUT,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.model = model
        self._client = httpx.Client(base_url=base_url, timeout=timeout, transport=transport)

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        try:
            response = self._client.post("/api/embed", json={"model": self.model, "input": list(texts)})
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as error:
            raise EmbedError(f"Ollama embed failed: {error}") from error
        vectors = payload.get("embeddings") if isinstance(payload, dict) else None
        if not isinstance(vectors, list) or len(vectors) != len(texts):
            raise EmbedError("Ollama returned the wrong number of embeddings")
        add_usage("embedding", payload)
        return [[float(x) for x in vector] for vector in vectors]


class EmbeddingStore:
    """Vectors by poi_id in their own SQLite file (float32, little endian)."""

    def __init__(self, path: Path) -> None:
        self.path = path

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path)
        try:
            connection.execute(_SCHEMA)
            yield connection
            connection.commit()
        finally:
            connection.close()

    def hashes(self, model: str) -> dict[str, str]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT poi_id, text_hash FROM place_embeddings WHERE model = ?", (model,)
            ).fetchall()
        return dict(rows)

    def all_ids(self) -> set[str]:
        with self._connect() as connection:
            return {row[0] for row in connection.execute("SELECT poi_id FROM place_embeddings")}

    def upsert(self, model: str, rows: Sequence[tuple[str, str, Sequence[float]]]) -> None:
        with self._connect() as connection:
            connection.executemany(
                "INSERT OR REPLACE INTO place_embeddings (poi_id, model, text_hash, dim, vector) "
                "VALUES (?, ?, ?, ?, ?)",
                [
                    (poi_id, model, digest, len(vector), np.asarray(vector, dtype="<f4").tobytes())
                    for poi_id, digest, vector in rows
                ],
            )

    def delete(self, poi_ids: Iterable[str]) -> None:
        with self._connect() as connection:
            connection.executemany("DELETE FROM place_embeddings WHERE poi_id = ?", [(i,) for i in poi_ids])

    def load(self, model: str) -> tuple[list[str], np.ndarray]:
        """Ids in sorted order and their L2-normalised vectors; shape (0, 0) when empty."""
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT poi_id, vector FROM place_embeddings WHERE model = ? ORDER BY poi_id", (model,)
            ).fetchall()
        if not rows:
            return [], np.zeros((0, 0), dtype=np.float32)
        matrix = np.stack([np.frombuffer(blob, dtype="<f4") for _, blob in rows]).astype(np.float32)
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return [poi_id for poi_id, _ in rows], matrix / norms


@dataclass(frozen=True)
class IndexStats:
    embedded: int
    unchanged: int
    deleted: int


def build_index(
    places: Sequence[Place], store: EmbeddingStore, client: EmbedClient, batch: int = EMBED_BATCH
) -> IndexStats:
    """Embed new or changed documents, keep the rest, delete rows for POIs that are gone."""
    known = store.hashes(client.model)
    todo: list[tuple[str, str, str]] = []
    unchanged = 0
    for place in places:
        text = document_text(place)
        digest = text_hash(text)
        if known.get(place.id) == digest:
            unchanged += 1
        else:
            todo.append((place.id, digest, text))
    for start in range(0, len(todo), batch):
        chunk = todo[start : start + batch]
        vectors = client.embed([text for _, _, text in chunk])
        store.upsert(client.model, [(poi_id, digest, vector) for (poi_id, digest, _), vector in zip(chunk, vectors)])
    gone = store.all_ids() - {place.id for place in places}
    store.delete(gone)
    return IndexStats(embedded=len(todo), unchanged=unchanged, deleted=len(gone))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the place embedding index.")
    parser.add_argument("--model", default=rag_embed_model())
    args = parser.parse_args(argv)
    places = HuePlacesRepository(hue_database_path()).list_all()
    client = EmbedClient(ollama_url(), args.model)
    try:
        stats = build_index(places, EmbeddingStore(rag_index_path()), client)
    except EmbedError as error:
        print(f"Index build failed: {error}", file=sys.stderr)
        return 1
    print(f"embedded={stats.embedded} unchanged={stats.unchanged} deleted={stats.deleted}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
