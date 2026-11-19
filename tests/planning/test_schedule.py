"""Test retime: xếp lại giờ theo mã, giữ ngày và thứ tự điểm model chọn. Không có mạng."""

import datetime as dt
import random
from collections.abc import Sequence

import pytest

from tests.planning.factories import DAY_WINDOWS, START, make_place, request_for, spread_pool
from tests.validation.factories import FixedTravelTime
from travel_agent.data.place_repository import InMemoryPlaceRepository
from travel_agent.domain.models import (
    Category,
    Itinerary,
    Pace,
    Place,
    PlannedDay,
    PlannedStop,
    PlanRequest,
    TravelMode,
)
from travel_agent.planning.candidates import select_candidates
from travel_agent.planning.durations import VISIT_ATTRIBUTE
from travel_agent.planning.schedule import REASON_DUPLICATE, DroppedStop, RetimeResult, retime
from travel_agent.planning.solver import SolveStatus, solve
from travel_agent.routing.travel_time import HaversineEstimator, TravelTimeProvider
from travel_agent.validation.report import IssueCode, ValidationReport
from travel_agent.validation.validator import validate_itinerary

TRAVEL = HaversineEstimator()
POOL = spread_pool()
NO_TRAVEL = FixedTravelTime(0.0)
TEN_MINUTES = FixedTravelTime(10.0)
# Các mã mà retime phải chặn tuyệt đối trên mọi điểm đã giữ lại.
TIMING_CODES = frozenset(
    {
        IssueCode.TRAVEL_TIME_INSUFFICIENT,
        IssueCode.STOP_OVERLAP,
        IssueCode.STOP_TIME_ORDER,
        IssueCode.CLOSED_DURING_VISIT,
    }
)


def open_place(pid: str, hours: str | None = "24/7", category: Category = Category.ATTRACTION):
    return make_place(pid, category, hours=hours)


def repo(*places: Place) -> InMemoryPlaceRepository:
    return InMemoryPlaceRepository(places)


def stop(pid: str, arrive: str, depart: str) -> PlannedStop:
    return PlannedStop(
        place_id=pid, arrive=dt.time.fromisoformat(arrive), depart=dt.time.fromisoformat(depart)
    )


def itinerary(*days: Sequence[PlannedStop]) -> Itinerary:
    return Itinerary(
        days=[
            PlannedDay(date=START + dt.timedelta(days=index), stops=list(stops))
            for index, stops in enumerate(days)
        ]
    )


def check(
    request: PlanRequest,
    plan: Itinerary,
    lookup: InMemoryPlaceRepository,
    travel: TravelTimeProvider,
) -> ValidationReport:
    return validate_itinerary(request, plan, lookup, travel)


def codes(report: ValidationReport) -> set[IssueCode]:
    return {issue.code for issue in report.issues}


def times(result: RetimeResult, day: int = 0) -> list[tuple[str, str, str]]:
    return [
        (s.place_id, s.arrive.strftime("%H:%M"), s.depart.strftime("%H:%M"))
        for s in result.itinerary.days[day].stops
    ]


def test_tight_schedule_is_free_of_travel_errors() -> None:
    request = request_for(Pace.MODERATE, 1, TravelMode.MOTORBIKE, DAY_WINDOWS[0])
    lookup = repo(open_place("t:a"), open_place("t:b"), open_place("t:c"))
    model = itinerary(
        [
            stop("t:a", "09:00", "10:00"),
            stop("t:b", "10:00", "11:00"),
            stop("t:c", "11:00", "12:00"),
        ]
    )
    assert IssueCode.TRAVEL_TIME_INSUFFICIENT in codes(check(request, model, lookup, TEN_MINUTES))

    result = retime(request, model, lookup, TEN_MINUTES)

    assert result.dropped == []
    assert codes(check(request, result.itinerary, lookup, TEN_MINUTES)).isdisjoint(TIMING_CODES)
    # Giờ model ghi là sàn: A giữ 09:00; B đến sau khi rời A + 10 phút đi; C tương tự.
    assert times(result) == [
        ("t:a", "09:00", "10:00"),
        ("t:b", "10:10", "11:10"),
        ("t:c", "11:20", "12:20"),
    ]


