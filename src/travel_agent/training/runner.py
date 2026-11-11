"""Chạy bộ eval qua một PlanGenerator. Cùng key thì cùng candidate ở mọi lần chạy."""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence

from travel_agent.domain.models import Place
from travel_agent.planning.candidates import select_candidates
from travel_agent.planning.prompt import build_messages
from travel_agent.routing.travel_time import TravelTimeProvider
from travel_agent.training.generator import PlanGenerator
from travel_agent.training.metrics import PlanOutcome, score_output
from travel_agent.training.requests import EvalEntry


def candidate_seed(key: str) -> int:
    return int(key[:8], 16)


def run_eval(
    entries: Sequence[EvalEntry],
    places: Sequence[Place],
    generator: PlanGenerator,
    travel: TravelTimeProvider,
    clock: Callable[[], float] = time.perf_counter,
) -> list[PlanOutcome]:
    """Không bắt `GenerationError`: lỗi hạ tầng làm hỏng lần eval, không tính cho model."""
    outcomes: list[PlanOutcome] = []
    for entry in entries:
        candidates = select_candidates(entry.request, places, candidate_seed(entry.key))
        messages = build_messages(entry.request, candidates)
        started = clock()
        raw = generator.generate(messages)
        latency_s = clock() - started
        outcomes.append(score_output(entry.key, entry.request, raw, candidates, travel, latency_s))
    return outcomes
