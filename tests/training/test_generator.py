import json
import re
from typing import Any

import pytest

from tests.training.factories import VALID_RAW
from travel_agent.training.generator import (
    ITINERARY_FORMAT_SCHEMA,
    GenerationError,
    OllamaGenerator,
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
    assert generator.generate(MESSAGES) == '{"days": []}'
    [(url, payload, timeout_s)] = transport.calls
    assert url == "http://127.0.0.1:11434/api/chat"
    assert timeout_s == 600.0
    assert payload == {
        "model": "model-x",
        "messages": MESSAGES,
        "stream": False,
        "think": False,
        "format": ITINERARY_FORMAT_SCHEMA,
        "options": {"temperature": 0.2, "seed": 5, "num_predict": 512},
    }


def test_plain_json_format_when_schema_disabled() -> None:
    transport = FakeTransport({"message": {"content": "{}"}})
    OllamaGenerator("model-x", schema_format=False, transport=transport).generate(MESSAGES)
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
