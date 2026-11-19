import json
from collections import Counter
from pathlib import Path

from tests.planning.factories import make_place, make_pool, make_request, spread_pool
from travel_agent.domain.models import Category, Pace, Place, PlanRequest, TravelMode
from travel_agent.planning.candidates import (
    CITY_CENTER,
    MAX_RADIUS_KM,
    candidate_limit,
    preferred_categories,
    select_candidates,
    within_radius,
)

KM_PER_DEGREE_LAT = 111.0


def place_north_of_center(pid: str, km: float) -> Place:
    lat = CITY_CENTER.lat + km / KM_PER_DEGREE_LAT
    return make_place(pid, Category.MUSEUM, lat=lat, lon=CITY_CENTER.lon)


def test_radius_depends_on_travel_mode() -> None:
    near, mid, far = (place_north_of_center(f"t:{km}", km) for km in (1.5, 8, 30))
    assert MAX_RADIUS_KM[TravelMode.WALK] < MAX_RADIUS_KM[TravelMode.MOTORBIKE]
    assert within_radius(near, TravelMode.WALK)
    assert not within_radius(mid, TravelMode.WALK)
    assert within_radius(mid, TravelMode.CAR)
    assert within_radius(mid, TravelMode.MOTORBIKE)
    assert not within_radius(far, TravelMode.CAR)


def test_select_candidates_drops_places_outside_radius() -> None:
    pool = [*make_pool(), place_north_of_center("t:mid", 8), place_north_of_center("t:far", 30)]
    walk = {
        place.id
        for seed in range(30)
        for place in select_candidates(make_request(travel_mode=TravelMode.WALK), pool, seed)
    }
    car = {
        place.id
        for seed in range(30)
        for place in select_candidates(make_request(travel_mode=TravelMode.CAR), pool, seed)
    }
    assert not {"t:mid", "t:far"} & walk
    assert "t:far" not in car
    assert "t:mid" in car


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


def test_every_preferred_category_with_places_is_covered_even_with_small_limit() -> None:
    """Loại ở cuối enum (religious, park) từng bị cắt khi limit nhỏ."""
    request = make_request(interests=["spiritual", "photography"])
    wanted = preferred_categories(request.interests)
    assert Category.RELIGIOUS in wanted
    for seed in range(40):
        chosen = select_candidates(request, make_pool(), seed=seed)
        assert len(chosen) == 12
        assert wanted <= {place.category for place in chosen}, seed


def test_preferred_categories_covered_for_each_single_interest() -> None:
    for interest in ("spiritual", "nature", "photography", "food", "culture"):
        request = make_request(interests=[interest])
        wanted = preferred_categories(request.interests)
        for seed in range(10):
            chosen = select_candidates(request, make_pool(), seed=seed)
            assert wanted <= {place.category for place in chosen}, (interest, seed)


def test_preferred_category_missing_from_pool_is_skipped() -> None:
    pool = [place for place in make_pool() if place.category is not Category.RELIGIOUS]
    chosen = select_candidates(make_request(interests=["spiritual"]), pool, seed=1)
    assert len(chosen) == 12
    assert Category.RELIGIOUS not in {place.category for place in chosen}


def test_no_non_preferred_category_is_always_the_one_cut() -> None:
    """Khi limit không đủ cho mọi loại, loại bị bỏ phải xoay theo seed, không cố định."""
    request = make_request(num_days=2, pace=Pace.RELAXED, interests=["history"])
    assert candidate_limit(request) - 4 < len(Category)  # trừ 4 bữa ăn: ít chỗ hơn số loại
    dropped: set[frozenset[Category]] = set()
    for seed in range(40):
        chosen = select_candidates(request, make_pool(), seed=seed)
        dropped.add(frozenset(set(Category) - {place.category for place in chosen}))
    assert len(dropped) > 1


def test_many_interests_still_cover_every_preferred_category() -> None:
    """Loại khớp sở thích nhiều hơn số chỗ: mỗi loại vẫn phải có ít nhất một điểm."""
    request = make_request(pace=Pace.RELAXED, interests=["culture", "food", "sightseeing"])
    wanted = preferred_categories(request.interests)
    assert len(wanted) * 2 > candidate_limit(request)
    for seed in range(40):
        chosen = select_candidates(request, make_pool(), seed=seed)
        assert wanted <= {place.category for place in chosen}, seed


# --- Hồi quy: không truyền tùy chọn thì kết quả phải y như trước khi có must_include/exclude ---

SNAPSHOT_FILE = Path(__file__).parent / "snapshots" / "candidates_default.json"
SNAPSHOT_CASES: dict[str, dict[str, object]] = {
    "plain_moderate": {"num_days": 2},
    "history_relaxed_walk": {
        "num_days": 1,
        "pace": Pace.RELAXED,
        "interests": ["history"],
        "travel_mode": TravelMode.WALK,
    },
    "spiritual_photo_packed": {
        "num_days": 3,
        "pace": Pace.PACKED,
        "interests": ["spiritual", "photography"],
    },
    "food_coffee_car": {
        "num_days": 2,
        "interests": ["food", "coffee"],
        "travel_mode": TravelMode.CAR,
    },
}
SNAPSHOT_SEEDS = [0, 1, 2, 7, 12345]


def _snapshot_pools() -> dict[str, list[Place]]:
    return {"mixed": [*make_pool(), *spread_pool()], "grid": make_pool()}


