"""Lấp khoảng trống (planning/fill.py): dữ liệu giả, travel cố định 10 phút, không mạng."""

import datetime as dt
from typing import Any

import pytest

from tests.planning.factories import START, make_place, make_request
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
)
from travel_agent.planning import fill as fill_module
from travel_agent.planning.fill import GAP_REASON, AddedStop, fill_gaps
from travel_agent.planning.pipeline import plan_trip
from travel_agent.training.generator import Generation
from travel_agent.validation.report import Issue, IssueCode, Severity, ValidationReport
from travel_agent.validation.validator import validate_itinerary

TRAVEL = FixedTravelTime(minutes=10.0)
StopSpec = tuple[str, str, str]  # (place_id, arrive "HH:MM", depart "HH:MM")


def _itin(*days: list[StopSpec]) -> Itinerary:
    return Itinerary(
        days=[
            PlannedDay(
                date=START + dt.timedelta(days=index),
                stops=[
                    PlannedStop(
                        place_id=pid,
                        arrive=dt.time.fromisoformat(arrive),
                        depart=dt.time.fromisoformat(depart),
                    )
                    for pid, arrive, depart in day
                ],
            )
            for index, day in enumerate(days)
        ]
    )


def _ids(itinerary: Itinerary, day: int = 0) -> list[str]:
    return [stop.place_id for stop in itinerary.days[day].stops]


def _still() -> float:
    """Đồng hồ cố định, để latency_s giống nhau giữa các lần chạy."""
    return 0.0


def _errors(request: PlanRequest, itinerary: Itinerary, places: list[Place]) -> list[Issue]:
    lookup = InMemoryPlaceRepository(places)
    return validate_itinerary(request, itinerary, lookup, TRAVEL).errors()


# Ngày có bữa trưa và bữa tối, và một khoảng trống 12:30-18:00 giữa chừng.
AFTERNOON_GAP: list[StopSpec] = [
    ("t:museum", "08:30", "10:30"),
    ("t:lunch", "11:30", "12:30"),
    ("t:dinner", "18:00", "19:00"),
]
LUNCH_AND_DINNER = [("t:lunch", "11:30", "12:30"), ("t:dinner", "18:00", "19:00")]


def _restaurants() -> list[Place]:
    return [
        make_place("t:lunch", Category.RESTAURANT),
        make_place("t:dinner", Category.RESTAURANT),
    ]


def test_afternoon_gap_is_filled_with_an_interest_matching_place() -> None:
    # "aaa-park" đứng đầu theo id nếu không xét sở thích; "history" phải kéo "t:hist" lên trước.
    places = [
        *_restaurants(),
        make_place("t:museum", Category.MUSEUM),
        make_place("t:aaa-park", Category.PARK),
        make_place("t:hist", Category.HISTORIC),
    ]
    request = make_request(num_days=1, pace=Pace.MODERATE, interests=["history"])
    itinerary = _itin(AFTERNOON_GAP)

    result, added = fill_gaps(request, itinerary, places, TRAVEL)

    assert added[0] == AddedStop(day_index=0, place_id="t:hist", reason=GAP_REASON)
    ids = _ids(result)
    assert ids.index("t:lunch") < ids.index("t:hist") < ids.index("t:dinner")
    assert _errors(request, result, places) == []


def test_gap_fill_respects_opening_hours() -> None:
    # "t:hist" đóng cửa trước 12:00, nên không vừa khoảng trống; "t:aaa-park" không có giờ thì vừa.
    places = [
        *_restaurants(),
        make_place("t:museum", Category.MUSEUM),
        make_place("t:aaa-park", Category.PARK),
        make_place("t:hist", Category.HISTORIC, hours="Mo-Su 08:00-12:00"),
    ]
    request = make_request(num_days=1, pace=Pace.MODERATE, interests=["history"])

    result, added = fill_gaps(request, _itin(AFTERNOON_GAP), places, TRAVEL)

    assert "t:hist" not in _ids(result)
    assert added[0].place_id == "t:aaa-park"
    assert _errors(request, result, places) == []


