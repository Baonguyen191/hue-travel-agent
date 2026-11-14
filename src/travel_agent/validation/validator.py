"""Validator: cổng kiểm chứng bắt buộc cho lịch trình do LLM sinh.

Mỗi Issue có vị trí (day_index, stop_index) để vòng repair chỉ đúng chỗ sai cho LLM.
"""

from __future__ import annotations

import datetime as dt

from travel_agent.data.place_repository import PlaceLookup
from travel_agent.domain.models import Category, Itinerary, Pace, Place, PlannedStop, PlanRequest
from travel_agent.domain.opening_hours import parse_opening_hours
from travel_agent.routing.travel_time import TravelTimeProvider
from travel_agent.validation.report import Issue, IssueCode, Severity, ValidationReport

# Heuristic sản phẩm, chưa kiểm chứng; tinh chỉnh bằng phản hồi người dùng ở plan sau.
MAX_STOPS_PER_DAY: dict[Pace, int] = {Pace.RELAXED: 4, Pace.MODERATE: 6, Pace.PACKED: 8}
MEAL_WINDOWS: tuple[tuple[str, dt.time, dt.time], ...] = (
    ("bữa trưa", dt.time(11, 0), dt.time(13, 30)),
    ("bữa tối", dt.time(17, 30), dt.time(20, 0)),
)
MEAL_CATEGORIES = frozenset({Category.RESTAURANT})


def validate_itinerary(
    request: PlanRequest,
    itinerary: Itinerary,
    places: PlaceLookup,
    travel: TravelTimeProvider,
) -> ValidationReport:
    issues: list[Issue] = []
    _check_days(request, itinerary, issues)
    seen: set[str] = set()
    estimated_legs = 0
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
            else:
                _check_opening_hours(day.date, stop, place, d_idx, s_idx, issues)
            # Id lạ đã bị báo UNKNOWN_PLACE ở mỗi lần xuất hiện; không báo trùng thêm (phạt đôi).
            if place is not None and stop.place_id in seen:
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
        estimated_legs += _check_travel(request, day.stops, resolved, d_idx, travel, issues)
        _check_load(request, day.stops, d_idx, issues)
        _check_meals(request, day.stops, resolved, d_idx, issues)
    return ValidationReport(issues=issues, estimated_legs=estimated_legs)


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


def _check_opening_hours(
    day_date: dt.date,
    stop: PlannedStop,
    place: Place,
    d_idx: int,
    s_idx: int,
    issues: list[Issue],
) -> None:
    hours = parse_opening_hours(place.opening_hours_raw)
    if hours is None:
        issues.append(
            _issue(
                Severity.WARNING,
                IssueCode.OPENING_HOURS_UNKNOWN,
                f"Chưa có giờ mở cửa đã xác minh cho {place.name}",
                d_idx,
                s_idx,
                place.id,
            )
        )
        return
    if not hours.covers(day_date.weekday(), stop.arrive, stop.depart):
        issues.append(
            _issue(
                Severity.ERROR,
                IssueCode.CLOSED_DURING_VISIT,
                f"{place.name} không mở cửa trong {stop.arrive:%H:%M}-{stop.depart:%H:%M} "
                f"(giờ mở cửa theo {place.source}: {place.opening_hours_raw})",
                d_idx,
                s_idx,
                place.id,
            )
        )


def _minutes_between(start: dt.time, end: dt.time) -> float:
    anchor = dt.date(2000, 1, 1)
    delta = dt.datetime.combine(anchor, end) - dt.datetime.combine(anchor, start)
    return delta.total_seconds() / 60


def _check_travel(
    request: PlanRequest,
    stops: list[PlannedStop],
    resolved: list[Place | None],
    d_idx: int,
    travel: TravelTimeProvider,
    issues: list[Issue],
) -> int:
    estimated = 0
    for s_idx in range(1, len(stops)):
        prev, cur = stops[s_idx - 1], stops[s_idx]
        gap = _minutes_between(prev.depart, cur.arrive)
        if gap < 0:
            issues.append(
                _issue(
                    Severity.ERROR,
                    IssueCode.STOP_OVERLAP,
                    f"Đến lúc {cur.arrive:%H:%M} nhưng điểm trước rời lúc {prev.depart:%H:%M}",
                    d_idx,
                    s_idx,
                    cur.place_id,
                )
            )
            continue
        origin, destination = resolved[s_idx - 1], resolved[s_idx]
        if origin is None or destination is None:
            continue  # đã báo UNKNOWN_PLACE
        leg = travel.travel_leg(origin.coords, destination.coords, request.travel_mode)
        if leg.estimated:
            estimated += 1
        if gap < leg.minutes:
            label = "ước tính" if leg.estimated else "theo routing"
            issues.append(
                _issue(
                    Severity.ERROR,
                    IssueCode.TRAVEL_TIME_INSUFFICIENT,
                    f"Chỉ có {gap:.0f} phút để đi từ {origin.name}, cần khoảng "
                    f"{leg.minutes:.0f} phút ({label}, nguồn {leg.source})",
                    d_idx,
                    s_idx,
                    cur.place_id,
                )
            )
    return estimated


def _check_load(
    request: PlanRequest, stops: list[PlannedStop], d_idx: int, issues: list[Issue]
) -> None:
    limit = MAX_STOPS_PER_DAY[request.pace]
    if len(stops) > limit:
        issues.append(
            _issue(
                Severity.WARNING,
                IssueCode.OVERLOADED_DAY,
                f"Ngày {d_idx + 1} có {len(stops)} điểm, vượt mức {limit} "
                f"cho nhịp độ {request.pace.value}",
                d_idx,
            )
        )


def _check_meals(
    request: PlanRequest,
    stops: list[PlannedStop],
    resolved: list[Place | None],
    d_idx: int,
    issues: list[Issue],
) -> None:
    for meal, window_start, window_end in MEAL_WINDOWS:
        if request.day_start > window_start or request.day_end < window_end:
            continue  # khung ngày không bao trọn bữa này
        has_meal = any(
            place is not None
            and place.category in MEAL_CATEGORIES
            and stop.arrive < window_end
            and stop.depart > window_start
            for stop, place in zip(stops, resolved, strict=True)
        )
        if not has_meal:
            issues.append(
                _issue(
                    Severity.WARNING,
                    IssueCode.MISSING_MEAL,
                    f"Ngày {d_idx + 1} chưa có điểm ăn cho {meal} "
                    f"({window_start:%H:%M}-{window_end:%H:%M})",
                    d_idx,
                )
            )
