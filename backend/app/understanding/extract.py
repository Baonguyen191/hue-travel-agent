"""LLM extraction through a local Ollama server: the model copies phrases, code decides the rest.

`OllamaExtractor` posts to `/api/chat` with `format` set to a JSON schema, `stream` false,
`think` false and `options.temperature` 0. The model returns verbatim phrases (dates, durations,
place names, preferences); it never computes dates or values. A reply that does not match the
schema is retried once; a transport failure or a second bad reply raises `ExtractionError`.

Prompt and few-shot examples are written by hand and are not taken from the evaluation set.
"""

from __future__ import annotations

import datetime as dt
import json
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.understanding.models import ApproveOption, Intent, PlanChangeKind

MAX_ATTEMPTS = 2
DEFAULT_TIMEOUT = 30.0
_WEEKDAY_NAMES = ("thứ Hai", "thứ Ba", "thứ Tư", "thứ Năm", "thứ Sáu", "thứ Bảy", "Chủ nhật")
_NULLABLE_STRING: dict[str, Any] = {"type": ["string", "null"]}
_NULLABLE_INT: dict[str, Any] = {"type": ["integer", "null"]}
_STRING_LIST: dict[str, Any] = {"type": "array", "items": {"type": "string"}}
_CHANGE_ITEM: dict[str, Any] = {
    "type": "object",
    "properties": {
        "kind": {"type": "string", "enum": [item.value for item in PlanChangeKind]},
        "text": {"type": "string"},
        "value": _NULLABLE_STRING,
    },
    "required": ["kind", "text", "value"],
    "additionalProperties": False,
}

EXTRACTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "intent": {"type": "string", "enum": [item.value for item in Intent]},
        "date_text": _NULLABLE_STRING,
        "duration_text": _NULLABLE_STRING,
        "origin": _NULLABLE_STRING,
        "people": _NULLABLE_INT,
        "rooms": _NULLABLE_INT,
        "budget_text": _NULLABLE_STRING,
        "city": _NULLABLE_STRING,
        "interest_phrases": _STRING_LIST,
        "must_include_mentions": _STRING_LIST,
        "exclude_mentions": _STRING_LIST,
        "exclude_category_phrases": _STRING_LIST,
        "soft_preferences": _STRING_LIST,
        "changes": {"type": "array", "items": _CHANGE_ITEM},
        "approve_option": {
            "type": ["string", "null"],
            "enum": [*[item.value for item in ApproveOption], None],
        },
    },
    "required": [
        "intent",
        "date_text",
        "duration_text",
        "origin",
        "people",
        "rooms",
        "budget_text",
        "city",
        "interest_phrases",
        "must_include_mentions",
        "exclude_mentions",
        "exclude_category_phrases",
        "soft_preferences",
        "changes",
        "approve_option",
    ],
    "additionalProperties": False,
}


class ExtractionError(RuntimeError):
    """The model is unreachable, or it returned no valid JSON even after a retry."""


class ChangeItem(BaseModel):
    """One requested plan change as the model copied it."""

    model_config = ConfigDict(extra="forbid")

    kind: PlanChangeKind
    text: str = ""
    value: str | None = None


class Extraction(BaseModel):
    """The JSON the model returns. Every value is a copied phrase or a closed enum."""

    model_config = ConfigDict(extra="forbid")

    intent: Intent
    date_text: str | None = None
    duration_text: str | None = None
    origin: str | None = None
    people: int | None = None
    rooms: int | None = None
    budget_text: str | None = None
    city: str | None = None
    interest_phrases: list[str] = Field(default_factory=list)
    must_include_mentions: list[str] = Field(default_factory=list)
    exclude_mentions: list[str] = Field(default_factory=list)
    exclude_category_phrases: list[str] = Field(default_factory=list)
    soft_preferences: list[str] = Field(default_factory=list)
    changes: list[ChangeItem] = Field(default_factory=list)
    approve_option: ApproveOption | None = None


