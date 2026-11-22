"""Retriever: BM25 without diacritics, RRF, filters, anchor radius, BM25-only fallback."""

from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path

_BACKEND = _Path(__file__).resolve().parents[1] / "backend"
if str(_BACKEND) not in _sys.path:
    _sys.path.insert(0, str(_BACKEND))
_TESTS = _Path(__file__).resolve().parent
if str(_TESTS) not in _sys.path:
    _sys.path.insert(0, str(_TESTS))

import logging  # noqa: E402

import httpx  # noqa: E402
import pytest  # noqa: E402

from app.rag import retrieve as retrieve_module  # noqa: E402
from app.rag.index import EmbedClient, EmbeddingStore  # noqa: E402
from app.rag.retrieve import BM25, Retriever, rrf, tokenize  # noqa: E402
from app.understanding.models import Intent, ParsedQuery, PlaceMention, QuSource  # noqa: E402
from test_rag_index import make_place  # noqa: E402

PLACES = [
    make_place("huetripo:1", name="Đại Nội", category="historic", lat=16.4698, lon=107.5786,
               summary="Hoàng thành triều Nguyễn."),
    make_place("huetripo:2", name="Bún bò Mệ Kéo", category="restaurant", lat=16.4710, lon=107.5800),
    make_place("huetripo:3", name="Chùa Thiên Mụ", category="religious", lat=16.4530, lon=107.5450,
               summary="Ngôi chùa cổ yên tĩnh bên sông Hương."),
    make_place("huetripo:4", name="Bún bò xa", category="restaurant", lat=16.30, lon=107.70),
]


@pytest.fixture(autouse=True)
def _reset_warned(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(retrieve_module, "_warned", False)


def _failing_client() -> EmbedClient:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    return EmbedClient("http://ollama.test", "bge-m3", transport=httpx.MockTransport(handler))


def _retrieve_warnings(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.name == retrieve_module.logger.name and r.levelno == logging.WARNING]


def _parsed(poi_id: str | None = None, text: str = "Đại Nội") -> ParsedQuery:
    mention = PlaceMention(text=text, poi_id=poi_id, name=text, score=1.0) if poi_id else None
    return ParsedQuery(intent=Intent.PLACE_INFO, source=QuSource.RULES, place_query=mention)


def test_tokenize_folds_diacritics() -> None:
    assert tokenize("Bún bò Mệ Kéo!") == ["bun", "bo", "me", "keo"]


def test_bm25_ranks_matching_document_first() -> None:
    bm25 = BM25([["bun", "bo"], ["chua", "thien", "mu"], ["bun", "rieu"]])
    scores = bm25.scores(["bun", "bo"])
    assert scores[0] > scores[2] > scores[1] == 0.0


def test_rrf_sums_reciprocal_ranks() -> None:
    fused = rrf([["a", "b"], ["b", "c"]], k=60)
    assert fused["b"] == 1 / 61 + 1 / 62
    assert max(fused, key=fused.get) == "b"


def test_bm25_only_mode_without_store_and_diacritic_free_query() -> None:
    result = Retriever(PLACES).retrieve("chua thien mu", None, k=2)
    assert result.mode == "bm25"
    assert result.hits[0].poi_id == "huetripo:3"
    assert result.hits[0].bm25_rank == 1 and result.hits[0].dense_rank is None


def test_no_lexical_match_and_no_dense_gives_no_hits() -> None:
    assert Retriever(PLACES).retrieve("wifi khách sạn", None).hits == []


def test_category_filter_keeps_only_restaurants() -> None:
    result = Retriever(PLACES).retrieve("quán ăn bún bò ngon", None, k=5)
    ids = {hit.poi_id for hit in result.hits}
    assert ids <= {"huetripo:2", "huetripo:4"}
    assert "huetripo:2" in ids


def test_anchor_keeps_places_within_radius_and_removes_the_anchor() -> None:
    result = Retriever(PLACES).retrieve("quán bún bò gần Đại Nội", _parsed("huetripo:1"), k=5)
    ids = [hit.poi_id for hit in result.hits]
    assert ids[0] == "huetripo:2"
    assert "huetripo:1" not in ids and "huetripo:4" not in ids
    assert result.hits[0].distance_km is not None and result.hits[0].distance_km < 1


def test_linked_place_is_boosted_for_single_place_questions() -> None:
    result = Retriever(PLACES).retrieve("Đại Nội mấy giờ mở cửa", _parsed("huetripo:1"), k=3)
    assert result.hits[0].poi_id == "huetripo:1"


def test_hybrid_mode_uses_dense_ranking(tmp_path) -> None:
    store = EmbeddingStore(tmp_path / "rag.sqlite")
    store.upsert("bge-m3", [
        ("huetripo:1", "h", [0.0, 1.0]), ("huetripo:2", "h", [0.0, 1.0]),
        ("huetripo:3", "h", [1.0, 0.0]), ("huetripo:4", "h", [0.0, 1.0]),
    ])

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"embeddings": [[1.0, 0.0]]})

    client = EmbedClient("http://ollama.test", "bge-m3", transport=httpx.MockTransport(handler))
    result = Retriever(PLACES, store, client).retrieve("nơi yên bình để tĩnh tâm", None, k=2)
    assert result.mode == "hybrid"
    assert result.hits[0].poi_id == "huetripo:3"
    assert result.hits[0].dense_rank == 1


