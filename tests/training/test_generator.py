import http.client
import io
import json
import re
import urllib.error
import urllib.request
from typing import Any

import pytest

from tests.training.factories import VALID_RAW
from travel_agent.training.generator import (
    ITINERARY_FORMAT_SCHEMA,
    Generation,
    GenerationError,
    OllamaGenerator,
    http_post_json,
    itinerary_format_schema,
)
from travel_agent.training.parsing import parse_itinerary

MESSAGES = [{"role": "system", "content": "s"}, {"role": "user", "content": "u"}]


class FakeTransport:
    def __init__(self, response: dict[str, Any]) -> None:
        self.response = response
        self.calls: list[tuple[str, dict[str, Any], float]] = []

    def __call__(self, url: str, payload: dict[str, Any], timeout_s: float) -> dict[str, Any]:
        self.calls.append((url, payload, timeout_s))
        return self.response


def test_sends_chat_request_with_thinking_off_and_schema() -> None:
    transport = FakeTransport({"message": {"content": '{"days": []}'}})
    generator = OllamaGenerator(
        "model-x", temperature=0.2, seed=5, num_predict=512, transport=transport
    )
    assert generator.generate(MESSAGES) == Generation(content='{"days": []}')
    [(url, payload, timeout_s)] = transport.calls
    assert url == "http://127.0.0.1:11434/api/chat"
    assert timeout_s == 600.0
    assert payload == {
        "model": "model-x",
        "messages": MESSAGES,
        "stream": False,
        "think": False,
        "format": ITINERARY_FORMAT_SCHEMA,
        "options": {"temperature": 0.2, "seed": 5, "num_predict": 512, "num_ctx": 8192},
    }


def test_plain_json_format_when_schema_disabled() -> None:
    transport = FakeTransport({"message": {"content": "{}"}})
    OllamaGenerator("model-x", schema_format=False, transport=transport).generate(MESSAGES)
    assert transport.calls[0][1]["format"] == "json"


def test_schema_pins_day_count() -> None:
    days = itinerary_format_schema(3)["properties"]["days"]
    assert (days["minItems"], days["maxItems"]) == (3, 3)


def test_schema_without_day_count_is_the_default() -> None:
    assert itinerary_format_schema(None) == ITINERARY_FORMAT_SCHEMA
    days = ITINERARY_FORMAT_SCHEMA["properties"]["days"]
    assert days["minItems"] == 1
    assert "maxItems" not in days


def test_pinned_schema_rejects_wrong_day_count() -> None:
    stop = {"place_id": "t:a", "arrive": "09:00", "depart": "10:00"}
    one_day = {"days": [{"date": "2026-12-01", "stops": [stop]}]}
    two_days = {"days": [*one_day["days"], {"date": "2026-12-02", "stops": [stop]}]}
    assert _conforms(itinerary_format_schema(1), one_day)
    assert not _conforms(itinerary_format_schema(2), one_day)
    assert not _conforms(itinerary_format_schema(1), two_days)


def test_generate_sends_per_call_schema() -> None:
    transport = FakeTransport({"message": {"content": "{}"}})
    generator = OllamaGenerator("model-x", transport=transport)
    generator.generate(MESSAGES, format_schema=itinerary_format_schema(2))
    assert transport.calls[0][1]["format"]["properties"]["days"]["maxItems"] == 2


def test_plain_json_mode_ignores_per_call_schema() -> None:
    transport = FakeTransport({"message": {"content": "{}"}})
    generator = OllamaGenerator("model-x", schema_format=False, transport=transport)
    generator.generate(MESSAGES, format_schema=itinerary_format_schema(2))
    assert transport.calls[0][1]["format"] == "json"


def test_missing_content_raises() -> None:
    transport = FakeTransport({"error": "model not found"})
    with pytest.raises(GenerationError, match="model not found"):
        OllamaGenerator("model-x", transport=transport).generate(MESSAGES)


def _keys(node: Any) -> set[str]:
    """Mọi khóa xuất hiện ở bất kỳ độ sâu nào trong schema."""
    if isinstance(node, dict):
        return set(node) | {key for value in node.values() for key in _keys(value)}
    if isinstance(node, list):
        return {key for value in node for key in _keys(value)}
    return set()


def _conforms(schema: dict[str, Any], value: Any) -> bool:
    """Kiểm tra tối thiểu các từ khóa schema viết tay dùng (không thêm thư viện jsonschema)."""
    kind = schema["type"]
    if isinstance(kind, list):
        return any(_conforms({**schema, "type": option}, value) for option in kind)
    if kind == "null":
        return value is None
    if kind == "string":
        pattern = schema.get("pattern")
        return isinstance(value, str) and (pattern is None or re.search(pattern, value) is not None)
    if kind == "array":
        items = schema["items"]
        return (
            isinstance(value, list)
            and len(value) >= schema.get("minItems", 0)
            and len(value) <= schema.get("maxItems", len(value))
            and all(_conforms(items, item) for item in value)
        )
    assert kind == "object"
    properties = schema["properties"]
    return (
        isinstance(value, dict)
        and set(schema["required"]) <= set(value)
        and set(value) <= set(properties)
        and all(_conforms(properties[name], item) for name, item in value.items())
    )


