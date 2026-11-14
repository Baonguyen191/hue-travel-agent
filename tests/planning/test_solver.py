import datetime as dt
import itertools
import math
import random
import re
from collections.abc import Sequence

import pytest

from tests.planning.factories import START, make_place
from travel_agent.data.place_repository import InMemoryPlaceRepository
from travel_agent.domain.models import Category, Itinerary, Pace, Place, PlanRequest, TravelMode
from travel_agent.planning import solver as solver_module
from travel_agent.planning.candidates import CITY_CENTER, select_candidates
from travel_agent.planning.prompt import SYSTEM_PROMPT
from travel_agent.planning.solver import (
    STOPS_PER_DAY,
    VISIT_MINUTES,
    SolveResult,
    SolveStatus,
    solve,
)
from travel_agent.routing.travel_time import HaversineEstimator
from travel_agent.validation.report import Issue, IssueCode, Severity, ValidationReport
from travel_agent.validation.validator import (
    MAX_STOPS_PER_DAY,
    MEAL_CATEGORIES,
    MEAL_WINDOWS,
    validate_itinerary,
)

KM_PER_DEGREE_LAT = 111.0
TRAVEL = HaversineEstimator()

# Khung ngày giống các giá trị `training/requests.py` sinh ra.
DAY_WINDOWS = (
    (dt.time(7, 30), dt.time(21, 0)),
    (dt.time(8, 0), dt.time(20, 0)),
    (dt.time(9, 0), dt.time(18, 0)),
    (dt.time(8, 0), dt.time(21, 0)),
)
POOL_SIZES: dict[Category, int] = {
    Category.RESTAURANT: 16,
    Category.CAFE: 8,
    Category.HISTORIC: 8,
    Category.MUSEUM: 4,
    Category.RELIGIOUS: 5,
    Category.ATTRACTION: 5,
    Category.PARK: 4,
    Category.MARKET: 4,
    Category.VIEWPOINT: 4,
}
# Trộn giờ đã biết (có khung nghỉ trưa, có ngày đóng cửa) với giờ chưa rõ (None).
SIGHT_HOURS: tuple[str | None, ...] = (
    None,
    "07:30-17:30",
    "Mo-Su 08:00-11:30,13:30-17:00",
    "Tu-Su 07:00-17:00",
    "Mo-Tu,Th-Su 08:00-17:00",
    "24/7",
    "06:30-18:30",
    None,
)
# Nhà hàng nào cũng phục vụ được cả hai bữa: select_candidates chỉ giữ đúng 2 nhà hàng mỗi ngày,
# nên một quán chỉ bán sáng làm request thành bất khả thi (có test riêng cho ca đó).
RESTAURANT_HOURS: tuple[str | None, ...] = (
    None,
    "07:00-22:00",
    "10:00-22:00",
    "10:30-14:00,17:00-21:30",
    "06:30-21:00",
    "Mo-Su 10:00-23:00",
    "08:00-22:00",
)


def offset(km_north: float, km_east: float) -> tuple[float, float]:
    lat = CITY_CENTER.lat + km_north / KM_PER_DEGREE_LAT
    km_per_degree_lon = KM_PER_DEGREE_LAT * math.cos(math.radians(CITY_CENTER.lat))
    return lat, CITY_CENTER.lon + km_east / km_per_degree_lon


def spread_pool() -> list[Place]:
    """Khoảng 1/4 số điểm nằm ngoài bán kính đi bộ (3-9 km), còn lại trong 1,9 km."""
    rng = random.Random(7)
    pool: list[Place] = []
    for category, size in POOL_SIZES.items():
        hours = RESTAURANT_HOURS if category is Category.RESTAURANT else SIGHT_HOURS
        for index in range(size):
            radius = rng.uniform(3.0, 9.0) if index % 4 == 3 else rng.uniform(0.1, 1.9)
            angle = rng.uniform(0, 2 * math.pi)
            lat, lon = offset(radius * math.sin(angle), radius * math.cos(angle))
            pool.append(
                make_place(
                    f"t:{category.value}/{index}",
                    category,
                    hours=hours[index % len(hours)],
                    lat=lat,
                    lon=lon,
                )
            )
    return pool