def test_place_opening_later_waits_for_opening() -> None:
    request = request_for(Pace.RELAXED, 1, TravelMode.MOTORBIKE, DAY_WINDOWS[0])
    lookup = repo(open_place("t:late", "13:00-17:00"), open_place("t:after"))
    model = itinerary([stop("t:late", "09:00", "10:00"), stop("t:after", "10:00", "11:00")])

    result = retime(request, model, lookup, NO_TRAVEL)

    assert result.dropped == []
    assert times(result) == [("t:late", "13:00", "14:00"), ("t:after", "14:00", "15:00")]


def test_closed_all_day_stop_is_dropped_and_next_travels_from_last_kept() -> None:
    request = request_for(Pace.RELAXED, 1, TravelMode.MOTORBIKE, DAY_WINDOWS[0])
    # Ngày 1/12/2026 là thứ Ba: không có khung nào nên đóng cửa cả ngày.
    lookup = repo(
        open_place("t:a"),
        open_place("t:closed", "Mo,We-Su 08:00-17:00"),
        open_place("t:c"),
    )
    model = itinerary(
        [
            stop("t:a", "09:00", "10:00"),
            stop("t:closed", "10:00", "11:00"),
            stop("t:c", "11:00", "12:00"),
        ]
    )

    result = retime(request, model, lookup, TEN_MINUTES)

    assert result.dropped == [DroppedStop(0, "t:closed", "đóng cửa cả ngày")]
    # Điểm C đi từ A (rời 10:00) chứ không từ điểm đã bỏ; C giữ giờ 11:00 của model vì đã kịp.
    assert times(result) == [("t:a", "09:00", "10:00"), ("t:c", "11:00", "12:00")]
    assert codes(check(request, result.itinerary, lookup, TEN_MINUTES)).isdisjoint(TIMING_CODES)


def test_stop_that_cannot_end_before_day_end_is_dropped() -> None:
    request = request_for(Pace.RELAXED, 1, TravelMode.MOTORBIKE, (dt.time(8, 0), dt.time(9, 0)))
    lookup = repo(open_place("t:a"), open_place("t:b"))
    model = itinerary([stop("t:a", "08:00", "09:00"), stop("t:b", "09:00", "10:00")])

    result = retime(request, model, lookup, NO_TRAVEL)

    assert result.dropped == [DroppedStop(0, "t:b", "vượt giờ kết thúc ngày")]
    assert times(result) == [("t:a", "08:00", "09:00")]


def test_stop_that_arrives_after_closing_time_is_dropped() -> None:
    request = request_for(Pace.RELAXED, 1, TravelMode.MOTORBIKE, DAY_WINDOWS[0])
    lookup = repo(open_place("t:a", "08:00-10:00"), open_place("t:b", "08:00-09:30"))
    model = itinerary([stop("t:a", "08:00", "09:00"), stop("t:b", "09:00", "10:00")])

    result = retime(request, model, lookup, NO_TRAVEL)

    assert result.dropped == [DroppedStop(0, "t:b", "không kịp trước giờ đóng cửa")]
    # A mở từ 08:00 nên không đến sớm hơn dù ngày bắt đầu 07:30.
    assert times(result) == [("t:a", "08:00", "09:00")]


def test_days_dates_order_and_place_ids_are_kept() -> None:
    request = request_for(Pace.RELAXED, 2, TravelMode.WALK, DAY_WINDOWS[1])
    lookup = repo(*(open_place(f"t:{name}") for name in "abcd"))
    model = itinerary(
        [stop("t:b", "09:00", "10:00"), stop("t:a", "10:00", "11:00")],
        [stop("t:d", "09:00", "10:00"), stop("t:c", "10:00", "11:00")],
    )

    result = retime(request, model, lookup, NO_TRAVEL)

    assert result.dropped == []
    assert [day.date for day in result.itinerary.days] == [START, START + dt.timedelta(days=1)]
    assert [[s.place_id for s in day.stops] for day in result.itinerary.days] == [
        ["t:b", "t:a"],
        ["t:d", "t:c"],
    ]


