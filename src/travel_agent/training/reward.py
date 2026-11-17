"""Reward cho RL: chấm output thô của model theo spec 8.1, kết quả nằm trong [-1, 1].

Hàm thuần: cùng input luôn cho cùng reward. Dùng lại đúng validator của eval.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from pydantic import BaseModel

from travel_agent.data.place_repository import InMemoryPlaceRepository
from travel_agent.domain.models import Pace, Place, PlanRequest
from travel_agent.routing.travel_time import TravelTimeProvider
from travel_agent.training.parsing import parse_itinerary
from travel_agent.validation.report import IssueCode, Severity
from travel_agent.validation.validator import validate_itinerary

# Sàn số stop mỗi ngày theo nhịp độ: chặn việc lách bằng plan tối thiểu.
STOP_FLOOR: Mapping[Pace, int] = {Pace.RELAXED: 3, Pace.MODERATE: 4, Pace.PACKED: 6}

# Các trọng số dưới đây là giá trị khởi đầu theo spec, CHƯA được tinh chỉnh.
PARSE_FAILURE_REWARD = -1.0
START_REWARD = 1.0
UNKNOWN_PLACE_PENALTY = 0.5
OTHER_ERROR_PENALTY = 0.2
BELOW_STOP_FLOOR_PENALTY = 0.3
SOFT_WARNING_PENALTY = 0.05
BELOW_STOP_FLOOR_KEY = "below_stop_floor"
SOFT_WARNING_CODES = frozenset({IssueCode.OVERLOADED_DAY, IssueCode.MISSING_MEAL})


class RewardBreakdown(BaseModel):
    total: float
    parsed: bool
    valid: bool
    # Khóa là IssueCode.value hoặc "below_stop_floor"; giá trị là tổng phạt (số âm).
    # Chỉ giữ khóa có phạt khác 0.
    penalties: dict[str, float]


def score_reward(
    request: PlanRequest,
    raw: str,
    candidates: Sequence[Place],
    travel: TravelTimeProvider,
) -> RewardBreakdown:
    """Output không parse được thành Itinerary thì reward -1 và dừng, không chấm tiếp."""
    itinerary = parse_itinerary(raw)
    if itinerary is None:
        return RewardBreakdown(total=PARSE_FAILURE_REWARD, parsed=False, valid=False, penalties={})
    report = validate_itinerary(request, itinerary, InMemoryPlaceRepository(candidates), travel)

    penalties: dict[str, float] = {}

    def penalise(key: str, amount: float) -> None:
        penalties[key] = round(penalties.get(key, 0.0) - amount, 6)

    for issue in report.issues:
        if issue.code is IssueCode.UNKNOWN_PLACE:
            penalise(issue.code.value, UNKNOWN_PLACE_PENALTY)
        elif issue.severity is Severity.ERROR:
            penalise(issue.code.value, OTHER_ERROR_PENALTY)
        elif issue.code in SOFT_WARNING_CODES:
            penalise(issue.code.value, SOFT_WARNING_PENALTY)
        # Cảnh báo còn lại (opening_hours_unknown...) không bị phạt: giới hạn của dữ liệu.

    floor = STOP_FLOOR[request.pace]
    for day in itinerary.days:
        if len(day.stops) < floor:
            penalise(BELOW_STOP_FLOOR_KEY, BELOW_STOP_FLOOR_PENALTY)

    total = START_REWARD + sum(penalties.values())
    total = round(min(1.0, max(-1.0, total)), 6)
    return RewardBreakdown(
        total=total,
        parsed=True,
        valid=report.is_valid,
        penalties={key: value for key, value in penalties.items() if value != 0},
    )


def reward(
    request: PlanRequest,
    raw: str,
    candidates: Sequence[Place],
    travel: TravelTimeProvider,
) -> float:
    return score_reward(request, raw, candidates, travel).total
