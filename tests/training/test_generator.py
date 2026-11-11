from typing import Any

import pytest

from travel_agent.domain.models import Itinerary
from travel_agent.training.generator import GenerationError, OllamaGenerator

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
        "format": Itinerary.model_json_schema(),
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