def test_unknown_place_is_kept_and_reported_by_validator() -> None:
    request = request_for(Pace.RELAXED, 1, TravelMode.MOTORBIKE, DAY_WINDOWS[0])
    lookup = repo(open_place("t:a"), open_place("t:b"))
    model = itinerary(
        [
            stop("t:a", "09:00", "10:00"),
            stop("t:ghost", "10:30", "11:00"),
            stop("t:b", "11:00", "12:00"),
        ]
    )

    result = retime(request, model, lookup, NO_TRAVEL)

    assert result.dropped == []
    assert [s.place_id for s in result.itinerary.days[0].stops] == ["t:a", "t:ghost", "t:b"]
    # Điểm lạ giữ nguyên giờ của model; điểm sau nó không được xếp trước giờ rời của nó.
    assert times(result)[1] == ("t:ghost", "10:30", "11:00")
    assert times(result)[2] == ("t:b", "11:00", "12:00")
    report = check(request, result.itinerary, lookup, NO_TRAVEL)
    assert [(i.code, i.stop_index) for i in report.errors()] == [(IssueCode.UNKNOWN_PLACE, 1)]


def test_already_valid_plan_stays_valid() -> None:
    request = request_for(Pace.RELAXED, 1, TravelMode.MOTORBIKE, DAY_WINDOWS[0])
    lookup = repo(open_place("t:a"), open_place("t:b"))
    model = itinerary([stop("t:a", "09:00", "10:00"), stop("t:b", "11:00", "12:00")])
    assert check(request, model, lookup, TEN_MINUTES).errors() == []

    result = retime(request, model, lookup, TEN_MINUTES)

    assert result.dropped == []
    assert check(request, result.itinerary, lookup, TEN_MINUTES).errors() == []


def test_day_with_every_stop_dropped_keeps_first_stop_for_the_validator() -> None:
    request = request_for(Pace.RELAXED, 1, TravelMode.MOTORBIKE, DAY_WINDOWS[0])
    closed = "Mo,We-Su 08:00-17:00"  # thứ Ba đóng cửa
    lookup = repo(open_place("t:x", closed), open_place("t:z", closed))
    model = itinerary([stop("t:x", "09:00", "10:00"), stop("t:z", "10:00", "11:00")])

    result = retime(request, model, lookup, NO_TRAVEL)

    # Schema bắt buộc mỗi ngày có ít nhất một điểm: giữ điểm đầu nguyên giờ để validator báo lỗi.
    assert times(result) == [("t:x", "09:00", "10:00")]
    assert result.dropped == [DroppedStop(0, "t:z", "đóng cửa cả ngày")]
    assert IssueCode.CLOSED_DURING_VISIT in codes(
        check(request, result.itinerary, lookup, NO_TRAVEL)
    )


def test_unknown_opening_hours_use_the_day_window() -> None:
    request = request_for(Pace.RELAXED, 1, TravelMode.MOTORBIKE, (dt.time(8, 0), dt.time(9, 0)))
    lookup = repo(open_place("t:a", None), open_place("t:b", None))
    model = itinerary([stop("t:a", "08:00", "09:00"), stop("t:b", "09:00", "10:00")])

    result = retime(request, model, lookup, NO_TRAVEL)

    assert result.dropped == [DroppedStop(0, "t:b", "vượt giờ kết thúc ngày")]


@pytest.mark.parametrize(
    ("pace", "num_days", "mode"),
    [
        (Pace.RELAXED, 1, TravelMode.MOTORBIKE),
        (Pace.MODERATE, 2, TravelMode.WALK),
        (Pace.PACKED, 2, TravelMode.CAR),
    ],
)
def test_solver_plans_stay_valid_after_retime(pace: Pace, num_days: int, mode: TravelMode) -> None:
    for seed in range(2):
        request = request_for(pace, num_days, mode, DAY_WINDOWS[seed])
        candidates = select_candidates(request, POOL, seed)
        solved = solve(request, candidates, TRAVEL, seed)
        assert solved.status is SolveStatus.SOLVED, solved.detail
        assert solved.itinerary is not None
        lookup = InMemoryPlaceRepository(candidates)

        result = retime(request, solved.itinerary, lookup, TRAVEL)

        assert result.dropped == []
        assert check(request, result.itinerary, lookup, TRAVEL).errors() == []
        assert [[s.place_id for s in d.stops] for d in result.itinerary.days] == [
            [s.place_id for s in d.stops] for d in solved.itinerary.days
        ]


