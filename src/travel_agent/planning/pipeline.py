"""Lập lịch một chuyến đi: chọn candidate, sinh, xếp giờ, kiểm, rồi sửa khi còn lỗi ERROR.

Hàm thuần ngoài `generator`. Dùng đúng các hàm mà eval dùng (`candidate_seed`, `request_key`,
`build_messages`, `itinerary_format_schema`, `parse_itinerary`) để plan và eval so được với nhau.
`GenerationError` không bị bắt ở đây: đó là lỗi hạ tầng, không phải lỗi của model.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel

from travel_agent.data.place_repository import InMemoryPlaceRepository
from travel_agent.domain.models import Itinerary, Place, PlanRequest
from travel_agent.planning.candidates import select_candidates
from travel_agent.planning.prompt import build_messages
from travel_agent.planning.schedule import DroppedStop
from travel_agent.planning.schedule import retime as retime_itinerary
from travel_agent.routing.travel_time import TravelTimeProvider
from travel_agent.training.generator import PlanGenerator, itinerary_format_schema
from travel_agent.training.parsing import parse_itinerary
from travel_agent.training.requests import request_key
from travel_agent.training.runner import candidate_seed
from travel_agent.validation.report import ValidationReport
from travel_agent.validation.validator import validate_itinerary


class PlanAttempt(BaseModel):
    kind: Literal["generate", "repair"]
    raw: str
    parsed: bool
    # Số lỗi ERROR của validator. Bằng 0 khi không parse được (lúc đó validator không chạy).
    error_count: int
    latency_s: float


class PlanResult(BaseModel):
    itinerary: (
        Itinerary | None
    )  # lịch đã xếp giờ của lượt tốt nhất; None nếu không lượt nào parse được
    report: ValidationReport | None
    valid: bool  # không còn lỗi ERROR nào
    attempts: list[PlanAttempt]
    dropped: list[DroppedStop]  # điểm bị bỏ khi xếp giờ, của lượt tốt nhất
    candidates_ids: list[str]


@dataclass(frozen=True)
class _Trial:
    itinerary: Itinerary | None  # đã xếp giờ nếu retime bật
    report: ValidationReport | None  # None khi output không parse được
    dropped: list[DroppedStop]


def _is_valid(trial: _Trial) -> bool:
    return trial.report is not None and trial.report.is_valid


def _rank(trial: _Trial) -> tuple[bool, int]:
    """Lượt parse được luôn hơn lượt không parse; trong đó ít ERROR hơn thì hơn."""
    if trial.report is None:
        return (False, 0)
    return (True, -len(trial.report.errors()))


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
) -> PlanResult:
    """Sinh lịch cho `request`, tối đa `1 + max_repairs` lượt gọi model.

    Lượt đầu dùng prompt sinh như eval. Lượt sau: nếu output trước parse được thì dùng prompt sửa
    (kèm lịch đã xếp giờ và các lỗi ERROR); nếu không parse được thì sinh lại từ đầu. Dừng khi
    hết ERROR hoặc hết lượt. Trả về lượt có ít ERROR nhất; hòa thì lấy lượt sau.
    `seed` mặc định là `candidate_seed(request_key(request))`, đúng như eval.
    """
    if max_repairs < 0:
        raise ValueError("max_repairs không được âm")
    candidate_rng = candidate_seed(request_key(request)) if seed is None else seed
    candidates = select_candidates(request, places, candidate_rng)
    # Giống metrics.score_output: chỉ candidate mới là địa điểm hợp lệ.
    lookup = InMemoryPlaceRepository(candidates)
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
            trial = _Trial(itinerary=itinerary, report=report, dropped=dropped)
        attempts.append(
            PlanAttempt(
                kind=kind,
                raw=generation.content,
                parsed=trial.report is not None,
                error_count=len(trial.report.errors()) if trial.report is not None else 0,
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
                request, candidates, broken=trial.itinerary, issues=trial.report.issues
            )
            trial = attempt("repair", messages)
        else:
            trial = attempt("generate", build_messages(request, candidates))
        if _rank(trial) >= _rank(best):
            best = trial

    return PlanResult(
        itinerary=best.itinerary,
        report=best.report,
        valid=_is_valid(best),
        attempts=attempts,
        dropped=best.dropped,
        candidates_ids=[place.id for place in candidates],
    )