POOL = spread_pool()


def request_for(
    pace: Pace,
    num_days: int,
    mode: TravelMode,
    window: tuple[dt.time, dt.time] = DAY_WINDOWS[0],
    interests: Sequence[str] = ("history", "food"),
) -> PlanRequest:
    return PlanRequest(
        start_date=START,
        num_days=num_days,
        day_start=window[0],
        day_end=window[1],
        travel_mode=mode,
        pace=pace,
        interests=list(interests),
    )


def check(
    request: PlanRequest, candidates: Sequence[Place], itinerary: Itinerary
) -> ValidationReport:
    return validate_itinerary(request, itinerary, InMemoryPlaceRepository(candidates), TRAVEL)


def solved(result: SolveResult) -> Itinerary:
    assert result.status is SolveStatus.SOLVED, result.detail
    assert result.itinerary is not None
    return result.itinerary


def required_meals(request: PlanRequest) -> list[tuple[dt.time, dt.time]]:
    return [
        (start, end)
        for _, start, end in MEAL_WINDOWS
        if request.day_start <= start and request.day_end >= end
    ]


@pytest.mark.parametrize(
    ("pace", "num_days", "mode"),
    list(itertools.product(Pace, (1, 2, 3), TravelMode)),
)
def test_every_plan_passes_validator_and_pace_rules(
    pace: Pace, num_days: int, mode: TravelMode
) -> None:
    for seed in range(4):
        request = request_for(pace, num_days, mode, DAY_WINDOWS[seed % len(DAY_WINDOWS)])
        candidates = select_candidates(request, POOL, seed)
        itinerary = solved(solve(request, candidates, TRAVEL, seed))
        report = check(request, candidates, itinerary)

        assert report.errors() == []
        warned = {issue.code for issue in report.issues}
        assert IssueCode.OVERLOADED_DAY not in warned
        assert IssueCode.MISSING_MEAL not in warned
        low, high = STOPS_PER_DAY[pace]
        assert [low <= len(day.stops) <= high for day in itinerary.days] == [True] * num_days
        stops = [stop for day in itinerary.days for stop in day.stops]
        assert all(stop.note is None for stop in stops)
        assert len({stop.place_id for stop in stops}) == len(stops)


def test_meals_sit_fully_inside_meal_windows() -> None:
    by_id = {place.id: place for place in POOL}
    for seed in range(6):
        request = request_for(Pace.MODERATE, 2, TravelMode.MOTORBIKE, DAY_WINDOWS[seed % 4])
        itinerary = solved(solve(request, select_candidates(request, POOL, seed), TRAVEL, seed))
        for day in itinerary.days:
            meals = [s for s in day.stops if by_id[s.place_id].category in MEAL_CATEGORIES]
            assert len(meals) == len(required_meals(request))
            for (start, end), stop in zip(required_meals(request), meals, strict=True):
                assert start <= stop.arrive and stop.depart <= end


def test_visit_length_is_the_category_constant() -> None:
    request = request_for(Pace.PACKED, 1, TravelMode.CAR)
    candidates = select_candidates(request, POOL, 3)
    by_id = {place.id: place for place in candidates}
    itinerary = solved(solve(request, candidates, TRAVEL, 3))
    for stop in itinerary.days[0].stops:
        start, end = (dt.datetime.combine(START, t) for t in (stop.arrive, stop.depart))
        assert end - start == dt.timedelta(minutes=VISIT_MINUTES[by_id[stop.place_id].category])


def test_same_seed_gives_same_plan() -> None:
    request = request_for(Pace.MODERATE, 3, TravelMode.MOTORBIKE)
    candidates = select_candidates(request, POOL, 11)
    first = solve(request, candidates, TRAVEL, seed=11)
    second = solve(request, candidates, TRAVEL, seed=11)
    assert solved(first) == solved(second)


def test_different_seeds_give_different_plans() -> None:
    request = request_for(Pace.MODERATE, 2, TravelMode.MOTORBIKE)
    candidates = select_candidates(request, POOL, 0)  # cùng candidate, chỉ đổi seed solver
    plans = {
        solved(solve(request, candidates, TRAVEL, seed)).model_dump_json() for seed in range(8)
    }
    assert len(plans) >= 4


