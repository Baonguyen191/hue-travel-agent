"""Landmark trong candidate (opt-in). Không mạng; một test đọc DB thật."""

import math
from pathlib import Path

import pytest

from tests.planning.factories import make_place, make_request
from travel_agent.data.place_repository import SqlitePlaceRepository
from travel_agent.domain.models import Category, Pace, Place, PlanRequest, TravelMode
from travel_agent.planning.candidates import (
    CITY_CENTER,
    candidate_limit,
    landmark_places,
    popularity_score,
    select_candidates,
)

REAL_DB = Path(__file__).resolve().parents[2] / "data" / "hue.sqlite"
DAY_SEED = 11


def _far_place(pid: str, category: Category, rating: str, km: float = 30.0) -> Place:
    """Điểm cách trung tâm `km` km về phía bắc, nên ngoài bán kính đi xe máy và đi ô tô."""
    lat = CITY_CENTER.lat + km / 111.0
    place = make_place(pid, category, lat=lat, lon=CITY_CENTER.lon)
    return place.model_copy(update={"attributes": {"Đánh giá": rating}})


def _near_place(pid: str, category: Category, rating: str) -> Place:
    place = make_place(pid, category)
    return place.model_copy(update={"attributes": {"Đánh giá": rating}})


def _pool() -> list[Place]:
    # Mười điểm lịch sử gần, đều có độ phổ biến thấp; cộng các điểm xa và các loại khác.
    near = [_near_place(f"t:near/{i}", Category.HISTORIC, "3/5 (2 lượt)") for i in range(10)]
    far = [
        _far_place("t:tomb/top", Category.HISTORIC, "4.9/5 (900 lượt, Google)"),
        _far_place("t:tomb/mid", Category.HISTORIC, "4.5/5 (40 lượt, Google)"),
    ]
    other = [
        _near_place("t:resto/top", Category.RESTAURANT, "5/5 (5000 lượt)"),
        _near_place("t:cafe/top", Category.CAFE, "5/5 (5000 lượt)"),
        _near_place("t:park/top", Category.PARK, "5/5 (5000 lượt)"),
        _near_place("t:museum/top", Category.MUSEUM, "4.8/5 (300 lượt)"),
    ]
    return [*near, *far, *other]


def _ids(places: list[Place]) -> list[str]:
    return [place.id for place in places]


def test_popularity_is_log_of_reviews_with_rating_as_tiebreak() -> None:
    place = _near_place("t:a", Category.HISTORIC, "4.4/5 (29 lượt, Google)")
    assert popularity_score(place) == pytest.approx(math.log10(30) + 0.44)


def test_popularity_reads_thousands_separators_in_review_counts() -> None:
    dotted = _near_place("t:a", Category.HISTORIC, "4/5 (1.377 lượt, Google)")
    comma = _near_place("t:b", Category.HISTORIC, "4,0/5 (1,377 lượt)")
    assert popularity_score(dotted) == pytest.approx(math.log10(1378) + 0.4)
    assert popularity_score(comma) == pytest.approx(math.log10(1378) + 0.4)


def test_popularity_falls_back_to_rating_without_review_count() -> None:
    place = _near_place("t:a", Category.HISTORIC, "4.8/5")
    assert popularity_score(place) == pytest.approx(0.48)
    # Có số lượt (dù 1 lượt) thì xếp trên điểm chỉ có sao.
    assert popularity_score(_near_place("t:b", Category.HISTORIC, "4.8/5 (1 lượt)")) > 0.48


def test_popularity_is_zero_for_zero_reviews_missing_or_garbled_text() -> None:
    zero = _near_place("t:a", Category.HISTORIC, "0/5 (0 lượt, Không xác định)")
    assert popularity_score(zero) == 0.0
    assert popularity_score(make_place("t:b", Category.HISTORIC)) == 0.0
    assert popularity_score(_near_place("t:c", Category.HISTORIC, "không rõ")) == 0.0


def test_default_selection_is_unchanged_when_landmarks_is_zero() -> None:
    request = make_request(num_days=2, pace=Pace.MODERATE, interests=["history"])
    pool = _pool()
    for seed in range(5):
        assert _ids(select_candidates(request, pool, seed, landmarks=0)) == _ids(
            select_candidates(request, pool, seed)
        )


def test_walking_adds_no_landmarks() -> None:
    request = make_request(interests=["history"], travel_mode=TravelMode.WALK)
    pool = _pool()
    for seed in range(5):
        assert _ids(select_candidates(request, pool, seed, landmarks=6)) == _ids(
            select_candidates(request, pool, seed, landmarks=0)
        )