def _model_like(rng: random.Random, request: PlanRequest, pool: Sequence[Place]) -> Itinerary:
    """Lịch giống output model: giờ và thời lượng tùy ý, có thể chồng nhau hoặc đảo ngược."""
    days: list[list[PlannedStop]] = []
    for _ in range(request.num_days):
        day: list[PlannedStop] = []
        for place in rng.sample(list(pool), rng.randint(1, 8)):
            arrive = rng.randint(6 * 60, 23 * 60)
            depart = min(arrive + rng.randint(-15, 150), 23 * 60 + 59)
            day.append(
                stop(
                    place.id,
                    f"{arrive // 60:02d}:{arrive % 60:02d}",
                    f"{depart // 60:02d}:{depart % 60:02d}",
                )
            )
        days.append(day)
    return itinerary(*days)


def test_model_like_input_never_gets_timing_errors_on_kept_stops() -> None:
    rng = random.Random(20261118)
    kept_total = dropped_total = 0
    for seed in range(10):
        window = (*DAY_WINDOWS, (dt.time(8, 0), dt.time(11, 0)))[seed % 5]
        request = request_for(Pace.PACKED, 2, TravelMode.MOTORBIKE, window)
        pool = select_candidates(request, POOL, seed)
        lookup = InMemoryPlaceRepository(pool)
        model = _model_like(rng, request, pool)

        result = retime(request, model, lookup, TRAVEL)

        dropped = {(d.day_index, d.place_id) for d in result.dropped}
        dropped_total += len(result.dropped)
        kept_total += sum(len(day.stops) for day in result.itinerary.days)
        # Ngày mà mọi điểm đều bị bỏ trừ điểm đầu: điểm đầu được giữ nguyên giờ có chủ đích
        # (xem test_day_with_every_stop_dropped...), nên không kiểm lỗi giờ của ngày đó.
        fallback = {
            index
            for index, day in enumerate(model.days)
            if (index, day.stops[0].place_id) not in dropped
            and all((index, s.place_id) in dropped for s in day.stops[1:])
        }
        report = check(request, result.itinerary, lookup, TRAVEL)
        bad = [
            issue
            for issue in report.issues
            if issue.code in TIMING_CODES and issue.day_index not in fallback
        ]
        assert bad == [], seed
    assert dropped_total > 0
    assert kept_total > 0


def test_retime_is_deterministic() -> None:
    request = request_for(Pace.MODERATE, 1, TravelMode.MOTORBIKE, DAY_WINDOWS[2])
    pool = select_candidates(request, POOL, 3)
    model = _model_like(random.Random(5), request, pool)
    lookup = InMemoryPlaceRepository(pool)
    assert retime(request, model, lookup, TRAVEL) == retime(request, model, lookup, TRAVEL)


def _missing_meal_count(request, plan, lookup) -> int:
    report = check(request, plan, lookup, TEN_MINUTES)
    return sum(1 for issue in report.issues if issue.code is IssueCode.MISSING_MEAL)


def test_lunch_modelled_before_the_lunch_window_is_moved_into_it() -> None:
    request = request_for(Pace.MODERATE, 1, TravelMode.MOTORBIKE, DAY_WINDOWS[0])
    lookup = repo(
        open_place("t:a"),
        open_place("t:b"),
        open_place("t:lunch", category=Category.RESTAURANT),
    )
    model = itinerary(
        [
            stop("t:a", "08:00", "09:00"),
            stop("t:b", "09:00", "10:00"),
            stop("t:lunch", "10:50", "11:50"),
        ]
    )
    result = retime(request, model, lookup, TEN_MINUTES)
    # Model đặt trước khung 11:00-13:30: không xếp sớm hơn giờ bắt đầu khung bữa trưa.
    assert times(result)[-1] == ("t:lunch", "11:00", "12:00")
    assert _missing_meal_count(request, result.itinerary, lookup) <= _missing_meal_count(
        request, model, lookup
    )


def test_dinner_modelled_early_in_the_dinner_window_is_moved_into_it() -> None:
    request = request_for(Pace.MODERATE, 1, TravelMode.MOTORBIKE, DAY_WINDOWS[0])
    lookup = repo(open_place("t:a"), open_place("t:dinner", category=Category.RESTAURANT))
    # Model đặt chồng lên khung bữa tối (17:30-20:00) nhưng bắt đầu sớm: neo vào 17:30.
    model = itinerary([stop("t:a", "08:00", "09:00"), stop("t:dinner", "17:00", "18:00")])
    result = retime(request, model, lookup, TEN_MINUTES)
    assert times(result)[-1] == ("t:dinner", "17:30", "18:30")