def test_repeated_candidate_is_used_once() -> None:
    request = request_for(Pace.PACKED, 2, TravelMode.MOTORBIKE)
    candidates = select_candidates(request, POOL, 5)
    itinerary = solved(solve(request, [*candidates, *candidates], TRAVEL, 5))
    ids = [stop.place_id for day in itinerary.days for stop in day.stops]
    assert len(ids) == len(set(ids))


def test_too_few_places_is_infeasible() -> None:
    request = request_for(Pace.MODERATE, 1, TravelMode.MOTORBIKE)
    pool = [p for p in POOL if p.category is Category.RESTAURANT][:2] + POOL[-1:]
    result = solve(request, pool, TRAVEL, seed=0)
    assert result.status is SolveStatus.INFEASIBLE
    assert result.itinerary is None


def test_opening_hours_outside_day_window_is_infeasible() -> None:
    request = request_for(Pace.RELAXED, 1, TravelMode.MOTORBIKE, (dt.time(8, 0), dt.time(20, 0)))
    early = [place.model_copy(update={"opening_hours_raw": "05:00-07:30"}) for place in POOL]
    result = solve(request, early, TRAVEL, seed=0)
    assert result.status is SolveStatus.INFEASIBLE
    assert result.itinerary is None


def test_missing_restaurant_for_required_meal_is_infeasible() -> None:
    request = request_for(Pace.RELAXED, 1, TravelMode.MOTORBIKE, (dt.time(8, 0), dt.time(20, 0)))
    breakfast_only = [
        place.model_copy(update={"opening_hours_raw": "06:00-10:00"})
        if place.category is Category.RESTAURANT
        else place
        for place in POOL
    ]
    result = solve(request, breakfast_only, TRAVEL, seed=0)
    assert result.status is SolveStatus.INFEASIBLE


def test_no_meal_needed_when_day_window_misses_meal_windows() -> None:
    request = request_for(Pace.RELAXED, 1, TravelMode.MOTORBIKE, (dt.time(13, 0), dt.time(17, 0)))
    sights = [place for place in POOL if place.category is not Category.RESTAURANT]
    itinerary = solved(solve(request, sights, TRAVEL, seed=0))
    assert check(request, sights, itinerary).errors() == []


def test_timeout_returns_status_without_plan() -> None:
    request = request_for(Pace.PACKED, 3, TravelMode.MOTORBIKE)
    candidates = select_candidates(request, POOL, 0)
    result = solve(request, candidates, TRAVEL, seed=0, time_limit_s=1e-6)
    assert result.status is SolveStatus.TIMED_OUT
    assert result.itinerary is None


def test_plan_with_validator_error_is_returned_as_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    broken = ValidationReport(
        issues=[Issue(code=IssueCode.STOP_OVERLAP, severity=Severity.ERROR, message="giả lập")]
    )

    def always_broken(*args: object) -> ValidationReport:
        return broken

    monkeypatch.setattr(solver_module, "validate_itinerary", always_broken)
    request = request_for(Pace.RELAXED, 1, TravelMode.MOTORBIKE)
    result = solve(request, select_candidates(request, POOL, 0), TRAVEL, seed=0)
    assert result.status is SolveStatus.INVALID
    assert result.itinerary is None
    assert result.report == broken


def test_stop_ranges_match_validator_and_prompt() -> None:
    rule = re.search(r"7\. Số điểm dừng mỗi ngày theo pace: (.+)\.", SYSTEM_PROMPT)
    assert rule is not None
    prompt_ranges = {
        Pace(name): (int(low), int(high))
        for name, low, high in re.findall(r"(\w+) (\d+) đến (\d+)", rule.group(1))
    }
    for pace, (low, high) in STOPS_PER_DAY.items():
        assert high == MAX_STOPS_PER_DAY[pace]
        prompt_low, prompt_high = prompt_ranges[pace]
        assert prompt_low <= low <= high <= prompt_high