def test_gap_fill_stops_at_pace_maximum() -> None:
    # Nhịp thong thả tối đa 4 điểm; ngày đã có 4 điểm và còn khoảng trống dài thì không thêm gì.
    places = [
        *_restaurants(),
        make_place("t:museum", Category.MUSEUM),
        make_place("t:cafe", Category.CAFE),
        make_place("t:aaa-park", Category.PARK),
        make_place("t:hist", Category.HISTORIC),
    ]
    spec: list[StopSpec] = [
        ("t:museum", "08:30", "09:30"),
        ("t:lunch", "11:30", "12:30"),
        ("t:cafe", "14:00", "14:45"),
        ("t:dinner", "18:00", "19:00"),
    ]
    request = make_request(num_days=1, pace=Pace.RELAXED)
    itinerary = _itin(spec)

    result, added = fill_gaps(request, itinerary, places, TRAVEL)

    assert added == []
    assert result is itinerary


def test_moderate_day_is_never_filled_past_six_stops() -> None:
    places = [
        *_restaurants(),
        make_place("t:museum", Category.MUSEUM),
        make_place("t:cafe", Category.CAFE),
        make_place("t:hist", Category.HISTORIC),
        make_place("t:aaa-park", Category.PARK),
        make_place("t:bbb-park", Category.PARK),
        make_place("t:ccc-park", Category.PARK),
        make_place("t:ddd-park", Category.PARK),
    ]
    spec: list[StopSpec] = [
        ("t:museum", "08:30", "09:45"),
        ("t:lunch", "11:30", "12:30"),
        ("t:cafe", "13:00", "13:45"),
        ("t:hist", "14:30", "15:30"),
        ("t:dinner", "18:00", "19:00"),
    ]
    request = make_request(num_days=1, pace=Pace.MODERATE)

    result, added = fill_gaps(request, _itin(spec), places, TRAVEL)

    assert len(_ids(result)) == 6
    assert len(added) == 1


def test_missing_dinner_is_filled_inside_the_dinner_window() -> None:
    places = [
        make_place("t:museum", Category.MUSEUM),
        make_place("t:lunch", Category.RESTAURANT),
        make_place("t:dinner", Category.RESTAURANT),
        make_place("t:hist", Category.HISTORIC),
    ]
    spec: list[StopSpec] = [
        ("t:museum", "08:30", "10:30"),
        ("t:lunch", "11:30", "12:30"),
        ("t:hist", "14:00", "15:00"),
    ]
    request = make_request(num_days=1, pace=Pace.MODERATE)

    result, added = fill_gaps(request, _itin(spec), places, TRAVEL)

    assert added[0] == AddedStop(day_index=0, place_id="t:dinner", reason="bổ sung bữa tối")
    dinner = next(stop for stop in result.days[0].stops if stop.place_id == "t:dinner")
    assert dt.time(17, 30) <= dinner.arrive
    assert dinner.depart <= dt.time(20, 0)
    assert _errors(request, result, places) == []


def test_missing_lunch_is_filled_when_day_covers_the_window() -> None:
    places = [
        make_place("t:museum", Category.MUSEUM),
        make_place("t:lunch", Category.RESTAURANT),
        make_place("t:dinner", Category.RESTAURANT),
    ]
    spec: list[StopSpec] = [("t:museum", "08:30", "10:30"), ("t:dinner", "18:00", "19:00")]
    request = make_request(num_days=1, pace=Pace.MODERATE)

    result, added = fill_gaps(request, _itin(spec), places, TRAVEL)

    assert added[0].reason == "bổ sung bữa trưa"
    assert added[0].place_id == "t:lunch"


def test_places_already_in_the_itinerary_are_never_added_again() -> None:
    places = [
        *_restaurants(),
        make_place("t:museum", Category.MUSEUM),
        make_place("t:aaa-park", Category.PARK),
    ]
    request = make_request(num_days=1, pace=Pace.MODERATE, interests=["history"])

    result, added = fill_gaps(request, _itin(AFTERNOON_GAP), places, TRAVEL)

    ids = _ids(result)
    assert ids.count("t:museum") == 1
    assert "t:museum" not in [item.place_id for item in added]
    assert len(ids) == len(set(ids))