SYSTEM_PROMPT = """Bạn trích thông tin từ một tin nhắn nhờ lập lịch du lịch Huế.
Chỉ trả về JSON đúng schema, không giải thích.

Quy tắc chung:
- Chỉ chép nguyên văn từ tin nhắn. Không tự tính ngày: "cuối tuần này" giữ nguyên là
  "cuối tuần này", không đổi thành ngày.
- Không suy diễn trường không được nhắc. Không có thì để null (chuỗi, số) hoặc [] (danh sách).

Các trường:
- intent: plan_new (xin lập lịch đi chơi), modify_plan (sửa lịch đã có: bỏ điểm, thêm ngày,
  đổi số người), place_info (hỏi giờ mở cửa, giá vé, vị trí của một địa điểm), approve (đồng ý
  một gói ngân sách), book (xin đặt chỗ), out_of_scope (không phải du lịch Huế: thành phố khác,
  thời tiết, đặt vé, viết văn...).
- date_text: cụm chỉ thời điểm đi, chép nguyên văn, ví dụ "cuối tuần này", "thứ 7 tới", "20/12".
- duration_text: cụm chỉ số ngày đi, chép nguyên văn, ví dụ "2 ngày", "2n1đ".
- origin: nơi xuất phát nếu nêu rõ. city: thành phố đến nếu nêu rõ và không phải Huế.
- people, rooms: số người, số phòng nếu nêu rõ.
- budget_text: cụm ngân sách nguyên văn, ví dụ "khoảng 4 triệu".
- interest_phrases: cụm thể hiện sở thích người dùng muốn, ví dụ "đi chùa", "đặc sản".
  Chỉ ghi điều họ muốn, KHÔNG ghi điều họ không muốn. Tên địa điểm cụ thể không ghi ở đây.
- must_include_mentions: tên địa điểm cụ thể người dùng muốn đến, chép đúng cách họ viết.
  Với place_info, ghi tên địa điểm đang được hỏi vào đây.
- exclude_mentions: tên địa điểm cụ thể người dùng không muốn đến, hoặc đã đi rồi.
- exclude_category_phrases: loại địa điểm không muốn. "không đi chợ" ghi "chợ".
- soft_preferences: yêu cầu khác không có trường riêng, chép nguyên văn cụm.
- changes: với modify_plan, mỗi thay đổi một mục: kind (remove_place, add_place, add_days,
  remove_days, set_people, set_budget, cheaper, other...), text là cụm nguyên văn, value là số
  hoặc tên nếu có. Thêm ngày: kind add_days.
- approve_option: BUDGET, BALANCED hoặc COMFORT khi người dùng chọn một gói; không thì null.
"""

_EXAMPLES: tuple[tuple[str, dict[str, Any]], ...] = (
    (
        "Cuối tuần này cả nhà mình muốn đi Huế ba ngày, lịch nhẹ thôi, thích đặc sản và đi chùa.",
        {
            "intent": "plan_new",
            "date_text": "Cuối tuần này",
            "duration_text": "ba ngày",
            "origin": None,
            "people": None,
            "rooms": None,
            "budget_text": None,
            "city": None,
            "interest_phrases": ["đặc sản", "đi chùa"],
            "must_include_mentions": [],
            "exclude_mentions": [],
            "exclude_category_phrases": [],
            "soft_preferences": ["cả nhà đi cùng", "lịch nhẹ"],
            "changes": [],
            "approve_option": None,
        },
    ),
    (
        "Mai mình đi từ Đà Nẵng ra Huế, 2 người, 2 ngày 1 đêm, ngân sách khoảng 4 triệu, ghé Đại Nội.",
        {
            "intent": "plan_new",
            "date_text": "Mai",
            "duration_text": "2 ngày 1 đêm",
            "origin": "Đà Nẵng",
            "people": 2,
            "rooms": None,
            "budget_text": "khoảng 4 triệu",
            "city": None,
            "interest_phrases": [],
            "must_include_mentions": ["Đại Nội"],
            "exclude_mentions": [],
            "exclude_category_phrases": [],
            "soft_preferences": [],
            "changes": [],
            "approve_option": None,
        },
    ),
    (
        "Bỏ chùa Thiên Mụ khỏi lịch, thêm một ngày nữa cho mình.",
        {
            "intent": "modify_plan",
            "date_text": None,
            "duration_text": None,
            "origin": None,
            "people": None,
            "rooms": None,
            "budget_text": None,
            "city": None,
            "interest_phrases": [],
            "must_include_mentions": [],
            "exclude_mentions": ["chùa Thiên Mụ"],
            "exclude_category_phrases": [],
            "soft_preferences": [],
            "changes": [
                {"kind": "remove_place", "text": "bỏ chùa Thiên Mụ", "value": None},
                {"kind": "add_days", "text": "thêm một ngày nữa", "value": "1"},
            ],
            "approve_option": None,
        },
    ),
    (
        "Nhà thờ Phủ Cam có mở cửa buổi tối không?",
        {
            "intent": "place_info",
            "date_text": None,
            "duration_text": None,
            "origin": None,
            "people": None,
            "rooms": None,
            "budget_text": None,
            "city": None,
            "interest_phrases": [],
            "must_include_mentions": ["Nhà thờ Phủ Cam"],
            "exclude_mentions": [],
            "exclude_category_phrases": [],
            "soft_preferences": [],
            "changes": [],
            "approve_option": None,
        },
    ),
    (
        "Đi Đà Lạt 3 ngày từ 10/1 cho mình nhé.",
        {
            "intent": "out_of_scope",
            "date_text": "10/1",
            "duration_text": "3 ngày",
            "origin": None,
            "people": None,
            "rooms": None,
            "budget_text": None,
            "city": "Đà Lạt",
            "interest_phrases": [],
            "must_include_mentions": [],
            "exclude_mentions": [],
            "exclude_category_phrases": [],
            "soft_preferences": [],
            "changes": [],
            "approve_option": None,
        },
    ),
    (
        "Ngày 15 tháng 1 mình đi Huế bốn ngày, không đi chợ, thích cà phê.",
        {
            "intent": "plan_new",
            "date_text": "Ngày 15 tháng 1",
            "duration_text": "bốn ngày",
            "origin": None,
            "people": None,
            "rooms": None,
            "budget_text": None,
            "city": None,
            "interest_phrases": ["cà phê"],
            "must_include_mentions": [],
            "exclude_mentions": [],
            "exclude_category_phrases": ["chợ"],
            "soft_preferences": [],
            "changes": [],
            "approve_option": None,
        },
    ),
    (
        "Chọn gói tiết kiệm nhé.",
        {
            "intent": "approve",
            "date_text": None,
            "duration_text": None,
            "origin": None,
            "people": None,
            "rooms": None,
            "budget_text": None,
            "city": None,
            "interest_phrases": [],
            "must_include_mentions": [],
            "exclude_mentions": [],
            "exclude_category_phrases": [],
            "soft_preferences": [],
            "changes": [],
            "approve_option": "BUDGET",
        },
    ),
)


