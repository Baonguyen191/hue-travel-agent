import datetime as dt

from tests.validation.factories import (
    DAY1,
    VALID_DAY,
    FixedTravelTime,
    make_day,
    make_itinerary,
    make_request,
    sample_places,
)
from travel_agent.domain.models import Itinerary, PlanRequest
from travel_agent.validation.report import IssueCode, ValidationReport
from travel_agent.validation.validator import validate_itinerary


def run(itinerary: Itinerary, request: PlanRequest | None = None) -> ValidationReport:
    return validate_itinerary(
        request or make_request(), itinerary, sample_places(), FixedTravelTime()
    )


def error_codes(report: ValidationReport) -> list[IssueCode]:
    return [issue.code for issue in report.errors()]


def test_valid_itinerary_has_no_errors() -> None:
    report = run(make_itinerary(make_day(VALID_DAY)))
    assert report.is_valid
    assert report.errors() == []


def test_unknown_place_is_error_with_position() -> None:
    stops = [*VALID_DAY]
    stops[1] = ("osm:node/999", "10:45", "11:15")
    report = run(make_itinerary(make_day(stops)))
    assert not report.is_valid
    [issue] = report.errors()
    assert issue.code is IssueCode.UNKNOWN_PLACE
    assert (issue.day_index, issue.stop_index, issue.place_id) == (0, 1, "osm:node/999")


def test_repeated_unknown_place_is_reported_only_as_unknown() -> None:
    """Id lạ lặp lại bị báo UNKNOWN_PLACE ở mỗi stop, không cộng thêm DUPLICATE_PLACE."""
    stops = [*VALID_DAY]
    stops[0] = ("osm:node/999", "08:30", "10:30")
    stops[1] = ("osm:node/999", "10:45", "11:15")
    report = run(make_itinerary(make_day(stops)))
    codes = [issue.code for issue in report.issues]
    assert codes.count(IssueCode.UNKNOWN_PLACE) == 2
    assert IssueCode.DUPLICATE_PLACE not in codes


def test_duplicate_place_across_days() -> None:
    day2 = make_day(VALID_DAY, date=DAY1 + dt.timedelta(days=1))
    report = run(make_itinerary(make_day(VALID_DAY), day2), make_request(num_days=2))
    assert error_codes(report) == [IssueCode.DUPLICATE_PLACE] * 4


def test_day_count_mismatch() -> None:
    report = run(make_itinerary(make_day(VALID_DAY)), make_request(num_days=2))
    assert error_codes(report) == [IssueCode.DAY_COUNT_MISMATCH]


def test_date_mismatch() -> None:
    report = run(make_itinerary(make_day(VALID_DAY, date=DAY1 + dt.timedelta(days=1))))
    assert error_codes(report) == [IssueCode.DATE_MISMATCH]


def test_depart_not_after_arrive() -> None:
    stops = [*VALID_DAY]
    stops[0] = ("t:museum", "10:30", "10:30")
    report = run(make_itinerary(make_day(stops)))
    assert error_codes(report) == [IssueCode.STOP_TIME_ORDER]


def test_stop_outside_day_window() -> None:
    stops = [*VALID_DAY]
    stops[0] = ("t:museum", "07:00", "08:00")
    report = run(make_itinerary(make_day(stops)))
    assert error_codes(report) == [IssueCode.OUTSIDE_DAY_WINDOW]
