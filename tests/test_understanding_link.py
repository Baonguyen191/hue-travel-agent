"""Tests for linking place mentions to POI ids (synthetic cases and the real Hue DB)."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest

import sys as _sys
from pathlib import Path as _Path
_BACKEND = _Path(__file__).resolve().parents[1] / "backend"
if str(_BACKEND) not in _sys.path:
    _sys.path.insert(0, str(_BACKEND))

from app.core.config import hue_database_path
from app.repositories.hue_places import HuePlacesRepository
from app.schemas.place import Place, PlaceCategory
from app.understanding.link import link_places

HUE_DB = hue_database_path()
requires_db = pytest.mark.skipif(
    not Path(HUE_DB).is_file(), reason="missing backend/data/hue.sqlite"
)


def _place(place_id: str, name: str, category: PlaceCategory) -> Place:
    return Place(
        id=place_id,
        name=name,
        category=category,
        lat=16.47,
        lon=107.58,
        opening_hours_confidence="UNKNOWN",
        price_status="UNKNOWN",
        source="test",
        source_place_id=place_id,
        collected_at=dt.datetime(2026, 11, 1, tzinfo=dt.UTC),
        raw_attributes={},
    )


@pytest.fixture(scope="module")
def hue_places() -> list[Place]:
    if not Path(HUE_DB).is_file():
        pytest.skip("missing backend/data/hue.sqlite")
    return HuePlacesRepository(Path(HUE_DB)).list_all()


def _linked_id(mention: str, places: list[Place]) -> str | None:
    (result,) = link_places([mention], places)
    return result.poi_id


@requires_db
@pytest.mark.parametrize(
    ("mention", "poi_id"),
    [
        ("chùa Thiên Mụ", "huetripo:197559"),
        ("chua thien mu", "huetripo:197559"),
        ("Kinh Thành", "huetripo:860594"),
        ("Đại Nội", "huetripo:531787"),
        ("chợ Đông Ba", "huetripo:193028"),
        ("Đông Ba", "huetripo:193028"),
        ("lăng Tự Đức", "huetripo:483480"),
        ("Lăng Khải Định", "huetripo:627150"),
        ("lăng Minh Mạng", "huetripo:424131"),
    ],
)
def test_famous_places_link_to_db_ids(
    mention: str, poi_id: str, hue_places: list[Place]
) -> None:
    assert _linked_id(mention, hue_places) == poi_id


@requires_db
def test_unknown_place_is_not_linked(hue_places: list[Place]) -> None:
    assert _linked_id("Bảo tàng Mỹ thuật Paris", hue_places) is None


def test_pagoda_is_not_the_tofu_stall_next_to_it() -> None:
    places = [
        _place("a0", "Đậu hũ chùa Thiên Mụ", "restaurant"),
        _place("b1", "Chùa Thiên Mụ", "religious"),
    ]
    assert _linked_id("chùa Thiên Mụ", places) == "b1"


def test_food_word_in_mention_removes_penalty() -> None:
    places = [
        _place("a0", "Đậu hũ chùa Thiên Mụ", "restaurant"),
        _place("b1", "Chùa Thiên Mụ", "religious"),
    ]
    assert _linked_id("quán đậu hũ chùa Thiên Mụ", places) == "a0"


def test_market_beats_same_name_restaurant_for_cho_mention() -> None:
    places = [
        _place("a0", "Chợ Đông Ba", "restaurant"),
        _place("b1", "Chợ Đông Ba", "market"),
    ]
    assert _linked_id("chợ Đông Ba", places) == "b1"


def test_exact_name_ignores_parenthetical_and_diacritics() -> None:
    places = [_place("p1", "Chùa Thiên Mụ (Chùa Linh Mụ)", "religious")]
    assert _linked_id("Chua Thien Mu", places) == "p1"


def test_contained_mention_links_with_lower_score() -> None:
    places = [_place("p1", "Kinh Thành Huế", "historic")]
    (result,) = link_places(["Kinh Thành"], places)
    assert result.poi_id == "p1"
    assert result.score == pytest.approx(0.85)
    assert result.name == "Kinh Thành Huế"


def test_single_word_mention_is_not_a_containment_match() -> None:
    places = [_place("p1", "Đại Nội Huế", "historic")]
    assert _linked_id("Đại", places) is None


def test_below_threshold_keeps_text_and_score_without_id() -> None:
    places = [_place("p1", "Chùa Thiên Mụ", "religious")]
    (result,) = link_places(["Chùa Hương"], places)
    assert result.poi_id is None
    assert result.text == "Chùa Hương"
    assert 0.0 < result.score < 0.7


def test_no_shared_token_gives_zero_score() -> None:
    places = [_place("p1", "Lăng Tự Đức", "historic")]
    (result,) = link_places(["Bãi biển"], places)
    assert result.poi_id is None
    assert result.score == 0.0


def test_one_result_per_mention_in_order_and_blank_mentions_skipped() -> None:
    places = [
        _place("p1", "Chùa Thiên Mụ", "religious"),
        _place("p2", "Đại Nội Huế", "historic"),
    ]
    results = link_places(["Đại Nội", "  ", "chùa Thiên Mụ"], places)
    assert [item.poi_id for item in results] == ["p2", "p1"]


def test_gapped_in_order_words_link_to_the_longer_name() -> None:
    places = [
        _place("p1", "Lăng vua Tự Đức", "historic"),
        _place("p2", "Lăng Dục Đức", "historic"),
    ]
    assert _linked_id("lăng Tự Đức", places) == "p1"


def test_ambiguous_mention_adds_note_with_candidates() -> None:
    places = [
        _place("p1", "Chợ Đông Ba", "market"),
        _place("p2", "Chợ Đông Ba Huế", "market"),
    ]
    notes: list[str] = []
    link_places(["chợ Đông Ba"], places, notes=notes)
    assert notes
    assert "p1" in notes[0]
    assert "p2" in notes[0]


def test_empty_inputs_give_empty_results() -> None:
    assert link_places([], []) == []
    (result,) = link_places(["Đại Nội"], [])
    assert result.poi_id is None
