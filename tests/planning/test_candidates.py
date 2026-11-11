from collections import Counter

from tests.planning.factories import make_place, make_pool, make_request
from travel_agent.domain.models import Category, Pace
from travel_agent.planning.candidates import candidate_limit, select_candidates


def test_limit_scales_with_pace_and_days() -> None:
    assert candidate_limit(make_request(num_days=1, pace=Pace.RELAXED)) == 12
    assert candidate_limit(make_request(num_days=3, pace=Pace.MODERATE)) == 22
    assert candidate_limit(make_request(num_days=3, pace=Pace.PACKED)) == 28
    assert candidate_limit(make_request(num_days=7, pace=Pace.PACKED)) == 30


def test_returns_limit_unique_places() -> None:
    request = make_request(num_days=3, pace=Pace.PACKED)
    chosen = select_candidates(request, make_pool(), seed=1)
    assert len(chosen) == 28
    assert len({place.id for place in chosen}) == 28


def test_same_seed_same_result_regardless_of_input_order() -> None:
    request = make_request()
    pool = make_pool()
    first = select_candidates(request, pool, seed=7)
    second = select_candidates(request, list(reversed(pool)), seed=7)
    assert [place.id for place in first] == [place.id for place in second]


def test_different_seed_changes_selection() -> None:
    request = make_request()
    pool = make_pool()
    first = {place.id for place in select_candidates(request, pool, seed=1)}
    second = {place.id for place in select_candidates(request, pool, seed=2)}
    assert first != second


def test_reserves_two_restaurants_per_day() -> None:
    request = make_request(num_days=3, pace=Pace.RELAXED)
    chosen = select_candidates(request, make_pool(), seed=3)
    restaurants = [place for place in chosen if place.category is Category.RESTAURANT]
    assert len(restaurants) >= 6


def test_no_interests_covers_every_category() -> None:
    chosen = select_candidates(make_request(), make_pool(), seed=4)
    assert {place.category for place in chosen} == set(Category)


def test_interest_gets_more_slots() -> None:
    chosen = select_candidates(make_request(interests=["coffee"]), make_pool(), seed=5)
    counts = Counter(place.category for place in chosen)
    assert counts[Category.CAFE] > counts[Category.MUSEUM]


def test_unknown_interest_is_ignored() -> None:
    chosen = select_candidates(make_request(interests=["khong-co"]), make_pool(), seed=6)
    assert len(chosen) == 12


def test_small_pool_returns_everything() -> None:
    pool = [
        make_place("t:a", Category.MUSEUM),
        make_place("t:b", Category.RESTAURANT),
        make_place("t:c", Category.CAFE),
    ]
    chosen = select_candidates(make_request(), pool, seed=8)
    assert {place.id for place in chosen} == {"t:a", "t:b", "t:c"}
