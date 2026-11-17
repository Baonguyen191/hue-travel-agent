import datetime as dt

import pytest

from tests.planning.factories import make_place
from tests.validation.factories import (
    DAY1,
    FixedTravelTime,
    StopSpec,
    make_day,
    make_itinerary,
    make_request,
)
from travel_agent.domain.models import Category, Pace, Place, PlanRequest
from travel_agent.training.reward import STOP_FLOOR, RewardBreakdown, reward, score_reward

# Có giờ mở cửa đủ bao trùm mọi stop trong các plan dưới đây: không có warning nào.
PLACES: list[Place] = [
    make_place("t:museum", Category.MUSEUM, hours="Mo-Su 07:00-17:00"),
    make_place("t:museum2", Category.MUSEUM, hours="Mo-Su 07:00-17:00"),
    make_place("t:cafe", Category.CAFE, hours="Mo-Su 08:00-18:00"),
    make_place("t:cafe2", Category.CAFE, hours="Mo-Su 08:00-18:00"),
    make_place("t:park", Category.PARK, hours="24/7"),
    make_place("t:lunch", Category.RESTAURANT, hours="Mo-Su 10:00-22:00"),
    make_place("t:dinner", Category.RESTAURANT, hours="Mo-Su 16:00-22:00"),
    make_place("t:lunch2", Category.RESTAURANT, hours="Mo-Su 10:00-22:00"),
]
# Cùng id nhưng không có giờ mở cửa: validator báo opening_hours_unknown.
BARE_PLACES: list[Place] = [make_place(place.id, place.category) for place in PLACES]

VALID_STOPS: list[StopSpec] = [
    ("t:museum", "08:30", "10:30"),
    ("t:cafe", "10:45", "11:15"),
    ("t:lunch", "11:30", "12:30"),
    ("t:dinner", "18:00", "19:00"),
]


def _raw(*days: list[StopSpec]) -> str:
    planned = [make_day(stops, DAY1 + dt.timedelta(days=index)) for index, stops in enumerate(days)]
    return make_itinerary(*planned).model_dump_json()


def _score(
    raw: str,
    request: PlanRequest | None = None,
    candidates: list[Place] | None = None,
    minutes: float = 10.0,
) -> RewardBreakdown:
    return score_reward(
        request or make_request(),
        raw,
        PLACES if candidates is None else candidates,
        FixedTravelTime(minutes=minutes),
    )


@pytest.mark.parametrize(
    "raw",
    [
        "không phải json",
        '{"days": [',
    ],
)
def test_broken_json_gives_minus_one(raw: str) -> None:
    result = _score(raw)
    assert result.total == -1.0
    assert (result.parsed, result.valid) == (False, False)
    assert result.penalties == {}


@pytest.mark.parametrize(
    "raw",
    [
        '{"foo": 1}',
        '{"days": []}',
        '{"days": [{"date": "2026-11-04", "stops": []}]}',
    ],
)
def test_wrong_schema_gives_minus_one(raw: str) -> None:
    result = _score(raw)
    assert result.total == -1.0
    assert (result.parsed, result.valid) == (False, False)
    assert result.penalties == {}


def test_valid_plan_with_enough_stops_and_no_warnings_gives_plus_one() -> None:
    result = _score(_raw(VALID_STOPS))
    assert result.total == 1.0
    assert (result.parsed, result.valid) == (True, True)
    assert result.penalties == {}


def test_each_unknown_place_costs_half_and_is_not_double_counted() -> None:
    stops: list[StopSpec] = [
        ("t:museum", "08:30", "10:30"),
        ("x:404", "10:45", "11:15"),
        ("t:lunch", "11:30", "12:30"),
        ("t:dinner", "18:00", "19:00"),
    ]
    result = _score(_raw(stops))
    assert result.penalties == {"unknown_place": -0.5}
    assert result.total == 0.5
    assert (result.parsed, result.valid) == (True, False)


def test_unknown_places_clamp_total_at_minus_one() -> None:
    stops: list[StopSpec] = [
        ("x:1", "08:30", "09:00"),
        ("x:2", "09:15", "09:45"),
        ("x:3", "10:00", "10:30"),
        ("x:4", "10:45", "11:15"),
    ]
    result = _score(_raw(stops))
    assert result.penalties["unknown_place"] == -2.0
    assert result.total == -1.0