def test_landmarks_bring_far_preferred_places_and_skip_restaurants_and_cafes() -> None:
    request = make_request(interests=["history"], travel_mode=TravelMode.MOTORBIKE)
    chosen = _ids(select_candidates(request, _pool(), DAY_SEED, landmarks=3))
    assert "t:tomb/top" in chosen  # 30 km: ngoài bán kính, nhưng là landmark
    assert "t:tomb/mid" in chosen
    # Nhà hàng và quán cà phê có độ phổ biến cao nhất nhưng không bao giờ là landmark.
    landmark_only = _ids(
        landmark_places(
            request, _pool(), 10, excluded_ids=(), excluded_categories=(), reserved_ids=()
        )
    )
    assert not {"t:resto/top", "t:cafe/top"} & set(landmark_only)


def test_landmarks_are_taken_in_popularity_order_up_to_the_count() -> None:
    request = make_request(interests=["history"], travel_mode=TravelMode.MOTORBIKE)
    top_one = _ids(
        landmark_places(
            request, _pool(), 1, excluded_ids=(), excluded_categories=(), reserved_ids=()
        )
    )
    assert top_one == ["t:tomb/top"]


def test_landmarks_without_interests_use_history_religious_and_attraction() -> None:
    request = make_request(interests=[], travel_mode=TravelMode.CAR)
    chosen = _ids(
        landmark_places(
            request,
            _pool(),
            6,
            excluded_ids=(),
            excluded_categories=(),
            reserved_ids=(),
        )
    )
    assert "t:museum/top" in chosen  # MUSEUM thuộc nhóm lịch sử
    assert "t:resto/top" not in chosen and "t:cafe/top" not in chosen
    assert "t:park/top" not in chosen  # PARK không thuộc nhóm mặc định


def test_landmarks_respect_exclusions_and_are_not_duplicated() -> None:
    request = make_request(interests=["history"], travel_mode=TravelMode.MOTORBIKE)
    chosen = _ids(
        select_candidates(
            request,
            _pool(),
            DAY_SEED,
            must_include=["t:tomb/top"],
            exclude_ids=["t:tomb/mid"],
            landmarks=6,
        )
    )
    assert "t:tomb/mid" not in chosen
    assert chosen.count("t:tomb/top") == 1
    excluded_category = _ids(
        select_candidates(
            request, _pool(), DAY_SEED, exclude_categories=[Category.HISTORIC], landmarks=6
        )
    )
    assert not {"t:tomb/top", "t:tomb/mid"} & set(excluded_category)


def test_landmarks_keep_the_candidate_count_and_do_not_drop_meals() -> None:
    request = make_request(num_days=1, pace=Pace.RELAXED, interests=["history"])
    pool = [*_pool(), *(_near_place(f"t:resto/{i}", Category.RESTAURANT, "4/5") for i in range(6))]
    for seed in range(5):
        chosen = select_candidates(request, pool, seed, landmarks=6)
        assert len(chosen) == candidate_limit(request)
        restaurants = [place for place in chosen if place.category is Category.RESTAURANT]
        assert len(restaurants) >= 2


def test_landmarks_replace_the_last_ordinary_candidates() -> None:
    request = make_request(num_days=1, pace=Pace.RELAXED, interests=["history"])
    pool = _pool()
    plain = _ids(select_candidates(request, pool, DAY_SEED))
    with_landmarks = _ids(select_candidates(request, pool, DAY_SEED, landmarks=3))
    assert len(with_landmarks) == len(plain)
    assert "t:tomb/top" in with_landmarks
    assert "t:tomb/mid" in with_landmarks


def test_negative_landmarks_is_rejected() -> None:
    with pytest.raises(ValueError):
        select_candidates(make_request(), _pool(), DAY_SEED, landmarks=-1)


@pytest.mark.skipif(not REAL_DB.exists(), reason="chưa có data/hue.sqlite")
def test_history_by_motorbike_brings_a_royal_tomb_from_the_real_db() -> None:
    repo = SqlitePlaceRepository(REAL_DB)
    try:
        places = repo.list_places(limit=100_000)
    finally:
        repo.close()
    request = PlanRequest(
        start_date=make_request().start_date,
        num_days=2,
        pace=Pace.MODERATE,
        travel_mode=TravelMode.MOTORBIKE,
        interests=["history"],
    )
    chosen = select_candidates(request, places, DAY_SEED, landmarks=6)
    names = [place.name for place in chosen]
    assert any(name.startswith("Lăng vua") for name in names), names
