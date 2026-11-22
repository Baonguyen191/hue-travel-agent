"""Writes a place answer from retrieved POIs with a local Ollama model.

The model returns JSON {answer, cited_poi_ids, answerable}. Ids outside the context are dropped;
an answer without a valid citation is a refusal. Every fact is checked against the cited POIs; on
a mismatch, an invalid reply after a retry, or a transport error, the template answer for the top
hit is used instead (source "fallback").
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Literal

import httpx
from pydantic import BaseModel, ValidationError

from app.core.usage import add_usage
from app.rag.facts import CITE_RE, FactMismatch, check_facts
from app.rag.index import document_text
from app.rag.retrieve import Hit, RetrievalResult, Retriever
from app.schemas.place import Place
from app.understanding.models import ParsedQuery

MAX_ATTEMPTS = 2
DEFAULT_TIMEOUT = 90.0
REFUSAL_TEXT = "Mình chưa có thông tin để trả lời câu này trong dữ liệu Huế."
ANSWER_SCHEMA = {
    "type": "object",
    "properties": {
        "answer": {"type": "string"},
        "cited_poi_ids": {"type": "array", "items": {"type": "string"}},
        "answerable": {"type": "boolean"},
    },
    "required": ["answer", "cited_poi_ids", "answerable"],
}
SYSTEM_PROMPT = """Bạn là trợ lý du lịch Huế. Chỉ dùng thông tin trong phần NGỮ CẢNH.
Quy tắc:
- Mỗi câu nói về một địa điểm phải kết thúc bằng mã của địa điểm trong ngoặc vuông, ví dụ [huetripo:531787].
- Giờ mở cửa, giá, số điện thoại, địa chỉ phải chép đúng như trong ngữ cảnh. Không đoán, không làm tròn.
- Nếu ngữ cảnh không trả lời được câu hỏi: answerable = false, answer là một câu nói rằng dữ liệu chưa có thông tin, cited_poi_ids rỗng.
- Trả lời ngắn bằng tiếng Việt, tối đa 5 câu, gợi ý tối đa 3 địa điểm.
- cited_poi_ids liệt kê mọi mã đã dùng, theo thứ tự xuất hiện."""


class RagError(RuntimeError):
    """The generator gave no usable answer."""


class _Output(BaseModel):
    answer: str
    cited_poi_ids: list[str]
    answerable: bool


@dataclass
class RagAnswer:
    text: str
    raw_text: str
    cited_poi_ids: list[str]
    answerable: bool
    source: Literal["llm", "fallback", "refusal"]
    retrieval: RetrievalResult
    mismatches: list[FactMismatch] = field(default_factory=list)
    error: str | None = None


def build_context(hits: Sequence[Hit], by_id: Mapping[str, Place]) -> str:
    return "\n".join(f"[{hit.poi_id}] {document_text(by_id[hit.poi_id])}" for hit in hits if hit.poi_id in by_id)


def strip_citations(text: str) -> str:
    cleaned = CITE_RE.sub("", text)
    cleaned = re.sub(r"\s+([.,;!?])", r"\1", cleaned)
    return re.sub(r"[ \t]{2,}", " ", cleaned).strip()


class RagAnswerer:
    """Retrieve, generate, check, fall back. `answer` never raises for model problems."""

    def __init__(
        self,
        retriever: Retriever,
        fallback_text: Callable[[Place], str],
        base_url: str,
        model: str,
        timeout: float = DEFAULT_TIMEOUT,
        transport: httpx.BaseTransport | None = None,
        k: int = 5,
    ) -> None:
        self.retriever = retriever
        self.fallback_text = fallback_text
        self.model = model
        self.k = k
        self._client = httpx.Client(base_url=base_url, timeout=timeout, transport=transport)

    def answer(self, question: str, parsed: ParsedQuery | None = None) -> RagAnswer:
        retrieval = self.retriever.retrieve(question, parsed, self.k)
        if not retrieval.hits:
            return RagAnswer(REFUSAL_TEXT, REFUSAL_TEXT, [], False, "refusal", retrieval)
        by_id = self.retriever.by_id
        context_ids = [hit.poi_id for hit in retrieval.hits]
        try:
            output = self._generate(question, build_context(retrieval.hits, by_id))
        except RagError as error:
            return self._fallback(retrieval, str(error))
        listed = CITE_RE.findall(output.answer) + output.cited_poi_ids
        cited = [poi_id for poi_id in dict.fromkeys(listed) if poi_id in context_ids]
        if not output.answerable or not cited:
            own = strip_citations(output.answer) if not output.answerable else ""
            text = own or REFUSAL_TEXT
            return RagAnswer(text, output.answer, [], False, "refusal", retrieval)
        mismatches = check_facts(output.answer, [by_id[poi_id] for poi_id in cited])
        if mismatches:
            result = self._fallback(retrieval, "fact mismatch")
            result.mismatches = mismatches
            return result
        return RagAnswer(strip_citations(output.answer), output.answer, cited, True, "llm", retrieval)

    def _fallback(self, retrieval: RetrievalResult, error: str) -> RagAnswer:
        place = self.retriever.by_id[retrieval.hits[0].poi_id]
        text = self.fallback_text(place)
        return RagAnswer(text, text, [place.id], True, "fallback", retrieval, error=error)

    def _generate(self, question: str, context: str) -> _Output:
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"NGỮ CẢNH:\n{context}\n\nCÂU HỎI: {question}"},
        ]
        last_error = "no attempt"
        for _ in range(MAX_ATTEMPTS):
            try:
                return _Output.model_validate_json(self._chat(messages))
            except (RagError, ValidationError) as error:
                last_error = str(error)
        raise RagError(f"Generator failed after {MAX_ATTEMPTS} attempts: {last_error}")

    def _chat(self, messages: list[dict[str, str]]) -> str:
        body = {
            "model": self.model,
            "messages": messages,
            "format": ANSWER_SCHEMA,
            "stream": False,
            "think": False,
            "options": {"temperature": 0},
        }
        try:
            response = self._client.post("/api/chat", json=body)
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as error:
            raise RagError(f"Ollama không trả lời: {error}") from error
        if isinstance(payload, dict):
            add_usage("rag_generator", payload)
        content = payload.get("message", {}).get("content") if isinstance(payload, dict) else None
        if not isinstance(content, str):
            raise RagError("Ollama trả về thiếu message.content")
        return content
