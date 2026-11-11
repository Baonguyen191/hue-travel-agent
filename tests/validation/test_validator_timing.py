from tests.validation.factories import (
    VALID_DAY,
    FixedTravelTime,
    make_day,
    make_itinerary,
    make_request,
    sample_places,
)
from travel_agent.domain.models import Itinerary, Pace, PlanRequest
from travel_agent.routing.travel_time import HaversineEstimator, TravelTimeProvider
from travel_agent.validation.report import Issue, IssueCode, ValidationReport
from travel_agent.validation.validator import validate_itinerary


def run(
    itinerary: Itinerary,
    request: PlanRequest | None = None,
    travel: TravelTimeProvider | None = None,
) -> ValidationReport:
    return validate_itinerary(
        request or make_request(), itinerary, sample_places(), travel or FixedTravelTime()
    )


def codes(issues: list[Issue]) -> list[IssueCode]:
    return [issue.code for issue in issues]


def test_valid_day_only_warns_about_unknown_hours() -> None:
    report = run(make_itinerary(make_day(VALID_DAY)))
    assert report.is_valid
    assert codes(report.issues) == [IssueCode.OPENING_HOURS_UNKNOWN]
    assert report.issues[0].place_id == "t:cafe"
    assert report.estimated_legs == 0


def test_travel_time_insufficient() -> None:
    report = run(make_itinerary(make_day(VALID_DAY)), travel=FixedTravelTime(minutes=30))
    errors = report.errors()
    assert codes(errors) == [IssueCode.TRAVEL_TIME_INSUFFICIENT] * 2
    assert [error.stop_index for error in errors] == [1, 2]


def test_overlapping_stops() -> None:
    stops = [*VALID_DAY]
    stops[1] = ("t:cafe", "10:00", "11:15")
    report = run(make_itinerary(make_day(stops)))
    assert codes(report.errors()) == [IssueCode.STOP_OVERLAP]


def test_closed_during_visit() -> None:
    stops = [
        ("t:lunch", "11:30", "12:30"),
        ("t:museum", "16:00", "17:30"),
        ("t:dinner", "18:00", "19:00"),
    ]
    report = run(make_itinerary(make_day(stops)))
    [error] = report.errors()
    assert error.code is IssueCode.CLOSED_DURING_VISIT
    assert error.stop_index == 1
    assert "Mo-Su 07:00-17:00" in error.message


def test_estimated_legs_are_counted() -> None:
    report = run(
        make_itinerary(make_day(VALID_DAY)), travel=FixedTravelTime(minutes=10, estimated=True)
    )
    assert report.is_valid
    assert report.estimated_legs == 3


def test_haversine_estimator_marks_all_legs_estimated() -> None:
    report = run(make_itinerary(make_day(VALID_DAY)), travel=HaversineEstimator())
    assert report.is_valid
    assert report.estimated_legs == 3


def test_overloaded_relaxed_day_is_warning_only() -> None:
    stops = [*VALID_DAY, ("t:viewpoint", "19:15", "20:00")]
    report = run(make_itinerary(make_day(stops)), make_request(pace=Pace.RELAXED))
    assert report.is_valid
    assert IssueCode.OVERLOADED_DAY in codes(report.issues)


def test_missing_lunch_is_warning() -> None:
    stops = [
        ("t:museum", "08:30", "10:30"),
        ("t:cafe", "10:45", "11:15"),
        ("t:dinner", "18:00", "19:00"),
    ]
    report = run(make_itinerary(make_day(stops)))
    assert report.is_valid
    meal_warnings = [i for i in report.issues if i.code is IssueCode.MISSING_MEAL]
    assert len(meal_warnings) == 1
    assert "bữa trưa" in meal_warnings[0].message
