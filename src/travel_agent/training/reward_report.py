"""Kiểm reward trên output dev đã có, trước khi dùng reward để train RL.

Dựng lại candidate đúng như `runner.run_eval`, rồi chấm output thô của từng request bằng
`score_reward`. Hàm thuần: không đọc đĩa (việc đọc file nằm ở `commands.py`).
"""

from __future__ import annotations

import statistics
from collections.abc import Mapping, Sequence
from pathlib import Path

from pydantic import BaseModel

from travel_agent.domain.models import Place
from travel_agent.planning.candidates import select_candidates
from travel_agent.routing.travel_time import TravelTimeProvider
from travel_agent.training.metrics import PlanOutcome
from travel_agent.training.requests import EvalEntry
from travel_agent.training.reward import (
    BELOW_STOP_FLOOR_KEY,
    BELOW_STOP_FLOOR_PENALTY,
    RewardBreakdown,
    score_reward,
)
from travel_agent.training.runner import candidate_seed


class ScoredOutcome(BaseModel):
    key: str
    valid: bool  # valid của outcome gốc (validator eval chạy lúc đó)
    breakdown: RewardBreakdown


class RewardSummary(BaseModel):
    n: int
    mean_reward: float
    mean_reward_valid: float | None  # None khi không có plan hợp lệ nào
    mean_reward_invalid: float | None  # None khi không có plan lỗi nào
    n_valid: int
    n_invalid: int
    # Số dòng mà valid trong breakdown khác valid trong outcome. Phải bằng 0.
    valid_mismatch: int
    penalty_totals: dict[str, float]
    below_floor_days: int


def load_outcomes(path: Path) -> list[PlanOutcome]:
    lines = path.read_text(encoding="utf-8").splitlines()
    return [PlanOutcome.model_validate_json(line) for line in lines if line.strip()]


def score_outcomes(
    entries: Sequence[EvalEntry],
    outcomes: Sequence[PlanOutcome],
    places: Sequence[Place],
    travel: TravelTimeProvider,
) -> list[ScoredOutcome]:
    """Mỗi outcome phải có entry cùng key trong bộ eval; thiếu hoặc trùng thì báo lỗi."""
    by_key = {entry.key: entry for entry in entries}
    seen: set[str] = set()
    scored: list[ScoredOutcome] = []
    for outcome in outcomes:
        entry = by_key.get(outcome.key)
        if entry is None:
            raise ValueError(f"outcome {outcome.key} không có trong bộ eval")
        if outcome.key in seen:
            raise ValueError(f"outcome {outcome.key} xuất hiện nhiều lần")
        seen.add(outcome.key)
        candidates = select_candidates(entry.request, places, candidate_seed(entry.key))
        breakdown = score_reward(entry.request, outcome.raw, candidates, travel)
        scored.append(ScoredOutcome(key=outcome.key, valid=outcome.valid, breakdown=breakdown))
    return scored


def _mean(values: Sequence[float]) -> float | None:
    return statistics.fmean(values) if values else None


def summarize_rewards(scored: Sequence[ScoredOutcome]) -> RewardSummary:
    if not scored:
        raise ValueError("không có kết quả nào để tổng hợp")
    totals = [item.breakdown.total for item in scored]
    valid_totals = [item.breakdown.total for item in scored if item.valid]
    invalid_totals = [item.breakdown.total for item in scored if not item.valid]

    penalty_totals: dict[str, float] = {}
    for item in scored:
        for key, value in item.breakdown.penalties.items():
            penalty_totals[key] = round(penalty_totals.get(key, 0.0) + value, 6)

    # Mỗi ngày dưới sàn bị phạt đúng BELOW_STOP_FLOOR_PENALTY, nên đếm ngược từ tổng phạt.
    below_floor_days = sum(
        round(-item.breakdown.penalties.get(BELOW_STOP_FLOOR_KEY, 0.0) / BELOW_STOP_FLOOR_PENALTY)
        for item in scored
    )
    return RewardSummary(
        n=len(scored),
        mean_reward=statistics.fmean(totals),
        mean_reward_valid=_mean(valid_totals),
        mean_reward_invalid=_mean(invalid_totals),
        n_valid=len(valid_totals),
        n_invalid=len(invalid_totals),
        valid_mismatch=sum(item.breakdown.valid != item.valid for item in scored),
        penalty_totals=dict(sorted(penalty_totals.items())),
        below_floor_days=below_floor_days,
    )


def check_report(summaries: Mapping[str, RewardSummary], better: str, worse: str) -> list[str]:
    """Trả lý do không qua; rỗng là qua. `better` phải có reward trung bình cao hơn `worse`."""
    missing = [name for name in (better, worse) if name not in summaries]
    if missing:
        return [f"thiếu kết quả của {', '.join(missing)}"]

    failures: list[str] = []
    high, low = summaries[better], summaries[worse]
    if high.mean_reward <= low.mean_reward:
        failures.append(
            f"reward trung bình {better} ({high.mean_reward:.3f}) "
            f"không cao hơn {worse} ({low.mean_reward:.3f})"
        )
    for name, summary in summaries.items():
        if (
            summary.mean_reward_valid is not None
            and summary.mean_reward_invalid is not None
            and summary.mean_reward_valid <= summary.mean_reward_invalid
        ):
            failures.append(
                f"{name}: trung bình plan hợp lệ ({summary.mean_reward_valid:.3f}) "
                f"không cao hơn plan lỗi ({summary.mean_reward_invalid:.3f})"
            )
        if summary.valid_mismatch > 0:
            failures.append(
                f"{name}: {summary.valid_mismatch} dòng có valid trong breakdown "
                "khác valid trong outcome"
            )
    return failures
