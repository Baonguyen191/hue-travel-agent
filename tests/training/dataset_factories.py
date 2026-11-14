"""Dataset nhỏ dựng từ pool giả để test build và check. Không phải dữ liệu thật của Huế."""

from collections.abc import Mapping, Sequence
from functools import cache

from tests.planning.factories import spread_pool
from travel_agent.domain.models import Place
from travel_agent.routing.travel_time import HaversineEstimator
from travel_agent.training.dataset import (
    BuildResult,
    CheckParams,
    DatasetParams,
    ShareBounds,
    TokenizerRef,
    build_samples,
)

TRAVEL = HaversineEstimator()
PARAMS = DatasetParams(
    name="test_sft",
    request_seed=99,
    target_samples=40,
    repair_share=0.25,
    max_requests=80,
)
CHECK = CheckParams(
    max_tokens=100_000,
    tokenizer=TokenizerRef(repo="test/none", revision="0"),
    distribution=ShareBounds(min_share=0.0, max_share=1.0),
)


@cache
def pool() -> tuple[Place, ...]:
    return tuple(spread_pool())


@cache
def small_build() -> BuildResult:
    return build_samples(PARAMS, pool(), set(), TRAVEL)


def char_counter(messages: Sequence[Mapping[str, str]]) -> int:
    """Counter giả cho test: đếm ký tự. Không phải số token thật."""
    return sum(len(message["content"]) for message in messages)
