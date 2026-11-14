"""Gọi model sinh lịch trình. Code eval chỉ phụ thuộc Protocol `PlanGenerator`."""

from __future__ import annotations

import http.client
import json
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any, Protocol, TypeVar

from pydantic import BaseModel

DEFAULT_HOST = "http://127.0.0.1:11434"

_TIME_PATTERN = "^([01][0-9]|2[0-3]):[0-5][0-9]$"
_DATE_PATTERN = "^[0-9]{4}-[0-9]{2}-[0-9]{2}$"


def itinerary_format_schema(num_days: int | None) -> dict[str, Any]:
    """Schema viết tay, cùng hình dạng với `Itinerary`; `num_days` ép đúng số phần tử của `days`.

    Không dùng `Itinerary.model_json_schema()`: nó sinh `format: time`, mà grammar của llama.cpp
    (Ollama) có thể đòi hậu tố múi giờ. Test giữ hai bên khớp nhau. Giờ và ngày chỉ ràng buộc
    bằng pattern, không có từ khóa `format`.
    """
    days: dict[str, Any] = {
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
    if num_days is not None:
        days["minItems"] = num_days
        days["maxItems"] = num_days
    return {"type": "object", "properties": {"days": days}, "required": ["days"]}


# Schema không ràng buộc số ngày; dùng khi caller không truyền schema riêng.
ITINERARY_FORMAT_SCHEMA: dict[str, Any] = itinerary_format_schema(None)

_T = TypeVar("_T")

Transport = Callable[[str, dict[str, Any], float], dict[str, Any]]


class GenerationError(RuntimeError):
    """Lỗi hạ tầng khi gọi model (mạng, timeout, model chưa pull). Không phải lỗi của model."""


class Generation(BaseModel):
    """Một lần model trả lời: nội dung thô cùng thông tin Ollama cho biết khi có."""

    content: str
    done_reason: str | None = None  # "stop" là tự dừng, "length" là chạm num_predict
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


class PlanGenerator(Protocol):
    def generate(
        self, messages: list[dict[str, str]], format_schema: dict[str, Any] | None = None
    ) -> Generation: ...


def http_post_json(url: str, payload: dict[str, Any], timeout_s: float) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as response:
            decoded = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        # Body có JSON {"error": ...} của Ollama: model chưa pull, think/format không hỗ trợ...
        raise GenerationError(f"Ollama trả HTTP {exc.code}: {_error_body(exc)}") from exc
    except (OSError, http.client.HTTPException, ValueError) as exc:
        # URLError, TimeoutError, ConnectionResetError là OSError; JSONDecodeError là ValueError.
        raise GenerationError(f"Gọi Ollama thất bại: {exc}") from exc
    if not isinstance(decoded, dict):
        raise GenerationError("Ollama trả về dữ liệu không phải JSON object")
    return decoded


def _error_body(error: urllib.error.HTTPError) -> str:
    try:
        body = error.read().decode("utf-8", errors="replace").strip()
    except (OSError, http.client.HTTPException, AttributeError):
        body = ""
    return body or str(error.reason)


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
        num_ctx: int = 8192,
        timeout_s: float = 600.0,
        schema_format: bool = True,
        transport: Transport | None = None,
    ) -> None:
        self._model = model
        self._url = f"{host.rstrip('/')}/api/chat"
        self._options = {
            "temperature": temperature,
            "seed": seed,
            "num_predict": num_predict,
            "num_ctx": num_ctx,
        }
        self._timeout_s = timeout_s
        self._schema_format = schema_format
        self._transport = transport or http_post_json

    def generate(
        self, messages: list[dict[str, str]], format_schema: dict[str, Any] | None = None
    ) -> Generation:
        """`format_schema` thay schema mặc định cho lần gọi này (trừ khi `schema_format=False`)."""
        output_format: dict[str, Any] | str = "json"
        if self._schema_format:
            output_format = format_schema or ITINERARY_FORMAT_SCHEMA
        payload = {
            "model": self._model,
            "messages": messages,
            "stream": False,
            "think": False,
            "format": output_format,
            "options": self._options,
        }
        response = self._transport(self._url, payload, self._timeout_s)
        message = response.get("message")
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str):
            raise GenerationError(f"Ollama không trả nội dung: {response.get('error', response)}")
        return Generation(
            content=content,
            done_reason=_optional(response.get("done_reason"), str),
            prompt_tokens=_optional(response.get("prompt_eval_count"), int),
            completion_tokens=_optional(response.get("eval_count"), int),
        )


def _optional(value: object, kind: type[_T]) -> _T | None:
    """Giá trị đúng kiểu thì giữ, thiếu hoặc sai kiểu thì None (bool không tính là int)."""
    if isinstance(value, kind) and not isinstance(value, bool):
        return value
    return None
