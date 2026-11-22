"""RAG index: document text, hashing, embedding client, incremental store."""

from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path

_BACKEND = _Path(__file__).resolve().parents[1] / "backend"
if str(_BACKEND) not in _sys.path:
    _sys.path.insert(0, str(_BACKEND))

import json  # noqa: E402
from datetime import datetime, timezone  # noqa: E402

import httpx  # noqa: E402
import numpy as np  # noqa: E402
import pytest  # noqa: E402

from app.core import config  # noqa: E402
from app.rag.index import (  # noqa: E402
    EmbedClient,
    EmbedError,
    EmbeddingStore,
    build_index,
    document_text,
    text_hash,
)
from app.schemas.place import Place  # noqa: E402


def make_place(poi_id: str = "huetripo:1", **overrides: object) -> Place:
    data: dict[str, object] = {
        "id": poi_id,
        "name": "Bún bò Mệ Kéo",
        "category": "restaurant",
        "lat": 16.47,
        "lon": 107.58,
        "address": "20 Bạch Đằng",
        "opening_hours_raw": "06:00-21:00",
        "opening_hours_confidence": "UNVERIFIED",
        "price_min_vnd": 30000,
        "price_max_vnd": 50000,
        "price_status": "REFERENCE_RANGE",
        "rating_value": 4.5,
        "rating_count": 120,
        "summary": "Quán bún bò lâu đời.",
        "source": "huetripo",
        "source_place_id": poi_id.split(":")[1],
        "collected_at": datetime(2026, 11, 1, tzinfo=timezone.utc),
        "raw_attributes": {"Loại hình (theo nguồn)": "Quán ăn", "Điện thoại": "0234 3826 123"},
    }
    data.update(overrides)
    return Place.model_validate(data)


def test_document_text_orders_fields_and_skips_missing_ones() -> None:
    text = document_text(make_place())
    assert text == (
        "Bún bò Mệ Kéo. quán ăn. Loại hình: Quán ăn. Địa chỉ: 20 Bạch Đằng. "
        "Giờ mở cửa: 06:00-21:00. Giá: 30.000đ – 50.000đ. Điện thoại: 0234 3826 123. "
        "Đánh giá: 4.5/5 (120 lượt). Quán bún bò lâu đời."
    )
    bare = document_text(make_place(address=None, opening_hours_raw=None, price_min_vnd=None,
                                    price_max_vnd=None, price_status="UNKNOWN", rating_value=None,
                                    rating_count=None, summary=None, raw_attributes={}))
    assert bare == "Bún bò Mệ Kéo. quán ăn"


def test_text_hash_is_stable_and_changes_with_text() -> None:
    assert text_hash("a") == text_hash("a")
    assert text_hash("a") != text_hash("b")


def _embed_handler(calls: list[dict]):
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        calls.append(body)
        vectors = [[float(len(text)), 1.0, 0.0] for text in body["input"]]
        return httpx.Response(200, json={"embeddings": vectors, "prompt_eval_count": 5})
    return handler


def test_embed_client_posts_model_and_inputs() -> None:
    calls: list[dict] = []
    client = EmbedClient("http://ollama.test", "bge-m3", transport=httpx.MockTransport(_embed_handler(calls)))
    assert client.embed(["ab", "abc"]) == [[2.0, 1.0, 0.0], [3.0, 1.0, 0.0]]
    assert calls == [{"model": "bge-m3", "input": ["ab", "abc"]}]


def test_embed_client_raises_on_wrong_count() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"embeddings": [[1.0]]})
    client = EmbedClient("http://ollama.test", "bge-m3", transport=httpx.MockTransport(handler))
    with pytest.raises(EmbedError):
        client.embed(["a", "b"])


def test_build_index_embeds_only_changed_rows_and_deletes_removed(tmp_path) -> None:
    calls: list[dict] = []
    client = EmbedClient("http://ollama.test", "bge-m3", transport=httpx.MockTransport(_embed_handler(calls)))
    store = EmbeddingStore(tmp_path / "rag.sqlite")
    first = [make_place("huetripo:1"), make_place("huetripo:2", name="Chè Hẻm")]
    assert build_index(first, store, client, batch=1).embedded == 2
    assert len(calls) == 2

    calls.clear()
    second = [make_place("huetripo:1"), make_place("huetripo:3", name="Cơm hến")]
    stats = build_index(second, store, client)
    assert (stats.embedded, stats.unchanged, stats.deleted) == (1, 1, 1)
    assert calls[0]["input"] == [document_text(second[1])]
    assert store.all_ids() == {"huetripo:1", "huetripo:3"}


def test_store_load_returns_normalised_float32_matrix(tmp_path) -> None:
    store = EmbeddingStore(tmp_path / "rag.sqlite")
    store.upsert("bge-m3", [("huetripo:2", "h2", [0.0, 3.0]), ("huetripo:1", "h1", [4.0, 0.0])])
    ids, matrix = store.load("bge-m3")
    assert ids == ["huetripo:1", "huetripo:2"]
    assert matrix.dtype == np.float32
    np.testing.assert_allclose(matrix, [[1.0, 0.0], [0.0, 1.0]])
    assert store.load("other-model")[1].shape == (0, 0)


def test_config_defaults(monkeypatch) -> None:
    for name in ("RAG_ENABLED", "RAG_EMBED_MODEL", "RAG_GEN_MODEL", "RAG_INDEX_PATH", "QU_MODEL"):
        monkeypatch.delenv(name, raising=False)
    assert config.rag_enabled() is True
    assert config.rag_embed_model() == "bge-m3"
    assert config.rag_gen_model() == "qwen3.5:4b"
    assert config.rag_index_path() == config.DATA_DIR / "rag_index.sqlite"
    monkeypatch.setenv("RAG_ENABLED", "off")
    assert config.rag_enabled() is False
