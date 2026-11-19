"""Test liên kết tên địa điểm với DB: ca thật từ data/hue.sqlite và ca tổng hợp."""

import datetime as dt
from pathlib import Path

import pytest

from travel_agent.domain.models import Category, Coordinates, Place
from travel_agent.training.commands import load_usable_places
from travel_agent.understanding.link import link_places

REPO_ROOT = Path(__file__).parents[2]
HUE_DB = REPO_ROOT / "data" / "hue.sqlite"

requires_db = pytest.mark.skipif(not HUE_DB.exists(), reason="thiếu data/hue.sqlite (DVC)")


def _place(place_id: str, name: str, category: Category) -> Place:
    return Place(
        id=place_id,
        name=name,
        category=category,
        coords=Coordinates(lat=16.47, lon=107.58),
        source="test",
        source_place_id=place_id,
        license="test",
        collected_at=dt.datetime(2026, 11, 1, tzinfo=dt.UTC),
    )


@pytest.fixture(scope="module")
def hue_places() -> list[Place]:
    if not HUE_DB.exists():
        pytest.skip("thiếu data/hue.sqlite (DVC)")
    return load_usable_places(HUE_DB)


def _linked_id(mention: str, places: list[Place]) -> str | None:
    (result,) = link_places([mention], places)
    return result.place_id


@requires_db
@pytest.mark.parametrize(
    ("mention", "place_id"),
    [
        ("chùa Thiên Mụ", "huetripo:197559"),
        ("Chùa Thiên Mụ", "huetripo:197559"),
        ("chua thien mu", "huetripo:197559"),
        ("Kinh Thành", "huetripo:860594"),
        ("kinh thanh", "huetripo:860594"),
        ("Đại Nội", "huetripo:531787"),
        ("chợ Đông Ba", "huetripo:193028"),
        ("Đông Ba", "huetripo:193028"),
        ("Chợ Đông Ba Huế", "huetripo:759007"),
        ("Cafe Đông Ba", "huetripo:011377"),
        ("lăng Tự Đức", "huetripo:483480"),
        ("Lăng Khải Định", "huetripo:627150"),
        ("lăng Minh Mạng", "huetripo:424131"),
    ],
)
def test_famous_places_link_to_db_ids(mention: str, place_id: str, hue_places: list[Place]) -> None:
    assert _linked_id(mention, hue_places) == place_id


@requires_db
def test_pagoda_is_not_the_tofu_stall_next_to_it(hue_places: list[Place]) -> None:
    (result,) = link_places(["chùa Thiên Mụ"], hue_places)
    assert result.place_id == "huetripo:197559"
    assert result.score == pytest.approx(1.0)


@requires_db
def test_mention_with_food_word_may_link_to_food_place(hue_places: list[Place]) -> None:
    (result,) = link_places(["đậu hũ chùa Thiên Mụ"], hue_places)
    assert result.place_id in {"huetripo:371056", "huetripo:591521"}


@requires_db
def test_unknown_place_is_not_linked(hue_places: list[Place]) -> None:
    (result,) = link_places(["Sân golf Tân Sơn Nhất"], hue_places)
    assert result.place_id is None
    assert result.text == "Sân golf Tân Sơn Nhất"


def test_penalty_prefers_pagoda_over_tofu_regardless_of_id_order() -> None:
    # Tofu có id nhỏ hơn, nên nếu không có phạt loại thì nó sẽ thắng vì hòa điểm.
    places = [
        _place("a0", "Đậu hũ chùa Thiên Mụ", Category.RESTAURANT),
        _place("b1", "Chùa Thiên Mụ", Category.RELIGIOUS),
    ]
    (result,) = link_places(["chùa Thiên Mụ"], places)
    assert result.place_id == "b1"


def test_food_word_in_mention_removes_penalty() -> None:
    places = [
        _place("a0", "Đậu hũ chùa Thiên Mụ", Category.RESTAURANT),
        _place("b1", "Chùa Thiên Mụ", Category.RELIGIOUS),
    ]
    (result,) = link_places(["đậu hũ chùa Thiên Mụ"], places)
    assert result.place_id == "a0"


def test_market_beats_same_name_restaurant_for_chợ_mention() -> None:
    places = [
        _place("a0", "Chợ Đông Ba", Category.RESTAURANT),
        _place("b1", "Chợ Đông Ba", Category.MARKET),
    ]
    (result,) = link_places(["chợ Đông Ba"], places)
    assert result.place_id == "b1"


def test_exact_name_ignores_parenthetical_and_diacritics() -> None:
    places = [_place("p1", "Chùa Thiên Mụ (Chùa Linh Mụ)", Category.RELIGIOUS)]
    (result,) = link_places(["Chua Thien Mu"], places)
    assert result.place_id == "p1"
    assert result.score == pytest.approx(1.0)


def test_contained_mention_scores_below_exact_and_still_links() -> None:
    places = [_place("p1", "Kinh Thành Huế", Category.HISTORIC)]
    (result,) = link_places(["Kinh Thành"], places)
    assert result.place_id == "p1"
    assert 0.8 <= result.score < 1.0


def test_single_word_mention_is_not_a_containment_match() -> None:
    # "Huế" nằm trong "Đại Nội Huế" nhưng một chữ không đủ để coi là khớp theo cụm.
    places = [_place("p1", "Đại Nội Huế", Category.HISTORIC)]
    (result,) = link_places(["Huế"], places)
    assert result.place_id is None


def test_below_threshold_keeps_text_and_reports_score() -> None:
    places = [_place("p1", "Lăng Tự Đức", Category.HISTORIC)]
    (result,) = link_places(["Lăng Abc Xyz"], places)
    assert result.place_id is None
    assert result.text == "Lăng Abc Xyz"
    assert 0.0 < result.score < 0.7


def test_no_shared_token_gives_zero_score() -> None:
    places = [_place("p1", "Lăng Tự Đức", Category.HISTORIC)]
    (result,) = link_places(["Sân bay Phú Bài"], places)
    assert result.place_id is None
    assert result.score == 0.0


def test_one_result_per_mention_in_order_and_blank_mentions_skipped() -> None:
    places = [
        _place("p1", "Chùa Thiên Mụ", Category.RELIGIOUS),
        _place("p2", "Đại Nội Huế", Category.HISTORIC),
    ]
    results = link_places(["Đại Nội", "  ", "!!", "chùa Thiên Mụ"], places)
    assert [item.text for item in results] == ["Đại Nội", "chùa Thiên Mụ"]
    assert [item.place_id for item in results] == ["p2", "p1"]


def test_empty_inputs_give_empty_or_unlinked_results() -> None:
    assert link_places([], []) == []
    (result,) = link_places(["Đại Nội"], [])
    assert result.place_id is None
    assert result.score == 0.0
