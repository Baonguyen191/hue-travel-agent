"""Pure RAG metric functions on hand-computed cases."""

from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path

_BACKEND = _Path(__file__).resolve().parents[1] / "backend"
if str(_BACKEND) not in _sys.path:
    _sys.path.insert(0, str(_BACKEND))

import pytest  # noqa: E402

from app.evaluation.rag_metrics import claim_f1, context_precision, context_recall, faithfulness  # noqa: E402
from app.evaluation.stats import mean, percentile, rate  # noqa: E402


def test_context_precision_rank_weighted() -> None:
    # relevant at ranks 1 and 3: (1/1 + 2/3) / 2
    assert context_precision(["a", "x", "b", "y"], {"a", "b"}) == pytest.approx((1 + 2 / 3) / 2)
    assert context_precision(["x", "y"], {"a"}) == 0.0
    assert context_precision(["a"], set()) is None


def test_context_recall() -> None:
    assert context_recall(["a", "x"], {"a", "b"}) == 0.5
    assert context_recall(["a"], set()) is None


def test_context_recall_is_capped_by_k() -> None:
    assert context_recall(["a", "b", "c", "d", "e"], set("abcdefgh"), k=5) == 1.0
    assert context_recall(["a", "b", "c", "d", "e", "f"], set("abcdefgh"), k=5) == 1.0
    assert context_recall(["a", "x", "y"], set("abcdefgh"), k=5) == pytest.approx(1 / 5)


def test_faithfulness_and_claim_f1() -> None:
    assert faithfulness([True, True, False]) == pytest.approx(2 / 3)
    assert faithfulness([]) is None
    assert claim_f1(2, 1, 1) == pytest.approx(2 / 3)
    assert claim_f1(0, 0, 0) is None


def test_stats() -> None:
    assert mean([1.0, None, 0.0]) == 0.5
    assert mean([None]) is None
    assert percentile([1.0, 2.0, 3.0, 4.0], 0.5) == 2.5
    assert percentile([], 0.5) is None
    assert rate([True, False, True, True]) == 0.75
    assert rate([None]) is None
