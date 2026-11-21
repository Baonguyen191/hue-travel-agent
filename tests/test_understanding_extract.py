"""OllamaExtractor against a fake HTTP transport: valid reply, retry, timeouts and bad replies."""

from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path

_BACKEND = _Path(__file__).resolve().parents[1] / "backend"
if str(_BACKEND) not in _sys.path:
    _sys.path.insert(0, str(_BACKEND))

import datetime as dt  # noqa: E402
import json  # noqa: E402
from typing import Any  # noqa: E402

import httpx  # noqa: E402
import pytest  # noqa: E402

from app.understanding.extract import (  # noqa: E402
    EXTRACTION_SCHEMA,
    ExtractionError,
    OllamaExtractor,
    build_messages,
    build_request_body,
)
from app.understanding.models import Intent, PlanChangeKind  # noqa: E402

REF = dt.date(2026, 11, 18)
VALID: dict[str, Any] = {
    "intent": "plan_new",
    "date_text": "cuối tuần này",
    "duration_text": "2 ngày",
    "origin": None,
    "people": None,
    "rooms": None,
    "budget_text": None,
    "city": None,
    "interest_phrases": ["đi chùa"],
    "must_include_mentions": [],
    "exclude_mentions": [],
    "exclude_category_phrases": [],
    "soft_preferences": [],
    "changes": [],
    "approve_option": None,
}


def _reply(content: str) -> httpx.Response:
    return httpx.Response(200, json={"message": {"role": "assistant", "content": content}})


def _extractor(handler: Any) -> OllamaExtractor:
    return OllamaExtractor(
        "http://ollama.test", "qwen3.5:4b", transport=httpx.MockTransport(handler)
    )


def test_valid_reply_becomes_an_extraction() -> None:
    extractor = _extractor(lambda request: _reply(json.dumps(VALID, ensure_ascii=False)))

    result = extractor.extract("Cuối tuần này đi Huế 2 ngày, thích đi chùa", REF)

    assert result.intent is Intent.PLAN_NEW
    assert result.date_text == "cuối tuần này"
    assert result.interest_phrases == ["đi chùa"]


def test_request_body_asks_for_schema_without_thinking_or_streaming() -> None:
    seen: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        assert request.url.path == "/api/chat"
        return _reply(json.dumps(VALID))

    _extractor(handler).extract("Đi Huế 2 ngày", REF)

    body = seen[0]
    assert body["model"] == "qwen3.5:4b"
    assert body["format"] == EXTRACTION_SCHEMA
    assert body["stream"] is False
    assert body["think"] is False
    assert body["options"] == {"temperature": 0}


def test_invalid_json_is_retried_once_then_accepted() -> None:
    replies = iter(["không phải json", json.dumps(VALID)])
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return _reply(next(replies))

    result = _extractor(handler).extract("Đi Huế 2 ngày", REF)

    assert len(calls) == 2
    assert result.duration_text == "2 ngày"


def test_two_bad_replies_raise_extraction_error() -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return _reply(json.dumps({"intent": "dance"}))

    with pytest.raises(ExtractionError):
        _extractor(handler).extract("Đi Huế 2 ngày", REF)
    assert len(calls) == 2


def test_timeout_raises_extraction_error_without_retry() -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        raise httpx.ReadTimeout("quá 30 giây", request=request)

    with pytest.raises(ExtractionError):
        _extractor(handler).extract("Đi Huế 2 ngày", REF)
    assert len(calls) == 1


def test_connection_refused_raises_extraction_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    with pytest.raises(ExtractionError):
        _extractor(handler).extract("Đi Huế 2 ngày", REF)


def test_http_error_status_raises_extraction_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "model not found"})

    with pytest.raises(ExtractionError):
        _extractor(handler).extract("Đi Huế 2 ngày", REF)


def test_reply_without_message_content_raises_extraction_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"done": True})

    with pytest.raises(ExtractionError):
        _extractor(handler).extract("Đi Huế 2 ngày", REF)


def test_extra_keys_in_reply_are_rejected_and_retried() -> None:
    replies = iter([json.dumps({**VALID, "travel_mode": "car"}), json.dumps(VALID)])

    def handler(request: httpx.Request) -> httpx.Response:
        return _reply(next(replies))

    assert _extractor(handler).extract("Đi Huế 2 ngày", REF).duration_text == "2 ngày"


def test_schema_lists_every_intent_and_change_kind() -> None:
    properties = EXTRACTION_SCHEMA["properties"]
    assert set(properties["intent"]["enum"]) == {item.value for item in Intent}
    kinds = properties["changes"]["items"]["properties"]["kind"]["enum"]
    assert set(kinds) == {item.value for item in PlanChangeKind}


def test_messages_hold_system_prompt_examples_and_the_new_message() -> None:
    messages = build_messages("Đi Huế 2 ngày", REF)

    assert messages[0]["role"] == "system"
    assert messages[-1]["role"] == "user"
    assert "Đi Huế 2 ngày" in messages[-1]["content"]
    assert "18" in messages[-1]["content"]
    assert len(messages) > 4


def test_request_body_is_deterministic() -> None:
    body = build_request_body("m", [{"role": "user", "content": "x"}])
    assert body["options"]["temperature"] == 0
    assert body["format"]["additionalProperties"] is False
