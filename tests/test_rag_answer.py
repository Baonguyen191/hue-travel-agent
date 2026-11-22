"""RAG answerer: JSON parsing, citation filtering, refusals, retry, fallback, fact checks."""

from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path

_BACKEND = _Path(__file__).resolve().parents[1] / "backend"
if str(_BACKEND) not in _sys.path:
    _sys.path.insert(0, str(_BACKEND))
_TESTS = _Path(__file__).resolve().parent
if str(_TESTS) not in _sys.path:
    _sys.path.insert(0, str(_TESTS))

import json  # noqa: E402

import httpx  # noqa: E402

from app.core.usage import record_usage  # noqa: E402
from app.rag.answer import REFUSAL_TEXT, RagAnswerer, strip_citations  # noqa: E402
from app.rag.retrieve import Retriever  # noqa: E402
from test_rag_retrieve import PLACES  # noqa: E402


def _answerer(replies: list[object]) -> tuple[RagAnswerer, list[dict]]:
    bodies: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        reply = replies[min(len(bodies) - 1, len(replies) - 1)]
        if isinstance(reply, int):
            return httpx.Response(reply)
        content = reply if isinstance(reply, str) else json.dumps(reply, ensure_ascii=False)
        return httpx.Response(200, json={"message": {"content": content}, "prompt_eval_count": 300, "eval_count": 30})

    answerer = RagAnswerer(
        Retriever(PLACES), lambda place: f"TEMPLATE {place.name}", "http://ollama.test", "qwen3.5:4b",
        transport=httpx.MockTransport(handler),
    )
    return answerer, bodies


def test_llm_answer_with_valid_citation() -> None:
    answerer, bodies = _answerer([{
        "answer": "Chùa Thiên Mụ là ngôi chùa cổ yên tĩnh [huetripo:3].",
        "cited_poi_ids": ["huetripo:3"], "answerable": True,
    }])
    with record_usage() as usage:
        result = answerer.answer("chùa Thiên Mụ có gì")
    assert result.source == "llm"
    assert result.cited_poi_ids == ["huetripo:3"]
    assert result.text == "Chùa Thiên Mụ là ngôi chùa cổ yên tĩnh."
    assert "[huetripo:3]" in result.raw_text
    assert "[huetripo:3]" in bodies[0]["messages"][-1]["content"]
    assert bodies[0]["format"]["required"] == ["answer", "cited_poi_ids", "answerable"]
    assert usage["rag_generator"].total_tokens == 330


def test_ids_outside_the_context_are_dropped_and_no_valid_id_means_refusal() -> None:
    answerer, _ = _answerer([{"answer": "Có [huetripo:999].", "cited_poi_ids": ["huetripo:999"], "answerable": True}])
    result = answerer.answer("chùa Thiên Mụ")
    assert result.source == "refusal"
    assert result.cited_poi_ids == [] and result.answerable is False
    assert result.text == REFUSAL_TEXT


def test_model_refusal_keeps_its_sentence() -> None:
    answerer, _ = _answerer([{"answer": "Dữ liệu không có thông tin wifi.", "cited_poi_ids": [], "answerable": False}])
    result = answerer.answer("chùa Thiên Mụ có wifi không")
    assert (result.source, result.text) == ("refusal", "Dữ liệu không có thông tin wifi.")


def test_empty_retrieval_refuses_without_calling_the_llm() -> None:
    answerer, bodies = _answerer([500])
    result = answerer.answer("wifi khách sạn")
    assert result.source == "refusal" and bodies == []


def test_invalid_json_is_retried_once_then_falls_back_to_the_template() -> None:
    answerer, bodies = _answerer(["not json", "still not json"])
    result = answerer.answer("chùa Thiên Mụ")
    assert len(bodies) == 2
    assert result.source == "fallback"
    assert result.text == "TEMPLATE Chùa Thiên Mụ"
    assert result.cited_poi_ids == ["huetripo:3"]
    assert result.error


def test_second_attempt_can_succeed() -> None:
    good = {"answer": "Chùa cổ [huetripo:3].", "cited_poi_ids": ["huetripo:3"], "answerable": True}
    answerer, bodies = _answerer([500, good])
    assert answerer.answer("chùa Thiên Mụ").source == "llm"
    assert len(bodies) == 2


def test_fact_mismatch_falls_back_to_the_template() -> None:
    answerer, _ = _answerer([{
        "answer": "Chùa Thiên Mụ mở cửa 03:00 [huetripo:3].", "cited_poi_ids": ["huetripo:3"], "answerable": True,
    }])
    result = answerer.answer("chùa Thiên Mụ mấy giờ mở cửa")
    assert result.source == "fallback"
    assert [m.kind for m in result.mismatches] == ["time"]


def test_malformed_ollama_message_falls_back_without_raising() -> None:
    bodies: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json={"message": None, "prompt_eval_count": 1, "eval_count": 1})

    answerer = RagAnswerer(
        Retriever(PLACES), lambda place: f"TEMPLATE {place.name}", "http://ollama.test", "qwen3.5:4b",
        transport=httpx.MockTransport(handler),
    )
    result = answerer.answer("chùa Thiên Mụ")
    assert len(bodies) == 2
    assert result.source == "fallback"
    assert result.text == "TEMPLATE Chùa Thiên Mụ"
    assert result.error


def test_strip_citations() -> None:
    assert strip_citations("A [huetripo:1]. B [huetripo:2] và C.") == "A. B và C."
