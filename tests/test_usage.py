"""Token usage recorder: sums Ollama counts per component, ignores missing counts, crosses threads."""

from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path

_BACKEND = _Path(__file__).resolve().parents[1] / "backend"
if str(_BACKEND) not in _sys.path:
    _sys.path.insert(0, str(_BACKEND))

import asyncio  # noqa: E402
import datetime as dt  # noqa: E402
import json  # noqa: E402

import httpx  # noqa: E402

from app.core.usage import Usage, add_usage, record_usage  # noqa: E402
from app.understanding.extract import OllamaExtractor  # noqa: E402


def test_add_usage_sums_counts_per_component() -> None:
    with record_usage() as usage:
        add_usage("extractor", {"prompt_eval_count": 100, "eval_count": 20})
        add_usage("extractor", {"prompt_eval_count": 50, "eval_count": 5})
        add_usage("rag_generator", {"prompt_eval_count": 7, "eval_count": 3})
    assert usage["extractor"] == Usage(prompt_tokens=150, completion_tokens=25, calls=2)
    assert usage["extractor"].total_tokens == 175
    assert usage["rag_generator"].to_dict() == {
        "prompt_tokens": 7, "completion_tokens": 3, "total_tokens": 10, "calls": 1,
    }


def test_missing_or_invalid_counts_add_zero_but_count_the_call() -> None:
    with record_usage() as usage:
        add_usage("extractor", {})
        add_usage("extractor", {"prompt_eval_count": "x", "eval_count": -4})
    assert usage["extractor"] == Usage(prompt_tokens=0, completion_tokens=0, calls=2)


def test_add_usage_without_recorder_does_nothing() -> None:
    add_usage("extractor", {"prompt_eval_count": 1, "eval_count": 1})


def test_counts_from_a_worker_thread_reach_the_recorder() -> None:
    async def scenario() -> None:
        await asyncio.to_thread(add_usage, "extractor", {"prompt_eval_count": 3, "eval_count": 2})

    with record_usage() as usage:
        asyncio.run(scenario())
    assert usage["extractor"].total_tokens == 5


def test_extractor_records_ollama_counts() -> None:
    content = json.dumps({"intent": "out_of_scope"})

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"message": {"content": content}, "prompt_eval_count": 900, "eval_count": 40}
        )

    extractor = OllamaExtractor("http://ollama.test", "qwen3.5:4b", transport=httpx.MockTransport(handler))
    with record_usage() as usage:
        try:
            extractor.extract("Thời tiết Huế thế nào?", dt.date(2026, 11, 18))
        except Exception:  # the minimal JSON may fail schema validation; the counts still count
            pass
    assert usage["extractor"].prompt_tokens >= 900
    assert usage["extractor"].completion_tokens >= 40