def test_meal_window_is_not_applied_when_day_does_not_cover_it() -> None:
    # Khung 09:00-18:00 không bao trọn bữa tối 17:30-20:00: nhà hàng tối không bị neo.
    request = request_for(Pace.MODERATE, 1, TravelMode.MOTORBIKE, DAY_WINDOWS[2])
    lookup = repo(open_place("t:a"), open_place("t:dinner", category=Category.RESTAURANT))
    model = itinerary([stop("t:a", "09:00", "10:00"), stop("t:dinner", "17:45", "18:00")])
    result = retime(request, model, lookup, TEN_MINUTES)
    # Giờ model được giữ: 17:45 (không có khung bữa nào neo lên 17:30 và không kéo về 10:10).
    assert times(result)[-1][1] == "17:45"


def test_non_restaurant_in_a_meal_window_keeps_the_model_time() -> None:
    request = request_for(Pace.MODERATE, 1, TravelMode.MOTORBIKE, DAY_WINDOWS[0])
    lookup = repo(open_place("t:a"), open_place("t:cafe", category=Category.CAFE))
    model = itinerary([stop("t:a", "08:00", "09:00"), stop("t:cafe", "11:30", "12:00")])
    result = retime(request, model, lookup, TEN_MINUTES)
    # Quán cà phê không neo vào khung bữa; giờ 11:30 của model được giữ.
    assert times(result)[-1] == ("t:cafe", "11:30", "12:00")


def test_afternoon_visit_at_fifteen_keeps_fifteen() -> None:
    request = request_for(Pace.RELAXED, 1, TravelMode.MOTORBIKE, DAY_WINDOWS[0])
    lookup = repo(open_place("t:a"), open_place("t:b"))
    model = itinerary([stop("t:a", "09:00", "10:00"), stop("t:b", "15:00", "16:00")])
    result = retime(request, model, lookup, TEN_MINUTES)
    assert times(result) == [("t:a", "09:00", "10:00"), ("t:b", "15:00", "16:00")]
    assert check(request, result.itinerary, lookup, TEN_MINUTES).errors() == []


def test_retime_never_moves_a_stop_earlier_than_the_model() -> None:
    request = request_for(Pace.RELAXED, 1, TravelMode.MOTORBIKE, DAY_WINDOWS[0])
    lookup = repo(open_place("t:a"), open_place("t:b"), open_place("t:c"))
    model = itinerary(
        [
            stop("t:a", "09:00", "10:00"),
            stop("t:b", "12:00", "13:00"),
            stop("t:c", "13:30", "14:30"),
        ]
    )
    result = retime(request, model, lookup, NO_TRAVEL)
    arrives = [s.arrive for s in result.itinerary.days[0].stops]
    assert arrives == [dt.time(9, 0), dt.time(12, 0), dt.time(13, 30)]


def timed(pid: str, raw: str) -> Place:
    """Điểm có thuộc tính thời lượng tham quan trong DB (dạng thật là chuỗi số phút)."""
    return open_place(pid).model_copy(update={"attributes": {VISIT_ATTRIBUTE: raw}})


def test_duplicate_within_a_day_is_dropped_and_first_occurrence_kept() -> None:
    request = request_for(Pace.RELAXED, 1, TravelMode.MOTORBIKE, DAY_WINDOWS[0])
    lookup = repo(open_place("t:a"), open_place("t:b"))
    model = itinerary(
        [
            stop("t:a", "09:00", "10:00"),
            stop("t:b", "10:00", "11:00"),
            stop("t:a", "11:00", "12:00"),
        ]
    )

    result = retime(request, model, lookup, NO_TRAVEL)

    assert result.dropped == [DroppedStop(0, "t:a", REASON_DUPLICATE)]
    assert times(result) == [("t:a", "09:00", "10:00"), ("t:b", "10:00", "11:00")]
    assert IssueCode.DUPLICATE_PLACE not in codes(
        check(request, result.itinerary, lookup, NO_TRAVEL)
    )