def test_only_places_with_stored_vectors_get_dense_ranks(tmp_path) -> None:
    store = EmbeddingStore(tmp_path / "rag.sqlite")
    store.upsert("bge-m3", [("huetripo:3", "h", [1.0, 0.0])])

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"embeddings": [[1.0, 0.0]]})

    client = EmbedClient("http://ollama.test", "bge-m3", transport=httpx.MockTransport(handler))
    result = Retriever(PLACES, store, client).retrieve("nơi yên bình để tĩnh tâm", None, k=4)
    assert result.mode == "hybrid"
    ranked = {hit.poi_id: hit.dense_rank for hit in result.hits if hit.dense_rank is not None}
    assert ranked == {"huetripo:3": 1}


def test_empty_store_warns_once_and_uses_bm25(tmp_path, caplog) -> None:
    store = EmbeddingStore(tmp_path / "rag.sqlite")
    with caplog.at_level(logging.WARNING, logger=retrieve_module.logger.name):
        retriever = Retriever(PLACES, store, _failing_client())
        result = retriever.retrieve("chùa Thiên Mụ", None)
        retriever.retrieve("chùa Thiên Mụ", None)
    assert result.mode == "bm25"
    records = _retrieve_warnings(caplog)
    assert len(records) == 1
    assert "BM25 only" in records[0].getMessage()


def test_embed_failure_warns_once_across_calls(tmp_path, caplog) -> None:
    store = EmbeddingStore(tmp_path / "rag.sqlite")
    store.upsert("bge-m3", [("huetripo:3", "h", [1.0, 0.0])])
    retriever = Retriever(PLACES, store, _failing_client())
    with caplog.at_level(logging.WARNING, logger=retrieve_module.logger.name):
        first = retriever.retrieve("chùa Thiên Mụ", None)
        second = retriever.retrieve("chùa Thiên Mụ", None)
    assert first.mode == second.mode == "bm25"
    assert len(_retrieve_warnings(caplog)) == 1


def test_plain_retriever_without_store_is_quiet(caplog) -> None:
    with caplog.at_level(logging.WARNING, logger=retrieve_module.logger.name):
        Retriever(PLACES).retrieve("chùa Thiên Mụ", None)
    assert _retrieve_warnings(caplog) == []


def test_embed_failure_falls_back_to_bm25(tmp_path) -> None:
    store = EmbeddingStore(tmp_path / "rag.sqlite")
    store.upsert("bge-m3", [("huetripo:3", "h", [1.0, 0.0])])

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    client = EmbedClient("http://ollama.test", "bge-m3", transport=httpx.MockTransport(handler))
    result = Retriever(PLACES, store, client).retrieve("chùa Thiên Mụ", None)
    assert result.mode == "bm25"
    assert result.hits[0].poi_id == "huetripo:3"
