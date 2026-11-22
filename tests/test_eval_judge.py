"""LLM judge: claim split, support verdicts, answer-vs-reference comparison, retry and errors."""

from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path

_BACKEND = _Path(__file__).resolve().parents[1] / "backend"
if str(_BACKEND) not in _sys.path:
    _sys.path.insert(0, str(_BACKEND))

import json  # noqa: E402
from typing import Any  # noqa: E402

import httpx  # noqa: E402
import pytest  # noqa: E402

from app.core.usage import record_usage  # noqa: E402
from app.evaluation.judge import Judge, JudgeError  # noqa: E402


def _judge(replies: list[Any]) -> tuple[Judge, list[dict[str, Any]]]:
    """A judge whose Ollama returns the given contents in order (a str is sent as raw content)."""
    requests: list[dict[str, Any]] = []
    queue = list(replies)

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
        reply = queue.pop(0)
        content = reply if isinstance(reply, str) else json.dumps(reply)
        return httpx.Response(200, json={"message": {"content": content}, "prompt_eval_count": 10, "eval_count": 5})

    return Judge("http://ollama", "judge-model", transport=httpx.MockTransport(handler)), requests


def test_claims_returns_the_list() -> None:
    judge, requests = _judge([{"claims": [" A ", "", "B"]}])
    assert judge.claims("answer text") == ["A", "B"]
    body = requests[0]
    assert body["model"] == "judge-model"
    assert body["stream"] is False and body["think"] is False
    assert body["options"] == {"temperature": 0}


def test_support_maps_verdicts_in_index_order() -> None:
    reply = {"verdicts": [{"index": 1, "supported": False}, {"index": 0, "supported": True}]}
    judge, _ = _judge([reply])
    assert judge.support(["a", "b"], "ctx") == [True, False]


def test_support_retries_once_then_raises() -> None:
    short = {"verdicts": [{"index": 0, "supported": True}]}
    good = {"verdicts": [{"index": 0, "supported": True}, {"index": 1, "supported": False}]}
    judge, requests = _judge([short, good])
    assert judge.support(["a", "b"], "ctx") == [True, False]
    assert len(requests) == 2
    judge, requests = _judge([short, short])
    with pytest.raises(JudgeError):
        judge.support(["a", "b"], "ctx")
    assert len(requests) == 2
    judge, _ = _judge(["not json", "still not"])
    with pytest.raises(JudgeError):
        judge.claims("x")


def test_empty_claims_make_no_request() -> None:
    judge, requests = _judge([])
    assert judge.support([], "ctx") == []
    assert judge.compare([], "ref") == (0, 0, 1)
    assert requests == []


def test_compare_counts_tp_fp_fn() -> None:
    reply = {
        "answer_claims": [{"index": 0, "in_reference": True}, {"index": 1, "in_reference": False}],
        "reference_claims": [{"claim": "x", "in_answer": False}],
    }
    judge, _ = _judge([reply])
    assert judge.compare(["a", "b"], "ref") == (1, 1, 1)


def test_transport_error_raises_judge_error() -> None:
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    judge = Judge("http://ollama", "m", transport=httpx.MockTransport(boom))
    with pytest.raises(JudgeError):
        judge.claims("x")


def test_usage_is_recorded_as_judge() -> None:
    judge, _ = _judge([{"claims": ["a"]}])
    with record_usage() as usage:
        judge.claims("x")
    assert usage["judge"].to_dict() == {
        "prompt_tokens": 10,
        "completion_tokens": 5,
        "total_tokens": 15,
        "calls": 1,
    }