def test_duplicate_across_days_is_dropped_from_the_later_day() -> None:
    request = request_for(Pace.RELAXED, 2, TravelMode.WALK, DAY_WINDOWS[1])
    lookup = repo(*(open_place(f"t:{name}") for name in "abc"))
    model = itinerary(
        [stop("t:a", "09:00", "10:00"), stop("t:b", "10:00", "11:00")],
        [stop("t:b", "09:00", "10:00"), stop("t:c", "10:00", "11:00")],
    )

    result = retime(request, model, lookup, NO_TRAVEL)

    assert result.dropped == [DroppedStop(1, "t:b", REASON_DUPLICATE)]
    assert [[s.place_id for s in day.stops] for day in result.itinerary.days] == [
        ["t:a", "t:b"],
        ["t:c"],
    ]
    assert IssueCode.DUPLICATE_PLACE not in codes(
        check(request, result.itinerary, lookup, NO_TRAVEL)
    )


def test_duplicate_is_removed_before_timing_so_travel_starts_from_the_kept_stop() -> None:
    request = request_for(Pace.RELAXED, 1, TravelMode.MOTORBIKE, DAY_WINDOWS[0])
    lookup = repo(open_place("t:a"), open_place("t:b"))
    model = itinerary(
        [
            stop("t:a", "09:00", "10:00"),
            stop("t:a", "10:00", "10:30"),
            stop("t:b", "10:00", "11:00"),
        ]
    )

    result = retime(request, model, lookup, TEN_MINUTES)

    # Nếu trùng còn trong lúc xếp giờ, A thứ hai giữ tới 10:30 và B đến 10:40. Bỏ trùng trước
    # nên B đi từ A đã giữ (rời 10:00): đến 10:10.
    assert times(result) == [("t:a", "09:00", "10:00"), ("t:b", "10:10", "11:10")]


def test_day_made_only_of_duplicates_keeps_its_first_stop_for_the_validator() -> None:
    request = request_for(Pace.RELAXED, 2, TravelMode.WALK, DAY_WINDOWS[1])
    lookup = repo(open_place("t:a"), open_place("t:b"))
    model = itinerary(
        [stop("t:a", "09:00", "10:00"), stop("t:b", "10:00", "11:00")],
        [stop("t:a", "09:00", "10:00"), stop("t:b", "10:00", "11:00")],
    )

    result = retime(request, model, lookup, NO_TRAVEL)

    # Schema cần một điểm mỗi ngày: giữ điểm đầu của ngày 2, nên validator báo duplicate_place.
    assert result.dropped == [DroppedStop(1, "t:b", REASON_DUPLICATE)]
    assert [[s.place_id for s in day.stops] for day in result.itinerary.days] == [
        ["t:a", "t:b"],
        ["t:a"],
    ]
    report = check(request, result.itinerary, lookup, NO_TRAVEL)
    assert [(i.code, i.day_index, i.stop_index) for i in report.errors()] == [
        (IssueCode.DUPLICATE_PLACE, 1, 0)
    ]


def test_database_visit_time_sets_the_departure() -> None:
    request = request_for(Pace.RELAXED, 1, TravelMode.MOTORBIKE, DAY_WINDOWS[0])
    lookup = repo(open_place("t:a"), timed("t:b", "120"))
    model = itinerary([stop("t:a", "09:00", "10:00"), stop("t:b", "15:00", "15:30")])

    result = retime(request, model, lookup, NO_TRAVEL)

    # Model ghi 30 phút nhưng DB ghi 120 phút: lượt thăm lấy 120 phút.
    assert times(result) == [("t:a", "09:00", "10:00"), ("t:b", "15:00", "17:00")]


def test_database_visit_time_is_clamped_to_the_range() -> None:
    request = request_for(Pace.RELAXED, 1, TravelMode.MOTORBIKE, DAY_WINDOWS[0])
    lookup = repo(timed("t:long", "600"))
    model = itinerary([stop("t:long", "09:00", "10:00")])

    result = retime(request, model, lookup, NO_TRAVEL)

    assert times(result) == [("t:long", "09:00", "13:00")]  # 600 phút kẹp về 240


def test_retime_takes_visit_minutes_from_the_database_not_the_solver_constant() -> None:
    request = request_for(Pace.RELAXED, 1, TravelMode.MOTORBIKE, DAY_WINDOWS[0])
    # Model ghi 45 phút, DB ghi 90 phút (dạng thật): thuộc tính DB thắng, không giữ 45.
    lookup = repo(timed("t:cafe", "90"))
    model = itinerary([stop("t:cafe", "09:00", "09:45")])

    result = retime(request, model, lookup, NO_TRAVEL)

    assert times(result) == [("t:cafe", "09:00", "10:30")]
    assert check(request, result.itinerary, lookup, NO_TRAVEL).errors() == []
