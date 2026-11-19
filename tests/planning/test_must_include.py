"""Điểm bắt buộc (must_include) trong plan_trip: lỗi tổng hợp, chèn bằng code, báo cáo."""

import json
from typing import Any

from tests.planning.factories import make_place, make_request
from tests.planning.test_pipeline import FakeClock, ScriptedGenerator
from tests.validation.factories import FixedTravelTime
from travel_agent.domain.models import Category, PlanRequest
from travel_agent.planning.pipeline import PlanResult, plan_trip
from travel_agent.planning.prompt import REPAIR_ISSUES_HEADER
from travel_agent.routing.travel_time import HaversineEstimator
from travel_agent.validation.report import IssueCode

TRAVEL = FixedTravelTime(minutes=10.0)
REQUEST: PlanRequest = make_request()  # 1 ngày, 2026-12-01, moderate, khung 08:00-21:00
PLACES = [
    make_place("t:museum", Category.MUSEUM),
    make_place("t:cafe", Category.CAFE),
    make_place("t:lunch", Category.RESTAURANT),
    make_place("t:dinner", Category.RESTAURANT),
]


def _json(days: list[list[tuple[str, str, str]]], start: str = "2026-12-01") -> str:
    payload: list[dict[str, Any]] = []
    for index, stops in enumerate(days):
        date = f"2026-12-{int(start[-2:]) + index:02d}"
        payload.append(
            {
                "date": date,
                "stops": [{"place_id": pid, "arrive": a, "depart": d} for pid, a, d in stops],
            }
        )
    return json.dumps({"days": payload})


# Không có bảo tàng (điểm bắt buộc), nhưng đủ hai bữa ăn: lỗi duy nhất là thiếu điểm bắt buộc.
WITHOUT_MUSEUM = _json(
    [[("t:cafe", "08:30", "09:30"), ("t:lunch", "11:30", "12:30"), ("t:dinner", "18:00", "19:00")]]
)
WITH_MUSEUM = _json(
    [
        [
            ("t:museum", "08:30", "10:30"),
            ("t:lunch", "11:30", "12:30"),
            ("t:dinner", "18:00", "19:00"),
        ]
    ]
)


def _plan(generator: ScriptedGenerator, **kwargs: Any) -> PlanResult:
    return plan_trip(REQUEST, PLACES, generator, TRAVEL, clock=FakeClock(), **kwargs)


def _planned(result: PlanResult) -> list[str]:
    assert result.itinerary is not None
    return [stop.place_id for day in result.itinerary.days for stop in day.stops]


def test_missing_required_place_is_reported_to_the_repair_prompt() -> None:
    generator = ScriptedGenerator([WITHOUT_MUSEUM, WITH_MUSEUM])
    result = _plan(generator, must_include=["t:museum"])

    assert result.valid is True
    assert result.missing_must == []
    assert [attempt.kind for attempt in result.attempts] == ["generate", "repair"]
    assert result.attempts[0].error_count == 1
    user = generator.seen[1][1]["content"]
    assert REPAIR_ISSUES_HEADER in user
    assert "Thiếu điểm bắt buộc: t:museum (t:museum)" in user
    assert IssueCode.MISSING_REQUIRED_PLACE.value in user


def test_missing_required_place_keeps_the_loop_going_until_repairs_run_out() -> None:
    # Lịch không lỗi validator nhưng thiếu bảo tàng: vòng lặp vẫn sửa, không dừng ở lượt đầu.
    generator = ScriptedGenerator([WITHOUT_MUSEUM, WITHOUT_MUSEUM, WITHOUT_MUSEUM])
    result = _plan(generator, must_include=["t:museum"], max_repairs=2)

    assert len(generator.seen) == 3
    assert result.report is not None and result.report.is_valid
    assert result.valid is True