def test_duplicate_place_costs_point_two() -> None:
    stops = [*VALID_STOPS, ("t:lunch", "19:30", "20:00")]  # lặp lunch, còn trong giờ mở cửa
    result = _score(_raw(stops))
    assert result.penalties == {"duplicate_place": -0.2}
    assert result.total == 0.8
    assert not result.valid


def test_travel_time_insufficient_costs_point_two() -> None:
    stops: list[StopSpec] = [
        ("t:museum", "08:30", "10:00"),
        ("t:cafe", "10:30", "11:00"),  # cách 30 phút, cần 45
        ("t:lunch", "13:00", "14:00"),
        ("t:dinner", "18:00", "19:00"),
    ]
    result = _score(_raw(stops), minutes=45.0)
    assert result.penalties == {"travel_time_insufficient": -0.2}
    assert result.total == 0.8


def test_day_count_mismatch_costs_point_two() -> None:
    request = make_request(num_days=2)
    result = _score(_raw(VALID_STOPS), request=request)
    assert result.penalties == {"day_count_mismatch": -0.2}
    assert result.total == 0.8


def test_one_stop_per_day_is_penalised_per_day() -> None:
    day_one: list[StopSpec] = [("t:lunch", "11:30", "19:00")]
    day_two: list[StopSpec] = [("t:lunch2", "11:30", "19:00")]
    result = _score(_raw(day_one, day_two), request=make_request(num_days=2))
    assert result.penalties == {"below_stop_floor": -0.6}
    assert result.total == 0.4
    assert (result.parsed, result.valid) == (True, True)


def test_stop_floor_depends_on_pace() -> None:
    three_stops: list[StopSpec] = [
        ("t:museum", "08:30", "10:30"),
        ("t:lunch", "11:30", "12:30"),
        ("t:dinner", "18:00", "19:00"),
    ]
    relaxed = _score(_raw(three_stops), request=make_request(pace=Pace.RELAXED))
    moderate = _score(_raw(three_stops), request=make_request(pace=Pace.MODERATE))
    assert relaxed.penalties == {}
    assert relaxed.total == 1.0
    assert moderate.penalties == {"below_stop_floor": -0.3}
    assert moderate.total == 0.7


def test_stop_floor_table_matches_spec() -> None:
    assert dict(STOP_FLOOR) == {Pace.RELAXED: 3, Pace.MODERATE: 4, Pace.PACKED: 6}


def test_overloaded_day_costs_point_zero_five() -> None:
    stops: list[StopSpec] = [
        ("t:museum", "08:00", "08:30"),
        ("t:cafe", "08:45", "09:15"),
        ("t:park", "09:30", "10:00"),
        ("t:lunch", "11:30", "12:30"),
        ("t:museum2", "12:45", "13:15"),
        ("t:cafe2", "13:30", "14:00"),
        ("t:dinner", "18:00", "19:00"),
    ]
    result = _score(_raw(stops))
    assert result.penalties == {"overloaded_day": -0.05}
    assert result.total == 0.95
    assert result.valid


def test_missing_meal_costs_point_zero_five() -> None:
    stops: list[StopSpec] = [
        ("t:museum", "08:30", "10:00"),
        ("t:cafe", "10:15", "10:45"),
        ("t:park", "14:00", "15:00"),
        ("t:dinner", "18:00", "19:00"),
    ]
    result = _score(_raw(stops))
    assert result.penalties == {"missing_meal": -0.05}
    assert result.total == 0.95
    assert result.valid


def test_opening_hours_unknown_costs_nothing() -> None:
    result = _score(_raw(VALID_STOPS), candidates=BARE_PLACES)
    assert result.penalties == {}
    assert result.total == 1.0
    assert result.valid


def test_reward_equals_score_reward_total() -> None:
    request = make_request()
    for raw in (_raw(VALID_STOPS), _raw([("x:9", "08:30", "09:00")]), "không phải json"):
        assert (
            reward(request, raw, PLACES, FixedTravelTime())
            == score_reward(request, raw, PLACES, FixedTravelTime()).total
        )
