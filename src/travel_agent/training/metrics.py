"""Chấm một output và tổng hợp metric cho cả bộ eval."""

from __future__ import annotations

import statistics
from collections import Counter
from collections.abc import Sequence

from pydantic import BaseModel, Field

from travel_agent.data.place_repository import InMemoryPlaceRepository
from travel_agent.domain.models import Place, PlanRequest
from travel_agent.routing.travel_time import TravelTimeProvider
from travel_agent.training.parsing import parse_itinerary
from travel_agent.validation.report import IssueCode
from travel_agent.validation.validator import validate_itinerary


class PlanOutcome(BaseModel):
    key: str
    parsed: bool
    valid: bool
    raw: str = ""  # output thô của model, giữ để xem lại lỗi và làm dữ liệu sau này
    day_count: int = 0
    stop_count: int = 0
    unknown_place_count: int = 0
    place_ids: list[str] = Field(default_factory=list)
    stops_per_day: list[int] = Field(default_factory=list)
    issue_codes: list[str] = Field(default_factory=list)
    issues: list[dict[str, str | int | None]] = Field(default_factory=list)
    latency_s: float = 0.0
    done_reason: str | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


class EvalSummary(BaseModel):
    n: int
    first_pass_valid_rate: float
    parse_error_rate: float
    unknown_place_rate: float
    avg_stops_per_day: float
    distinct_place_count: int
    latency_p50_s: float
    issue_code_distribution: dict[str, int]


def score_output(
    key: str,
    request: PlanRequest,
    raw: str,
    candidates: Sequence[Place],
    travel: TravelTimeProvider,
    latency_s: float,
    *,
    done_reason: str | None = None,
    prompt_tokens: int | None = None,
    completion_tokens: int | None = None,
) -> PlanOutcome:
    """Chỉ candidate mới là địa điểm hợp lệ: id ngoài danh sách bị báo `unknown_place`."""
    meta = {
        "latency_s": latency_s,
        "done_reason": done_reason,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
    }
    itinerary = parse_itinerary(raw)
    if itinerary is None:
        return PlanOutcome(key=key, parsed=False, valid=False, raw=raw, **meta)
    report = validate_itinerary(request, itinerary, InMemoryPlaceRepository(candidates), travel)
    codes = [issue.code.value for issue in report.issues]
    place_ids = [stop.place_id for day in itinerary.days for stop in day.stops]
    return PlanOutcome(
        key=key,
        parsed=True,
        valid=report.is_valid,
        raw=raw,
        day_count=len(itinerary.days),
        stop_count=len(place_ids),
        unknown_place_count=codes.count(IssueCode.UNKNOWN_PLACE.value),
        place_ids=place_ids,
        stops_per_day=[len(day.stops) for day in itinerary.days],
        issue_codes=codes,
        issues=[issue.model_dump(mode="json") for issue in report.issues],
        **meta,
    )


def summarize(outcomes: Sequence[PlanOutcome]) -> EvalSummary:
    if not outcomes:
        raise ValueError("không có kết quả nào để tổng hợp")
    n = len(outcomes)
    stops = sum(outcome.stop_count for outcome in outcomes)
    days = sum(outcome.day_count for outcome in outcomes)
    unknown = sum(outcome.unknown_place_count for outcome in outcomes)
    codes = Counter(code for outcome in outcomes for code in outcome.issue_codes)
    return EvalSummary(
        n=n,
        first_pass_valid_rate=sum(outcome.valid for outcome in outcomes) / n,
        parse_error_rate=sum(not outcome.parsed for outcome in outcomes) / n,
        unknown_place_rate=unknown / stops if stops else 0.0,
        avg_stops_per_day=stops / days if days else 0.0,
        distinct_place_count=len({pid for outcome in outcomes for pid in outcome.place_ids}),
        latency_p50_s=statistics.median(outcome.latency_s for outcome in outcomes),
        issue_code_distribution=dict(sorted(codes.items())),
    )


def regressions(current: EvalSummary, previous: EvalSummary) -> list[str]:
    """Cổng thăng hạng: trả danh sách lý do khi model mới kém mốc trước. Rỗng là qua cổng."""
    problems: list[str] = []
    if current.first_pass_valid_rate < previous.first_pass_valid_rate:
        problems.append(
            f"first_pass_valid_rate giảm: {current.first_pass_valid_rate:.3f} "
            f"< {previous.first_pass_valid_rate:.3f}"
        )
    return problems