def _user_content(text: str, ref: dt.date) -> str:
    weekday = _WEEKDAY_NAMES[ref.weekday()]
    header = f"Hôm nay là {weekday}, {ref.isoformat()} (chỉ để tham khảo, không tự tính ngày)."
    return f"{header}\nTin nhắn: {text}"


def build_messages(text: str, ref: dt.date) -> list[dict[str, str]]:
    """System prompt, the hand-written examples as user/assistant turns, then the message."""
    messages: list[dict[str, str]] = [{"role": "system", "content": SYSTEM_PROMPT}]
    for example_text, answer in _EXAMPLES:
        messages.append({"role": "user", "content": _user_content(example_text, ref)})
        messages.append({"role": "assistant", "content": json.dumps(answer, ensure_ascii=False)})
    messages.append({"role": "user", "content": _user_content(text, ref)})
    return messages


def build_request_body(model: str, messages: list[dict[str, str]]) -> dict[str, Any]:
    """The /api/chat body: structured output, no streaming, no thinking, deterministic sampling."""
    return {
        "model": model,
        "messages": messages,
        "format": EXTRACTION_SCHEMA,
        "stream": False,
        "think": False,
        "options": {"temperature": 0},
    }


class OllamaExtractor:
    """Calls a local Ollama model and returns a validated `Extraction`."""

    def __init__(
        self,
        base_url: str,
        model: str,
        timeout: float = DEFAULT_TIMEOUT,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.model = model
        self._client = httpx.Client(base_url=base_url, timeout=timeout, transport=transport)

    def extract(self, text: str, ref: dt.date) -> Extraction:
        """Ask the model at most MAX_ATTEMPTS times; transport errors are not retried."""
        messages = build_messages(text, ref)
        last_error: ValidationError | None = None
        for _ in range(MAX_ATTEMPTS):
            content = self._chat(messages)
            try:
                return Extraction.model_validate_json(content)
            except ValidationError as error:
                last_error = error
        raise ExtractionError(f"Model trả JSON sai schema sau {MAX_ATTEMPTS} lần: {last_error}")

    def _chat(self, messages: list[dict[str, str]]) -> str:
        body = build_request_body(self.model, messages)
        try:
            response = self._client.post("/api/chat", json=body)
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as error:
            raise ExtractionError(f"Ollama không trả lời: {error}") from error
        content = payload.get("message", {}).get("content") if isinstance(payload, dict) else None
        if not isinstance(content, str):
            raise ExtractionError("Ollama trả về thiếu message.content")
        return content

    def close(self) -> None:
        """Release the HTTP connection pool."""
        self._client.close()