def test_format_schema_has_no_format_keyword() -> None:
    """llama.cpp đòi hậu tố múi giờ cho `format: time`; schema viết tay chỉ dùng pattern."""
    assert "format" not in _keys(ITINERARY_FORMAT_SCHEMA)
    transport = FakeTransport({"message": {"content": "{}"}})
    OllamaGenerator("model-x", transport=transport).generate(MESSAGES)
    assert "format" not in _keys(transport.calls[0][1]["format"])


def test_valid_output_matches_format_schema_and_parses() -> None:
    """Giữ schema viết tay khớp hình dạng Itinerary."""
    assert _conforms(ITINERARY_FORMAT_SCHEMA, json.loads(VALID_RAW))
    assert parse_itinerary(VALID_RAW) is not None


def test_format_schema_rejects_timezone_suffix_and_missing_fields() -> None:
    stop = {"place_id": "p", "arrive": "08:30:00Z", "depart": "09:00"}
    assert not _conforms(
        ITINERARY_FORMAT_SCHEMA, {"days": [{"date": "2026-12-01", "stops": [stop]}]}
    )
    assert not _conforms(ITINERARY_FORMAT_SCHEMA, {"days": []})
    ok = {"place_id": "p", "arrive": "08:30", "depart": "09:00"}
    assert _conforms(ITINERARY_FORMAT_SCHEMA, {"days": [{"date": "2026-12-01", "stops": [ok]}]})


def test_generation_carries_done_reason_and_token_counts() -> None:
    transport = FakeTransport(
        {
            "message": {"content": "{}"},
            "done_reason": "length",
            "prompt_eval_count": 1500,
            "eval_count": 2048,
        }
    )
    generation = OllamaGenerator("model-x", transport=transport).generate(MESSAGES)
    assert generation == Generation(
        content="{}", done_reason="length", prompt_tokens=1500, completion_tokens=2048
    )


def test_generation_metadata_is_none_when_ollama_omits_it() -> None:
    transport = FakeTransport({"message": {"content": "{}"}, "done_reason": 7, "eval_count": "x"})
    generation = OllamaGenerator("model-x", transport=transport).generate(MESSAGES)
    assert (generation.done_reason, generation.prompt_tokens, generation.completion_tokens) == (
        None,
        None,
        None,
    )


def test_num_ctx_is_sent_in_options() -> None:
    transport = FakeTransport({"message": {"content": "{}"}})
    OllamaGenerator("model-x", num_ctx=16384, transport=transport).generate(MESSAGES)
    assert transport.calls[0][1]["options"]["num_ctx"] == 16384


def _raising_urlopen(exc: BaseException) -> Any:
    def urlopen(*args: Any, **kwargs: Any) -> Any:
        raise exc

    return urlopen


def test_http_error_message_includes_response_body(monkeypatch: pytest.MonkeyPatch) -> None:
    body = json.dumps({"error": "model 'qwen3.5:4b' not found"})
    error = urllib.error.HTTPError(
        "http://h/api/chat", 404, "Not Found", http.client.HTTPMessage(), io.BytesIO(body.encode())
    )
    monkeypatch.setattr(urllib.request, "urlopen", _raising_urlopen(error))
    with pytest.raises(GenerationError, match="model 'qwen3.5:4b' not found") as info:
        http_post_json("http://h/api/chat", {}, 1.0)
    assert "404" in str(info.value)
    assert "qwen3.5:4b" in str(info.value)


def test_http_error_with_unreadable_body_still_raises_generation_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    error = urllib.error.HTTPError(
        "http://h/api/chat", 500, "Server Error", http.client.HTTPMessage(), None
    )
    monkeypatch.setattr(urllib.request, "urlopen", _raising_urlopen(error))
    with pytest.raises(GenerationError, match="500"):
        http_post_json("http://h/api/chat", {}, 1.0)


@pytest.mark.parametrize(
    "exc",
    [
        ConnectionResetError("reset"),
        http.client.IncompleteRead(b"abc"),
        urllib.error.URLError("refused"),
        TimeoutError("timeout"),
    ],
)
def test_transport_failures_become_generation_error(
    monkeypatch: pytest.MonkeyPatch, exc: BaseException
) -> None:
    monkeypatch.setattr(urllib.request, "urlopen", _raising_urlopen(exc))
    with pytest.raises(GenerationError):
        http_post_json("http://h/api/chat", {}, 1.0)
