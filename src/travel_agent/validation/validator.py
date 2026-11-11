"""Validator: cổng kiểm chứng bắt buộc cho lịch trình do LLM sinh.

Mỗi Issue có vị trí (day_index, stop_index) để vòng repair chỉ đúng chỗ sai cho LLM.
"""

from __future__ import annotations

import datetime as dt

from travel_agent.data.place_repository import PlaceLookup
from travel_agent.domain.models import Itinerary, PlannedStop, PlanRequest
from travel_agent.routing.travel_time import TravelTimeProvider
from travel_agent.validation.report import Issue, IssueCode, Severity, ValidationReport


def validate_itinerary(
    request: PlanRequest,
    itinerary: Itinerary,
    places: PlaceLookup,
    travel: TravelTimeProvider,
) -> ValidationReport:
    issues: list[Issue] = []
    _check_days(request, itinerary, issues)
    seen: set[str] = set()
    for d_idx, day in enumerate(itinerary.days):
        resolved = [places.get(stop.place_id) for stop in day.stops]
        for s_idx, (stop, place) in enumerate(zip(day.stops, resolved, strict=True)):
            if place is None:
                issues.append(
                    _issue(
                        Severity.ERROR,
                        IssueCode.UNKNOWN_PLACE,
                        f"place_id {stop.place_id} không có trong danh sách địa điểm",
                        d_idx,
                        s_idx,
                        stop.place_id,
                    )
                )
            if stop.place_id in seen:
                issues.append(
                    _issue(
                        Severity.ERROR,
                        IssueCode.DUPLICATE_PLACE,
                        f"Địa điểm {stop.place_id} đã xuất hiện trước đó trong lịch trình",
                        d_idx,
                        s_idx,
                        stop.place_id,
                    )
                )
            seen.add(stop.place_id)
            _check_stop_times(request, stop, d_idx, s_idx, issues)
    return ValidationReport(issues=issues)


def _issue(
    severity: Severity,
    code: IssueCode,
    message: str,
    day_index: int | None = None,
    stop_index: int | None = None,
    place_id: str | None = None,
) -> Issue:
    return Issue(
        code=code,
        severity=severity,
        message=message,
        day_index=day_index,
        stop_index=stop_index,
        place_id=place_id,
    )


def _check_days(request: PlanRequest, itinerary: Itinerary, issues: list[Issue]) -> None:
    if len(itinerary.days) != request.num_days:
        issues.append(
            _issue(
                Severity.ERROR,
                IssueCode.DAY_COUNT_MISMATCH,
                f"Cần {request.num_days} ngày, lịch trình có {len(itinerary.days)} ngày",
            )
        )
    for d_idx, day in enumerate(itinerary.days):
        expected = request.start_date + dt.timedelta(days=d_idx)
        if day.date != expected:
            issues.append(
                _issue(
                    Severity.ERROR,
                    IssueCode.DATE_MISMATCH,
                    f"Ngày thứ {d_idx + 1} ghi {day.date.isoformat()}, "
                    f"phải là {expected.isoformat()}",
                    d_idx,
                )
            )


def _check_stop_times(
    request: PlanRequest, stop: PlannedStop, d_idx: int, s_idx: int, issues: list[Issue]
) -> None:
    if stop.depart <= stop.arrive:
        issues.append(
            _issue(
                Severity.ERROR,
                IssueCode.STOP_TIME_ORDER,
                f"Giờ rời ({stop.depart:%H:%M}) phải sau giờ đến ({stop.arrive:%H:%M})",
                d_idx,
                s_idx,
                stop.place_id,
            )
        )
    if stop.arrive < request.day_start or stop.depart > request.day_end:
        issues.append(
            _issue(
                Severity.ERROR,
                IssueCode.OUTSIDE_DAY_WINDOW,
                f"Điểm dừng {stop.arrive:%H:%M}-{stop.depart:%H:%M} nằm ngoài khung ngày "
                f"{request.day_start:%H:%M}-{request.day_end:%H:%M}",
                d_idx,
                s_idx,
                stop.place_id,
            )
        )
