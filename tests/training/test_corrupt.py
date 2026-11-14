import datetime as dt
from collections.abc import Sequence

import pytest

from tests.planning.factories import DAY_WINDOWS, request_for, spread_pool
from travel_agent.data.place_repository import InMemoryPlaceRepository
from travel_agent.domain.models import Itinerary, Pace, Place, PlanRequest, TravelMode
from travel_agent.planning.candidates import select_candidates
from travel_agent.planning.solver import solve
from travel_agent.routing.travel_time import HaversineEstimator
from travel_agent.training.corrupt import EXPECTED_CODE, CorruptionKind, corrupt
from travel_agent.validation.validator import validate_itinerary

TRAVEL = HaversineEstimator()
POOL = spread_pool()


def solved_plans(count: int) -> list[tuple[PlanRequest, list[Place], Itinerary]]:
    plans = []
    for seed in range(count):
        pace = list(Pace)[seed % 3]
        request = request_for(pace, 1 + seed % 3, TravelMode.MOTORBIKE, DAY_WINDOWS[seed % 4])
        candidates = select_candidates(request, POOL, seed)
        result = solve(request, candidates, TRAVEL, seed)
        assert result.itinerary is not None
        plans.append((request, candidates, result.itinerary))
    return plans


PLANS = solved_plans(8)


@pytest.mark.parametrize("kind", list(CorruptionKind))
def test_each_kind_produces_its_issue_code(kind: CorruptionKind) -> None:
    clean = 0
    for index, (request, candidates, itinerary) in enumerate(PLANS):
        result = corrupt(request, itinerary, candidates, TRAVEL, kind, seed=index)
        assert result is not None
        report = validate_itinerary(
            request, result.itinerary, InMemoryPlaceRepository(candidates), TRAVEL
        )
        assert report == result.report
        assert EXPECTED_CODE[kind] in {issue.code for issue in report.errors()}
        assert result.itinerary != itinerary
        clean += result.clean
    # Phần lớn mẫu chỉ có đúng một loại lỗi, để repair dạy sửa đúng chỗ.
    assert clean >= len(PLANS) * 3 // 4


def test_corruption_is_deterministic_and_leaves_the_plan_untouched() -> None:
    request, candidates, itinerary = PLANS[0]
    before = itinerary.model_copy(deep=True)
    first = corrupt(request, itinerary, candidates, TRAVEL, CorruptionKind.OVERLAP, seed=3)
    second = corrupt(request, itinerary, candidates, TRAVEL, CorruptionKind.OVERLAP, seed=3)
    assert first == second
    assert itinerary == before


def test_seed_changes_the_corruption() -> None:
    request, candidates, itinerary = PLANS[1]
    results = [
        corrupt(request, itinerary, candidates, TRAVEL, CorruptionKind.UNKNOWN_PLACE, seed)
        for seed in range(6)
    ]
    assert len({result.itinerary.model_dump_json() for result in results if result}) > 1


def test_unknown_place_id_looks_like_a_real_id() -> None:
    request, candidates, itinerary = PLANS[2]
    result = corrupt(request, itinerary, candidates, TRAVEL, CorruptionKind.UNKNOWN_PLACE, 0)
    assert result is not None
    known = {place.id for place in candidates}
    [fake] = [s.place_id for d in result.itinerary.days for s in d.stops if s.place_id not in known]
    assert fake.startswith("t:") and "/" in fake


def with_hours(candidates: Sequence[Place], hours: str | None) -> list[Place]:
    return [place.model_copy(update={"opening_hours_raw": hours}) for place in candidates]


def test_closed_is_not_applicable_without_known_hours() -> None:
    request, candidates, itinerary = PLANS[0]
    unknown = with_hours(candidates, None)
    assert corrupt(request, itinerary, unknown, TRAVEL, CorruptionKind.CLOSED, 0) is None


def test_closed_is_not_applicable_when_every_place_is_always_open() -> None:
    request, candidates, itinerary = PLANS[0]
    always = with_hours(candidates, "24/7")
    assert corrupt(request, itinerary, always, TRAVEL, CorruptionKind.CLOSED, 0) is None


def test_travel_gap_is_not_applicable_when_places_share_coordinates() -> None:
    request, candidates, itinerary = PLANS[0]
    same_spot = [place.model_copy(update={"coords": candidates[0].coords}) for place in candidates]
    assert corrupt(request, itinerary, same_spot, TRAVEL, CorruptionKind.TRAVEL_GAP, 0) is None


def test_overlap_is_not_applicable_with_one_stop_per_day() -> None:
    request, candidates, itinerary = PLANS[0]
    first_only = Itinerary(
        days=[day.model_copy(update={"stops": day.stops[:1]}) for day in itinerary.days]
    )
    assert corrupt(request, first_only, candidates, TRAVEL, CorruptionKind.OVERLAP, 0) is None


def test_shifts_stay_inside_the_clock() -> None:
    request, candidates, itinerary = PLANS[3]
    for kind in CorruptionKind:
        result = corrupt(request, itinerary, candidates, TRAVEL, kind, seed=1)
        assert result is not None
        for day in result.itinerary.days:
            for stop in day.stops:
                assert dt.time(0, 0) <= stop.arrive < stop.depart
