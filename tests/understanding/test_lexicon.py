"""Từ điển sở thích và nhịp độ (bằng code, không gọi LLM thật): nhà thờ, bún bò, đừng xếp dày...

Mọi câu dưới đây là câu viết mới cho test, không lấy từ bộ eval.
"""

import datetime as dt
import json
from typing import Any

import pytest

from travel_agent.domain.models import Pace
from travel_agent.training.generator import Generation
from travel_agent.understanding.extract import _FEW_SHOT, parse_query
from travel_agent.understanding.normalize import map_interests

WED = dt.date(2026, 11, 18)


class FixedGenerator:
    """Luôn trả cùng một JSON của LLM."""

    def __init__(self, answer: str) -> None:
        self._answer = answer

    def generate(
        self, messages: list[dict[str, str]], format_schema: dict[str, Any] | None = None
    ) -> Generation:
        return Generation(content=self._answer, done_reason="stop")


def _answer(**overrides: Any) -> str:
    data: dict[str, Any] = {
        "intent": "plan_new",
        "date_text": "20/12",
        "duration_text": "2 ngày",
        "travel_mode": None,
        "pace": None,
        "day_start": None,
        "day_end": None,
        "interest_phrases": [],
        "must_include_mentions": [],
        "exclude_mentions": [],
        "exclude_category_phrases": [],
        "soft_preferences": [],
        "city": None,
    }
    data.update(overrides)
    return json.dumps(data, ensure_ascii=False)


def _pace(text: str, llm_pace: str | None = None) -> Pace:
    query = parse_query(text, WED, FixedGenerator(_answer(pace=llm_pace)), [])
    assert query.request is not None
    return query.request.pace


@pytest.mark.parametrize(
    "phrase",
    ["nhà thờ", "giáo đường", "nha tho", "giao duong", "đi nhà thờ"],
)
def test_church_words_map_to_spiritual(phrase: str) -> None:
    assert map_interests([phrase]) == (["spiritual"], [])


@pytest.mark.parametrize(
    "phrase",
    ["bún bò", "bun bo", "cơm hến", "bánh bèo", "bánh khoái", "món Huế", "ăn sáng", "bún"],
)
def test_huế_food_words_map_to_food(phrase: str) -> None:
    assert map_interests([phrase]) == (["food"], [])


@pytest.mark.parametrize(
    "text",
    [
        "đừng xếp dày quá",
        "đừng xếp dày",
        "không dày",
        "không quá dày",
        "thoải mái thôi",
        "không vội",
        "dung xep day qua",
    ],
)
def test_relaxed_phrases_set_relaxed_pace_when_llm_leaves_it_null(text: str) -> None:
    assert _pace(f"đi Huế 2 ngày 20/12, {text}") is Pace.RELAXED


def test_packed_wording_with_negation_is_relaxed_not_packed() -> None:
    assert _pace("đi Huế 2 ngày 20/12, đừng xếp dày nhé") is not Pace.PACKED


def test_negated_comfort_word_is_not_relaxed() -> None:
    assert _pace("đi Huế 2 ngày 20/12, không thoải mái lắm") is Pace.MODERATE


def test_dense_schedule_without_negation_is_not_relaxed() -> None:
    assert _pace("đi Huế 2 ngày 20/12, lịch dày, càng nhiều càng tốt") is Pace.MODERATE


def test_llm_pace_wins_over_the_text_fallback() -> None:
    assert _pace("đi Huế 2 ngày 20/12, đừng xếp dày", llm_pace="packed") is Pace.PACKED


def test_relaxed_fallback_is_recorded_as_not_defaulted() -> None:
    query = parse_query(
        "đi Huế 2 ngày 20/12, không vội",
        WED,
        FixedGenerator(_answer()),
        [],
    )
    assert "pace" not in query.defaulted
    assert query.partial["pace"] == "relaxed"


def test_few_shot_teaches_named_places_as_must_include() -> None:
    # Ví dụ "muốn đi biển X ... ghé Y": tên địa điểm vào must_include_mentions, không vào sở thích.
    [(sentence, example)] = [
        (sentence, answer)
        for sentence, answer in _FEW_SHOT
        if "biển Thuận An" in answer["must_include_mentions"]
    ]
    assert "muốn đi biển Thuận An" in sentence
    assert "Lăng Tự Đức" in example["must_include_mentions"]
    assert example["interest_phrases"] == []