def test_insertion_that_adds_an_error_is_reverted_and_the_next_candidate_is_tried(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_validate = fill_module.validate_itinerary

    def strict_validate(
        request: PlanRequest, itinerary: Itinerary, places: Any, travel: Any
    ) -> ValidationReport:
        report = real_validate(request, itinerary, places, travel)
        if any(stop.place_id == "t:bad" for day in itinerary.days for stop in day.stops):
            fake = Issue(
                code=IssueCode.CLOSED_DURING_VISIT,
                severity=Severity.ERROR,
                message="lỗi giả để kiểm tra hoàn tác",
                place_id="t:bad",
            )
            report = ValidationReport(
                issues=[*report.issues, fake], estimated_legs=report.estimated_legs
            )
        return report

    monkeypatch.setattr(fill_module, "validate_itinerary", strict_validate)
    places = [
        *_restaurants(),
        make_place("t:museum", Category.MUSEUM),
        make_place("t:bad", Category.HISTORIC),
        make_place("t:aaa-park", Category.PARK),
    ]
    request = make_request(num_days=1, pace=Pace.MODERATE, interests=["history"])

    result, added = fill_gaps(request, _itin(AFTERNOON_GAP), places, TRAVEL)

    assert "t:bad" not in _ids(result)
    assert added[0].place_id == "t:aaa-park"


def test_gap_fill_never_runs_past_day_end() -> None:
    places = [
        make_place("t:museum", Category.MUSEUM),
        make_place("t:lunch", Category.RESTAURANT),
        make_place("t:aaa-park", Category.PARK),
        make_place("t:bbb-park", Category.PARK),
        make_place("t:ccc-park", Category.PARK),
    ]
    spec: list[StopSpec] = [("t:museum", "08:30", "09:30"), ("t:lunch", "11:30", "12:30")]
    request = make_request(num_days=1, pace=Pace.MODERATE).model_copy(
        update={"day_end": dt.time(17, 0)}
    )

    result, added = fill_gaps(request, _itin(spec), places, TRAVEL)

    assert added
    assert all(stop.depart <= dt.time(17, 0) for stop in result.days[0].stops)
    assert _errors(request, result, places) == []


def test_plan_trip_adds_nothing_when_the_flag_is_off() -> None:
    places = [
        make_place("t:museum", Category.MUSEUM),
        make_place("t:lunch", Category.RESTAURANT),
        make_place("t:dinner", Category.RESTAURANT),
        make_place("t:aaa-park", Category.PARK),
        make_place("t:hist", Category.HISTORIC),
    ]
    request = make_request(num_days=1, pace=Pace.MODERATE, interests=["history"])
    raw = _itin(AFTERNOON_GAP).model_dump_json()
    generator = _FixedGenerator(raw)

    off = plan_trip(request, places, generator, TRAVEL, fill_gaps=False, clock=_still)
    default = plan_trip(request, places, _FixedGenerator(raw), TRAVEL, clock=_still)
    on = plan_trip(request, places, _FixedGenerator(raw), TRAVEL, fill_gaps=True, clock=_still)

    assert off.added == []
    assert off.model_dump_json() == default.model_dump_json()
    assert on.added
    assert on.valid is True
    assert on.model_dump(exclude={"added"}) != off.model_dump(exclude={"added"})


def test_plan_trip_skips_the_fill_without_retime() -> None:
    places = [
        make_place("t:museum", Category.MUSEUM),
        make_place("t:lunch", Category.RESTAURANT),
        make_place("t:dinner", Category.RESTAURANT),
        make_place("t:aaa-park", Category.PARK),
    ]
    request = make_request(num_days=1, pace=Pace.MODERATE)
    generator = _FixedGenerator(_itin(AFTERNOON_GAP).model_dump_json())

    result = plan_trip(
        request, places, generator, TRAVEL, retime=False, fill_gaps=True, clock=_still
    )

    assert result.added == []


class _FixedGenerator:
    """Luôn trả cùng một output; đủ cho test vì lượt đầu đã hợp lệ hoặc không cần sửa."""

    def __init__(self, raw: str) -> None:
        self.raw = raw

    def generate(
        self, messages: list[dict[str, str]], format_schema: dict[str, Any] | None = None
    ) -> Generation:
        return Generation(content=self.raw, done_reason="stop")