def test_default_output_matches_snapshot_from_before_options() -> None:
    """Mốc lấy từ bản trước khi thêm tùy chọn; eval và DVC dựa vào thứ tự và tập điểm này."""
    expected = json.loads(SNAPSHOT_FILE.read_text(encoding="utf-8"))
    actual: dict[str, dict[str, list[str]]] = {}
    for name, kwargs in SNAPSHOT_CASES.items():
        request = make_request(**kwargs)  # type: ignore[arg-type]
        for label, pool in _snapshot_pools().items():
            actual[f"{name}/{label}"] = {
                str(seed): [place.id for place in select_candidates(request, pool, seed)]
                for seed in SNAPSHOT_SEEDS
            }
    assert actual == expected


def test_empty_options_equal_no_options() -> None:
    request = make_request(num_days=3, interests=["food"])
    pool = [*make_pool(), *spread_pool()]
    for seed in SNAPSHOT_SEEDS:
        plain = select_candidates(request, pool, seed)
        explicit = select_candidates(
            request, pool, seed, must_include=(), exclude_ids=(), exclude_categories=()
        )
        assert [p.id for p in plain] == [p.id for p in explicit]


# --- must_include / exclude ---


def _ids(places: list[Place]) -> set[str]:
    return {place.id for place in places}


def test_must_include_outside_radius_is_always_in_candidates() -> None:
    far = place_north_of_center("t:far", 30)
    request = make_request(travel_mode=TravelMode.WALK)
    for seed in range(20):
        chosen = select_candidates(request, [*make_pool(), far], seed, must_include=["t:far"])
        assert "t:far" in _ids(chosen)
        assert len(chosen) == candidate_limit(request)


def test_must_include_replaces_lowest_ranked_non_must_candidates() -> None:
    request = make_request(num_days=3, pace=Pace.PACKED)
    must = ["t:museum/0", "t:cafe/0"]
    for seed in range(10):
        chosen = select_candidates(request, make_pool(), seed, must_include=must)
        assert _ids(chosen) >= set(must)
        assert len(chosen) == candidate_limit(request)
        assert len(_ids(chosen)) == len(chosen)


def test_must_include_unknown_id_is_ignored() -> None:
    request = make_request()
    plain = select_candidates(request, make_pool(), seed=3)
    with_unknown = select_candidates(request, make_pool(), seed=3, must_include=["khong:co"])
    assert [p.id for p in plain] == [p.id for p in with_unknown]


def test_must_include_duplicates_counted_once() -> None:
    far = place_north_of_center("t:far", 30)
    request = make_request(travel_mode=TravelMode.WALK)
    chosen = select_candidates(request, [*make_pool(), far], 1, must_include=["t:far", "t:far"])
    assert [p.id for p in chosen].count("t:far") == 1
    assert len(chosen) == candidate_limit(request)


def test_must_include_larger_than_limit_keeps_all_musts_and_no_others() -> None:
    request = make_request(num_days=1, pace=Pace.RELAXED)  # limit 12
    must = [f"t:attraction/{index}" for index in range(10)] + [
        f"t:museum/{index}" for index in range(3)
    ]  # 13 điểm, đều có trong pool (mỗi loại 10 điểm)
    chosen = select_candidates(request, make_pool(), seed=2, must_include=must)
    assert _ids(chosen) == set(must)


def test_exclude_ids_removed_from_candidates() -> None:
    banned = {"t:museum/0", "t:museum/1", "t:cafe/0"}
    for seed in range(10):
        chosen = select_candidates(make_request(), make_pool(), seed, exclude_ids=banned)
        assert not _ids(chosen) & banned
        assert len(chosen) == candidate_limit(make_request())


def test_exclude_categories_removed_from_candidates() -> None:
    for seed in range(10):
        chosen = select_candidates(
            make_request(), make_pool(), seed, exclude_categories=[Category.CAFE]
        )
        assert all(place.category is not Category.CAFE for place in chosen)


def test_exclusion_wins_over_must_include() -> None:
    """Điểm vừa bắt buộc vừa bị loại (theo id hoặc theo loại) thì không vào candidate."""
    request = make_request(num_days=1)
    by_id = select_candidates(
        request, make_pool(), 4, must_include=["t:museum/0"], exclude_ids=["t:museum/0"]
    )
    by_category = select_candidates(
        request, make_pool(), 4, must_include=["t:cafe/0"], exclude_categories=[Category.CAFE]
    )
    assert "t:museum/0" not in _ids(by_id)
    assert "t:cafe/0" not in _ids(by_category)


def test_must_include_restaurant_is_kept_without_breaking_meal_reservation() -> None:
    request = make_request(num_days=2, pace=Pace.RELAXED)
    chosen = select_candidates(request, make_pool(), 5, must_include=["t:restaurant/3"])
    restaurants = [place for place in chosen if place.category is Category.RESTAURANT]
    assert "t:restaurant/3" in _ids(chosen)
    assert len(restaurants) >= 4


def test_options_do_not_change_request_or_pool() -> None:
    request: PlanRequest = make_request(num_days=2)
    pool = make_pool()
    before = [place.id for place in pool]
    select_candidates(request, pool, 1, must_include=["t:cafe/0"], exclude_ids=["t:park/0"])
    assert [place.id for place in pool] == before
