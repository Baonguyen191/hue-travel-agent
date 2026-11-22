"""LLM judge for RAG answers: atomic claims, context support, and claim overlap with a reference.

Same HTTP shape as the answer generator (Ollama /api/chat, JSON schema, temperature 0). Each call
is tried twice; a transport error, invalid JSON or a wrong-shaped verdict list twice is a JudgeError.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from typing import Any, TypeVar

import httpx

from app.core.usage import add_usage

MAX_ATTEMPTS = 2
DEFAULT_TIMEOUT = 180.0

CLAIMS_PROMPT = (
    "Split the ANSWER into short atomic factual claims in Vietnamese, one fact per claim. "
    'Ignore greetings and filler. Return JSON {"claims": [...]}.'
)
SUPPORT_PROMPT = (
    "For each numbered CLAIM decide whether the CONTEXT states it. supported=true only when the context "
    "says it explicitly; a claim about a place not in the context is not supported. "
    'Return JSON {"verdicts": [{"index": int, "supported": bool}]} with one verdict per claim.'
)
COMPARE_PROMPT = (
    "Compare the numbered ANSWER claims with the REFERENCE answer. For each answer claim set "
    "in_reference=true when the reference states the same fact. Then split the REFERENCE into atomic "
    "claims and set in_answer=true when the answer states it. "
    'Return JSON {"answer_claims": [{"index": int, "in_reference": bool}], '
    '"reference_claims": [{"claim": str, "in_answer": bool}]}.'
)
CLAIMS_SCHEMA = {
    "type": "object",
    "properties": {"claims": {"type": "array", "items": {"type": "string"}}},
    "required": ["claims"],
}
SUPPORT_SCHEMA = {
    "type": "object",
    "properties": {
        "verdicts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"index": {"type": "integer"}, "supported": {"type": "boolean"}},
                "required": ["index", "supported"],
            },
        }
    },
    "required": ["verdicts"],
}
COMPARE_SCHEMA = {
    "type": "object",
    "properties": {
        "answer_claims": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"index": {"type": "integer"}, "in_reference": {"type": "boolean"}},
                "required": ["index", "in_reference"],
            },
        },
        "reference_claims": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"claim": {"type": "string"}, "in_answer": {"type": "boolean"}},
                "required": ["claim", "in_answer"],
            },
        },
    },
    "required": ["answer_claims", "reference_claims"],
}

_T = TypeVar("_T")


class JudgeError(RuntimeError):
    """The judge gave no usable verdict after every attempt."""


def _numbered(claims: Sequence[str]) -> str:
    return "\n".join(f"{i}. {claim}" for i, claim in enumerate(claims))


def _flags(items: Any, key: str, count: int) -> list[bool]:
    """Booleans by index; the indices must be exactly 0..count-1, each once."""
    if not isinstance(items, list):
        raise ValueError("expected a list of verdicts")
    by_index: dict[int, bool] = {}
    for item in items:
        index, flag = item["index"], item[key]
        if isinstance(index, bool) or not isinstance(index, int) or not isinstance(flag, bool):
            raise ValueError("verdict has a wrong type")
        by_index[index] = flag
    if len(items) != count or set(by_index) != set(range(count)):
        raise ValueError(f"expected verdicts for indices 0..{count - 1}")
    return [by_index[i] for i in range(count)]


class Judge:
    """Claim-level judge over a local Ollama model."""

    def __init__(
        self,
        base_url: str,
        model: str,
        timeout: float = DEFAULT_TIMEOUT,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.model = model
        self._client = httpx.Client(base_url=base_url, timeout=timeout, transport=transport)

    def claims(self, answer: str) -> list[str]:
        """Atomic claims of an answer, blanks dropped."""

        def parse(data: dict[str, Any]) -> list[str]:
            items = data["claims"]
            if not isinstance(items, list) or not all(isinstance(item, str) for item in items):
                raise ValueError("claims must be a list of strings")
            return [item.strip() for item in items if item.strip()]

        return self._ask(CLAIMS_PROMPT, f"ANSWER:\n{answer}", CLAIMS_SCHEMA, parse)

    def support(self, claims: Sequence[str], context: str) -> list[bool]:
        """Per claim: does the context state it. No request for an empty claim list."""
        if not claims:
            return []
        user = f"CONTEXT:\n{context}\n\nCLAIMS:\n{_numbered(claims)}"
        return self._ask(
            SUPPORT_PROMPT,
            user,
            SUPPORT_SCHEMA,
            lambda data: _flags(data["verdicts"], "supported", len(claims)),
        )

    def compare(self, claims: Sequence[str], reference: str) -> tuple[int, int, int]:
        """(tp, fp, fn): answer claims in the reference, answer claims not in it, reference claims missed."""
        if not claims:
            return 0, 0, 1
        user = f"ANSWER CLAIMS:\n{_numbered(claims)}\n\nREFERENCE:\n{reference}"

        def parse(data: dict[str, Any]) -> tuple[int, int, int]:
            flags = _flags(data["answer_claims"], "in_reference", len(claims))
            reference_claims = data["reference_claims"]
            if not isinstance(reference_claims, list) or not all(
                isinstance(item["in_answer"], bool) for item in reference_claims
            ):
                raise ValueError("reference_claims is malformed")
            tp = sum(flags)
            fn = sum(1 for item in reference_claims if not item["in_answer"])
            return tp, len(flags) - tp, fn

        return self._ask(COMPARE_PROMPT, user, COMPARE_SCHEMA, parse)

    def _ask(
        self,
        system: str,
        user: str,
        schema: dict[str, Any],
        parse: Callable[[dict[str, Any]], _T],
    ) -> _T:
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        last_error = "no attempt"
        for _ in range(MAX_ATTEMPTS):
            try:
                data = json.loads(self._chat(messages, schema))
                if not isinstance(data, dict):
                    raise ValueError("reply is not a JSON object")
                return parse(data)
            except (JudgeError, ValueError, KeyError, TypeError) as error:
                last_error = str(error)
        raise JudgeError(f"Judge failed after {MAX_ATTEMPTS} attempts: {last_error}")

    def _chat(self, messages: list[dict[str, str]], schema: dict[str, Any]) -> str:
        body = {
            "model": self.model,
            "messages": messages,
            "format": schema,
            "stream": False,
            "think": False,
            "options": {"temperature": 0},
        }
        try:
            response = self._client.post("/api/chat", json=body)
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as error:
            raise JudgeError(f"Ollama không trả lời: {error}") from error
        if isinstance(payload, dict):
            add_usage("judge", payload)
        message = payload.get("message") if isinstance(payload, dict) else None
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str):
            raise JudgeError("Ollama trả về thiếu message.content")
        return content
