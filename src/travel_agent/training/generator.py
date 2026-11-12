"""Gọi model sinh lịch trình. Code eval chỉ phụ thuộc Protocol `PlanGenerator`."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any, Protocol

DEFAULT_HOST = "http://127.0.0.1:11434"

_TIME_PATTERN = "^([01][0-9]|2[0-3]):[0-5][0-9]$"
_DATE_PATTERN = "^[0-9]{4}-[0-9]{2}-[0-9]{2}$"

# Schema viết tay, cùng hình dạng với `Itinerary`. Không dùng `Itinerary.model_json_schema()`:
# nó sinh `format: time`, mà grammar của llama.cpp (Ollama) có thể đòi hậu tố múi giờ.
# Test giữ hai bên khớp nhau. Giờ và ngày chỉ ràng buộc bằng pattern, không có từ khóa `format`.
ITINERARY_FORMAT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "days": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "properties": {
                    "date": {"type": "string", "pattern": _DATE_PATTERN},
                    "stops": {
                        "type": "array",
                        "minItems": 1,
                        "items": {
                            "type": "object",
                            "properties": {
                                "place_id": {"type": "string", "minLength": 1},
                                "arrive": {"type": "string", "pattern": _TIME_PATTERN},
                                "depart": {"type": "string", "pattern": _TIME_PATTERN},
                                "note": {"type": ["string", "null"]},
                            },
                            "required": ["place_id", "arrive", "depart"],
                        },
                    },
                },
                "required": ["date", "stops"],
            },
        }
    },
    "required": ["days"],
}

Transport = Callable[[str, dict[str, Any], float], dict[str, Any]]


class GenerationError(RuntimeError):
    """Lỗi hạ tầng khi gọi model (mạng, timeout, model chưa pull). Không phải lỗi của model."""


class PlanGenerator(Protocol):
    def generate(self, messages: list[dict[str, str]]) -> str: ...


def http_post_json(url: str, payload: dict[str, Any], timeout_s: float) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as response:
            decoded = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise GenerationError(f"Gọi Ollama thất bại: {exc}") from exc
    if not isinstance(decoded, dict):
        raise GenerationError("Ollama trả về dữ liệu không phải JSON object")
    return decoded


class OllamaGenerator:
    """Gọi `/api/chat` của Ollama, thinking tắt, ép output theo `ITINERARY_FORMAT_SCHEMA`.

    `schema_format=False` dùng `format: "json"` cho bản Ollama không nhận schema này.
    """

    def __init__(
        self,
        model: str,
        *,
        host: str = DEFAULT_HOST,
        temperature: float = 0.0,
        seed: int = 0,
        num_predict: int = 2048,
        timeout_s: float = 600.0,
        schema_format: bool = True,
        transport: Transport | None = None,
    ) -> None:
        self._model = model
        self._url = f"{host.rstrip('/')}/api/chat"
        self._options = {"temperature": temperature, "seed": seed, "num_predict": num_predict}
        self._timeout_s = timeout_s
        self._format: dict[str, Any] | str = ITINERARY_FORMAT_SCHEMA if schema_format else "json"
        self._transport = transport or http_post_json

    def generate(self, messages: list[dict[str, str]]) -> str:
        payload = {
            "model": self._model,
            "messages": messages,
            "stream": False,
            "think": False,
            "format": self._format,
            "options": self._options,
        }
        response = self._transport(self._url, payload, self._timeout_s)
        message = response.get("message")
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str):
            raise GenerationError(f"Ollama không trả nội dung: {response.get('error', response)}")
        return content
