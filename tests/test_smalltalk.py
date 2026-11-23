"""smalltalk_kind(): greetings, thanks, goodbyes and identity questions on short messages (no network)."""

from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path

_BACKEND = _Path(__file__).resolve().parents[1] / "backend"
if str(_BACKEND) not in _sys.path:
    _sys.path.insert(0, str(_BACKEND))

import pytest  # noqa: E402

from app.understanding.smalltalk import smalltalk_kind  # noqa: E402


@pytest.mark.parametrize(
    ("text", "kind"),
    [
        ("xin chào", "greeting"),
        ("Chào bạn nhé", "greeting"),
        ("cảm ơn bạn", "thanks"),
        ("Tạm biệt", "goodbye"),
        ("bạn là ai?", "identity"),
        ("Chào bạn, bạn làm được gì?", "identity"),
    ],
)
def test_smalltalk_kinds(text: str, kind: str) -> None:
    assert smalltalk_kind(text) == kind


@pytest.mark.parametrize(
    "text",
    [
        "Cháo ở đâu ngon?",
        "chào bạn, cho mình lịch đi Huế 3 ngày",
        "Đại Nội mở cửa mấy giờ?",
        "Ở Huế làm được gì vui?",
        "hướng dẫn đường đến Đại Nội",
        "",
    ],
)
def test_non_smalltalk_is_none(text: str) -> None:
    assert smalltalk_kind(text) is None


def test_more_than_eight_words_is_not_smalltalk() -> None:
    assert smalltalk_kind("cảm ơn bạn rất nhiều vì đã giúp mình chọn lịch trình thật tuyệt vời") is None