def test_still_missing_required_place_is_inserted_in_code() -> None:
    generator = ScriptedGenerator([WITHOUT_MUSEUM, WITHOUT_MUSEUM, WITHOUT_MUSEUM])
    result = _plan(generator, must_include=["t:museum"], max_repairs=2)

    assert result.inserted_must == ["t:museum"]
    assert result.missing_must == []
    assert "t:museum" in _planned(result)
    assert result.valid is True


def test_inserted_place_is_not_reported_as_validator_error() -> None:
    generator = ScriptedGenerator([WITHOUT_MUSEUM])
    result = _plan(generator, must_include=["t:museum"], max_repairs=0)

    assert result.report is not None
    assert all(issue.code is not IssueCode.MISSING_REQUIRED_PLACE for issue in result.report.issues)
    assert result.valid is True


def test_insertion_goes_to_the_day_with_fewest_stops() -> None:
    two_days = _json(
        [
            [("t:cafe", "08:30", "09:30"), ("t:lunch", "11:30", "12:30")],
            [("t:dinner", "18:00", "19:00")],
        ]
    )
    request = make_request(num_days=2)
    generator = ScriptedGenerator([two_days])
    result = plan_trip(
        request,
        PLACES,
        generator,
        TRAVEL,
        clock=FakeClock(),
        must_include=["t:museum"],
        max_repairs=0,
    )

    assert result.itinerary is not None
    day_ids = [[stop.place_id for stop in day.stops] for day in result.itinerary.days]
    assert "t:museum" not in day_ids[0]
    assert "t:museum" in day_ids[1]
    assert result.inserted_must == ["t:museum"]


def test_insertion_position_minimises_added_travel() -> None:
    # Hai điểm đặt xa nhau; bảo tàng nằm sát điểm B nên phải chèn sau B, không đầu ngày.
    near_centre = 16.4698
    a = make_place("t:a", Category.ATTRACTION, lat=near_centre, lon=107.5786)
    b = make_place("t:b", Category.ATTRACTION, lat=near_centre + 0.03, lon=107.5786)
    museum = make_place("t:museum", Category.MUSEUM, lat=near_centre + 0.031, lon=107.5786)
    output = _json(
        [
            [
                ("t:a", "08:00", "09:00"),
                ("t:b", "09:30", "10:30"),
            ]
        ]
    )
    result = plan_trip(
        REQUEST,
        [a, b, museum],
        ScriptedGenerator([output]),
        HaversineEstimator(),
        clock=FakeClock(),
        must_include=["t:museum"],
        max_repairs=0,
    )
    assert _planned(result) == ["t:a", "t:b", "t:museum"]
    assert result.inserted_must == ["t:museum"]


def test_place_not_in_database_is_reported_missing_and_not_repaired() -> None:
    generator = ScriptedGenerator([WITHOUT_MUSEUM])
    result = _plan(generator, must_include=["t:ghost"])

    assert result.missing_must == ["t:ghost"]
    assert result.inserted_must == []
    assert len(generator.seen) == 1
    assert result.valid is True


def test_excluded_required_place_is_not_inserted() -> None:
    generator = ScriptedGenerator([WITHOUT_MUSEUM])
    result = _plan(generator, must_include=["t:museum"], exclude_ids=["t:museum"])

    assert result.missing_must == ["t:museum"]
    assert result.inserted_must == []
    assert len(generator.seen) == 1
    assert result.valid is True


def test_no_insertion_without_retime() -> None:
    generator = ScriptedGenerator([WITHOUT_MUSEUM, WITHOUT_MUSEUM, WITHOUT_MUSEUM])
    result = _plan(generator, must_include=["t:museum"], retime=False, max_repairs=2)

    assert len(generator.seen) == 3
    assert result.inserted_must == []
    assert result.missing_must == ["t:museum"]


def test_required_place_already_present_is_not_inserted_twice() -> None:
    generator = ScriptedGenerator([WITH_MUSEUM])
    result = _plan(generator, must_include=["t:museum"])

    assert result.inserted_must == []
    assert result.missing_must == []
    assert _planned(result).count("t:museum") == 1
