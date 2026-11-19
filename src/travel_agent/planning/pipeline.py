"""Lập lịch một chuyến đi: chọn candidate, sinh, xếp giờ, kiểm, rồi sửa khi còn lỗi ERROR.

Hàm thuần ngoài `generator`. Dùng đúng các hàm mà eval dùng (`candidate_seed`, `request_key`,
`build_messages`, `itinerary_format_schema`, `parse_itinerary`) để plan và eval so được với nhau.
`GenerationError` không bị bắt ở đây: đó là lỗi hạ tầng, không phải lỗi của model.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Collection, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, Field

from travel_agent.data.place_repository import InMemoryPlaceRepository
from travel_agent.domain.models import (
    Category,
    Itinerary,
    Place,
    PlannedDay,
    PlannedStop,
    PlanRequest,
)
from travel_agent.planning.candidates import select_candidates
from travel_agent.planning.fill import AddedStop
from travel_agent.planning.fill import fill_gaps as fill_schedule_gaps
from travel_agent.planning.hours import minute_floor, time_of
from travel_agent.planning.prompt import build_messages
from travel_agent.planning.schedule import DroppedStop
from travel_agent.planning.schedule import retime as retime_itinerary
from travel_agent.planning.solver import VISIT_MINUTES
from travel_agent.routing.travel_time import TravelTimeProvider
from travel_agent.training.generator import PlanGenerator, itinerary_format_schema
from travel_agent.training.parsing import parse_itinerary
from travel_agent.training.requests import request_key
from travel_agent.training.runner import candidate_seed
from travel_agent.validation.report import Issue, IssueCode, Severity, ValidationReport
from travel_agent.validation.validator import validate_itinerary


class PlanAttempt(BaseModel):
    kind: Literal["generate", "repair"]
    raw: str
    parsed: bool
    # Số lỗi ERROR của validator cộng số điểm bắt buộc vắng (coi như ERROR). Bằng 0 khi không
    # parse được (lúc đó validator không chạy).
    error_count: int
    latency_s: float


class PlanResult(BaseModel):
    itinerary: (
        Itinerary | None
    )  # lịch đã xếp giờ của lượt tốt nhất; None nếu không lượt nào parse được
    report: ValidationReport | None  # chỉ của validator, không chứa lỗi thiếu điểm bắt buộc
    valid: bool  # không còn lỗi ERROR của validator nào
    attempts: list[PlanAttempt]
    dropped: list[DroppedStop]  # điểm bị bỏ khi xếp giờ, của lượt tốt nhất (và lần chèn)
    candidates_ids: list[str]
    # Id bắt buộc (must_include) không có trong lịch cuối, kể cả id không có trong DB hoặc bị loại.
    missing_must: list[str] = Field(default_factory=list)
    # Id bắt buộc vắng sau sửa model, được chèn bằng code và vẫn còn trong lịch cuối.
    inserted_must: list[str] = Field(default_factory=list)
    # Điểm thêm vào để lấp khoảng trống (bữa ăn, quãng trống); rỗng khi `fill_gaps` tắt.
    added: list[AddedStop] = Field(default_factory=list)


@dataclass(frozen=True)
class _Trial:
    itinerary: Itinerary | None  # đã xếp giờ nếu retime bật
    report: ValidationReport | None  # None khi output không parse được
    dropped: list[DroppedStop]
    # Điểm bắt buộc (có trong candidate) vắng khỏi lịch; coi như ERROR khi lặp và khi chọn lượt.
    missing: list[Issue] = field(default_factory=list)


def _is_valid(trial: _Trial) -> bool:
    """Dừng vòng lặp: không ERROR của validator và không thiếu điểm bắt buộc nào."""
    return trial.report is not None and trial.report.is_valid and not trial.missing


def _error_count(trial: _Trial) -> int:
    if trial.report is None:
        return 0
    return len(trial.report.errors()) + len(trial.missing)


def _rank(trial: _Trial) -> tuple[bool, int]:
    """Lượt parse được luôn hơn lượt không parse; trong đó ít ERROR hơn thì hơn."""
    if trial.report is None:
        return (False, 0)
    return (True, -_error_count(trial))


def _planned_ids(itinerary: Itinerary | None) -> set[str]:
    if itinerary is None:
        return set()
    return {stop.place_id for day in itinerary.days for stop in day.stops}


def _missing_issues(
    itinerary: Itinerary, required: Sequence[str], names: dict[str, str]
) -> list[Issue]:
    """Lỗi tổng hợp ERROR cho điểm bắt buộc vắng. Không phải do validator sinh."""
    planned = _planned_ids(itinerary)
    return [
        Issue(
            code=IssueCode.MISSING_REQUIRED_PLACE,
            severity=Severity.ERROR,
            message=f"Thiếu điểm bắt buộc: {names.get(place_id, place_id)} ({place_id})",
            place_id=place_id,
        )
        for place_id in required
        if place_id not in planned
    ]


def _leg_minutes(
    origin: Place, destination: Place, request: PlanRequest, travel: TravelTimeProvider
) -> float:
    return travel.travel_leg(origin.coords, destination.coords, request.travel_mode).minutes


def _best_position(
    request: PlanRequest,
    stops: Sequence[PlannedStop],
    place: Place,
    lookup: InMemoryPlaceRepository,
    travel: TravelTimeProvider,
) -> int:
    """Vị trí chèn làm tăng ít thời gian đi nhất; hòa thì vị trí sớm hơn.

    Điểm lạ (không có trong `lookup`) không có tọa độ nên không tính chặng nào của nó.
    """
    best_pos, best_cost = 0, float("inf")
    for pos in range(len(stops) + 1):
        before = lookup.get(stops[pos - 1].place_id) if pos > 0 else None
        after = lookup.get(stops[pos].place_id) if pos < len(stops) else None
        cost = 0.0
        if before is not None:
            cost += _leg_minutes(before, place, request, travel)
        if after is not None:
            cost += _leg_minutes(place, after, request, travel)
        if before is not None and after is not None:
            cost -= _leg_minutes(before, after, request, travel)
        if cost < best_cost:
            best_pos, best_cost = pos, cost
    return best_pos


def _insert_places(
    request: PlanRequest,
    itinerary: Itinerary,
    places: Sequence[Place],
    lookup: InMemoryPlaceRepository,
    travel: TravelTimeProvider,
) -> Itinerary:
    """Chèn từng điểm vào ngày ít điểm nhất (hòa thì ngày sớm hơn), tại vị trí thêm ít đi lại nhất.

    Giờ tạm là day_start với thời lượng VISIT_MINUTES[loại]; retime đặt giờ thật sau đó.
    """
    if not itinerary.days:
        return itinerary
    days: list[list[PlannedStop]] = [list(day.stops) for day in itinerary.days]
    start = minute_floor(request.day_start)
    for place in places:
        day_index = min(range(len(days)), key=lambda i: len(days[i]))
        stops = days[day_index]
        pos = _best_position(request, stops, place, lookup, travel)
        placeholder = PlannedStop(
            place_id=place.id,
            arrive=request.day_start,
            depart=time_of(start + VISIT_MINUTES[place.category]),
        )
        stops.insert(pos, placeholder)
    return Itinerary(
        days=[
            PlannedDay(date=day.date, stops=stops)
            for day, stops in zip(itinerary.days, days, strict=True)
        ]
    )


def _insert_missing(
    request: PlanRequest,
    itinerary: Itinerary,
    dropped: list[DroppedStop],
    still_missing: list[str],
    candidate_by_id: dict[str, Place],
    lookup: InMemoryPlaceRepository,
    travel: TravelTimeProvider,
) -> tuple[Itinerary, ValidationReport, list[DroppedStop], list[str]]:
    """Chèn điểm bắt buộc còn vắng rồi xếp lại giờ và kiểm lại."""
    grown = _insert_places(
        request, itinerary, [candidate_by_id[pid] for pid in still_missing], lookup, travel
    )
    result = retime_itinerary(request, grown, lookup, travel)
    itinerary = result.itinerary
    # Điểm đã bỏ ở lượt xếp giờ trước có thể được chèn lại rồi bị bỏ tiếp: chỉ ghi một lần.
    seen_drops = {(drop.day_index, drop.place_id) for drop in dropped}
    dropped += [
        drop for drop in result.dropped if (drop.day_index, drop.place_id) not in seen_drops
    ]
    report = validate_itinerary(request, itinerary, lookup, travel)
    planned = _planned_ids(itinerary)
    inserted = [pid for pid in still_missing if pid in planned]
    return itinerary, report, dropped, inserted


def _fill_step(
    request: PlanRequest,
    itinerary: Itinerary,
    report: ValidationReport | None,
    candidates: Sequence[Place],
    lookup: InMemoryPlaceRepository,
    travel: TravelTimeProvider,
) -> tuple[Itinerary, ValidationReport | None, list[AddedStop]]:
    """Lấp khoảng trống bằng điểm thêm; nếu có điểm thêm thì kiểm lại lịch."""
    filled, added = fill_schedule_gaps(request, itinerary, candidates, travel)
    if added:
        return filled, validate_itinerary(request, filled, lookup, travel), added
    return itinerary, report, added


def plan_trip(
    request: PlanRequest,
    places: Sequence[Place],
    generator: PlanGenerator,
    travel: TravelTimeProvider,
    *,
    seed: int | None = None,
    retime: bool = True,
    max_repairs: int = 2,
    clock: Callable[[], float] = time.perf_counter,
    must_include: Sequence[str] = (),
    exclude_ids: Collection[str] = (),
    exclude_categories: Collection[Category] = (),
    landmarks: int = 0,
    fill_gaps: bool = False,
) -> PlanResult:
    """Sinh lịch cho `request`, tối đa `1 + max_repairs` lượt gọi model.

    Lượt đầu dùng prompt sinh như eval. Lượt sau: nếu output trước parse được thì dùng prompt sửa
    (kèm lịch đã xếp giờ, các lỗi ERROR và các điểm bắt buộc còn vắng); nếu không parse được thì
    sinh lại từ đầu. Dừng khi hết ERROR và không thiếu điểm bắt buộc, hoặc hết lượt. Trả về lượt
    có ít lỗi nhất (lỗi thiếu điểm bắt buộc được tính như ERROR); hòa thì lấy lượt sau.

    Điểm bắt buộc có trong candidate (có trong DB, không bị loại) mà vẫn vắng sau mọi lượt sửa
    thì được chèn bằng code (`_insert_places`), rồi xếp lại giờ và kiểm lại. Việc chèn chỉ làm khi
    `retime` bật, vì giờ chèn cần xếp lại. `inserted_must` là các điểm chèn xong còn trong lịch;
    `missing_must` là các id bắt buộc còn vắng ở lịch cuối (gồm id không có trong DB và id bị loại).
    `PlanResult.valid` chỉ xét ERROR của validator; thiếu điểm bắt buộc nằm ở `missing_must`.

    `seed` mặc định là `candidate_seed(request_key(request))`, đúng như eval.
    `must_include`, `exclude_ids`, `exclude_categories` chuyển cho `select_candidates`; không truyền
    thì kết quả như trước. Loại trừ thắng bắt buộc: điểm vừa bắt buộc vừa bị loại nằm trong
    `missing_must` và không được chèn. `landmarks` chuyển cho `select_candidates` (0 là tắt).

    `fill_gaps` bật bước lấp khoảng trống (xem planning/fill.py) sau lần xếp giờ cuối, rồi kiểm lại
    lịch. Bước này chỉ chạy khi `retime` bật, vì nó xếp giờ lại; `added` liệt kê điểm đã thêm.
    """
    if max_repairs < 0:
        raise ValueError("max_repairs không được âm")
    candidate_rng = candidate_seed(request_key(request)) if seed is None else seed
    candidates = select_candidates(
        request,
        places,
        candidate_rng,
        must_include=must_include,
        exclude_ids=exclude_ids,
        exclude_categories=exclude_categories,
        landmarks=landmarks,
    )
    # Giống metrics.score_output: chỉ candidate mới là địa điểm hợp lệ.
    lookup = InMemoryPlaceRepository(candidates)
    candidate_by_id = {place.id: place for place in candidates}
    names = {place.id: place.name for place in places}
    # Điểm bắt buộc mà model có thể đặt được: đúng những id có trong candidate.
    required = [place_id for place_id in dict.fromkeys(must_include) if place_id in candidate_by_id]
    schema: dict[str, Any] = itinerary_format_schema(request.num_days)
    attempts: list[PlanAttempt] = []

    def attempt(kind: Literal["generate", "repair"], messages: list[dict[str, str]]) -> _Trial:
        started = clock()
        generation = generator.generate(messages, format_schema=schema)
        latency_s = clock() - started
        itinerary = parse_itinerary(generation.content)
        trial = _Trial(itinerary=None, report=None, dropped=[])
        if itinerary is not None:
            dropped: list[DroppedStop] = []
            if retime:
                result = retime_itinerary(request, itinerary, lookup, travel)
                itinerary, dropped = result.itinerary, result.dropped
            report = validate_itinerary(request, itinerary, lookup, travel)
            missing = _missing_issues(itinerary, required, names)
            trial = _Trial(itinerary=itinerary, report=report, dropped=dropped, missing=missing)
        attempts.append(
            PlanAttempt(
                kind=kind,
                raw=generation.content,
                parsed=trial.report is not None,
                error_count=_error_count(trial),
                latency_s=latency_s,
            )
        )
        return trial

    trial = attempt("generate", build_messages(request, candidates))
    best = trial
    repairs = 0
    while not _is_valid(trial) and repairs < max_repairs:
        repairs += 1
        if trial.itinerary is not None and trial.report is not None:
            messages = build_messages(
                request,
                candidates,
                broken=trial.itinerary,
                issues=[*trial.report.issues, *trial.missing],
            )
            trial = attempt("repair", messages)
        else:
            trial = attempt("generate", build_messages(request, candidates))
        if _rank(trial) >= _rank(best):
            best = trial

    itinerary, report = best.itinerary, best.report
    dropped = list(best.dropped)
    inserted: list[str] = []
    still_missing = [issue.place_id for issue in best.missing if issue.place_id is not None]
    if retime and itinerary is not None and still_missing:
        itinerary, report, dropped, inserted = _insert_missing(
            request, itinerary, dropped, still_missing, candidate_by_id, lookup, travel
        )

    added: list[AddedStop] = []
    if fill_gaps and retime and itinerary is not None:
        itinerary, report, added = _fill_step(
            request, itinerary, report, candidates, lookup, travel
        )

    planned = _planned_ids(itinerary)
    missing = [place_id for place_id in dict.fromkeys(must_include) if place_id not in planned]
    return PlanResult(
        itinerary=itinerary,
        report=report,
        valid=report is not None and report.is_valid,
        attempts=attempts,
        dropped=dropped,
        candidates_ids=[place.id for place in candidates],
        missing_must=missing,
        inserted_must=inserted,
        added=added,
    )
