"""Test logic thuần của best-of-N: seed, chia vòng, chọn mẫu, dựng dataset, thống kê."""

from __future__ import annotations

import json

import pytest

from tests.training.factories import PLACES, REQUEST, VALID_RAW
from travel_agent.planning.prompt import build_messages, format_itinerary
from travel_agent.training.best_of_n import (
    ScoredSample,
    round_prompts,
    round_stats,
    sample_seed,
    select_best,
    to_dataset_sample,
)
from travel_agent.training.dataset import SampleKind
from travel_agent.training.parsing import parse_itinerary
from travel_agent.training.reward import RewardBreakdown
from travel_agent.training.rl_data import RlPrompt

KEY = "a" * 16
THRESHOLD = 0.9


def _reward(
    total: float,
    *,
    parsed: bool = True,
    valid: bool = True,
    penalties: dict[str, float] | None = None,
) -> RewardBreakdown:
    return RewardBreakdown(total=total, parsed=parsed, valid=valid, penalties=penalties or {})


def _sample(
    index: int,
    total: float,
    *,
    key: str = KEY,
    latency_s: float = 1.0,
    parsed: bool = True,
    valid: bool = True,
    penalties: dict[str, float] | None = None,
) -> ScoredSample:
    return ScoredSample(
        key=key,
        index=index,
        seed=index,
        raw=f"raw {index}",
        reward=_reward(total, parsed=parsed, valid=valid, penalties=penalties),
        latency_s=latency_s,
    )


def _prompt(key: str) -> RlPrompt:
    return RlPrompt(
        key=key,
        request=REQUEST,
        candidates=list(PLACES),
        messages=build_messages(REQUEST, PLACES),
    )


# --- sample_seed -------------------------------------------------------------------------------


def test_sample_seed_is_deterministic() -> None:
    assert sample_seed(4242, KEY, 1, 0) == sample_seed(4242, KEY, 1, 0)


def test_sample_seed_differs_per_sample_round_key_and_base() -> None:
    seeds = {
        sample_seed(4242, KEY, 1, 0),
        sample_seed(4242, KEY, 1, 1),
        sample_seed(4242, KEY, 2, 0),
        sample_seed(4242, "b" * 16, 1, 0),
        sample_seed(4243, KEY, 1, 0),
    }
    assert len(seeds) == 5


def test_sample_seed_fits_in_ollama_seed_range() -> None:
    for index in range(20):
        assert 0 <= sample_seed(4242, KEY, 1, index) < 2**32


# --- round_prompts -----------------------------------------------------------------------------


def test_round_prompts_are_consecutive_and_non_overlapping() -> None:
    prompts = [_prompt(f"k{i}") for i in range(10)]

    first = round_prompts(prompts, 1, 3)
    second = round_prompts(prompts, 2, 3)
    third = round_prompts(prompts, 3, 3)

    assert [p.key for p in first] == ["k0", "k1", "k2"]
    assert [p.key for p in second] == ["k3", "k4", "k5"]
    assert [p.key for p in third] == ["k6", "k7", "k8"]


def test_round_prompts_raises_when_not_enough_prompts() -> None:
    prompts = [_prompt(f"k{i}") for i in range(5)]
    with pytest.raises(ValueError):
        round_prompts(prompts, 2, 3)  # cần prompt 4..6, chỉ có 5


@pytest.mark.parametrize("round_index, per_round", [(0, 3), (1, 0)])
def test_round_prompts_rejects_bad_arguments(round_index: int, per_round: int) -> None:
    with pytest.raises(ValueError):
        round_prompts([_prompt("k0")], round_index, per_round)


# --- select_best -------------------------------------------------------------------------------


def test_select_best_takes_highest_reward() -> None:
    samples = [_sample(0, 0.95), _sample(1, 1.0), _sample(2, 0.92)]
    best = select_best(samples, THRESHOLD)
    assert best is not None
    assert best.index == 1


def test_select_best_ties_go_to_earliest_sample() -> None:
    samples = [_sample(2, 1.0), _sample(0, 1.0), _sample(1, 1.0)]
    best = select_best(samples, THRESHOLD)
    assert best is not None
    assert best.index == 0


def test_select_best_keeps_sample_exactly_at_threshold() -> None:
    best = select_best([_sample(0, THRESHOLD)], THRESHOLD)
    assert best is not None
    assert best.reward.total == THRESHOLD


def test_select_best_drops_group_below_threshold() -> None:
    samples = [_sample(0, 0.89), _sample(1, 0.5)]
    assert select_best(samples, THRESHOLD) is None


def test_select_best_empty_group_is_none() -> None:
    assert select_best([], THRESHOLD) is None


def test_select_best_never_keeps_parse_failure() -> None:
    failed = _sample(0, -1.0, parsed=False, valid=False)
    assert select_best([failed], 0.0) is None


# --- to_dataset_sample -------------------------------------------------------------------------


def test_to_dataset_sample_matches_sft_format() -> None:
    prompt = _prompt(KEY)
    sample = to_dataset_sample(prompt, VALID_RAW)

    itinerary = parse_itinerary(VALID_RAW)
    assert itinerary is not None
    assert sample.key == KEY
    assert sample.kind is SampleKind.GENERATE
    assert sample.corruption is None
    assert sample.broken is None
    assert sample.request == REQUEST
    assert sample.candidate_ids == [place.id for place in PLACES]
    assert sample.messages == [
        *prompt.messages,
        {"role": "assistant", "content": format_itinerary(itinerary)},
    ]


def test_to_dataset_sample_normalises_answer_like_solver() -> None:
    # Pretty-print và khoảng trắng thừa trong output model: đáp án lưu phải là dạng gọn của solver.
    pretty = json.dumps(json.loads(VALID_RAW), indent=4, ensure_ascii=True)
    sample = to_dataset_sample(_prompt(KEY), pretty)

    answer = sample.messages[-1]["content"]
    assert answer == format_itinerary(parse_itinerary(VALID_RAW))  # type: ignore[arg-type]
    assert answer != pretty.strip()
    assert sample.messages[-1]["role"] == "assistant"


def test_to_dataset_sample_rejects_unparseable_raw() -> None:
    with pytest.raises(ValueError):
        to_dataset_sample(_prompt(KEY), "không phải JSON")


# --- round_stats -------------------------------------------------------------------------------


def test_round_stats_on_empty_input_is_all_zero() -> None:
    stats = round_stats({}, THRESHOLD)
    assert stats.requests == 0
    assert stats.samples == 0
    assert stats.kept == 0
    assert stats.keep_rate == 0.0
    assert stats.mean_reward == 0.0
    assert stats.mean_best_reward == 0.0
    assert stats.mean_latency_s == 0.0
    assert stats.issue_totals == {}


def test_round_stats_counts_kept_and_rates() -> None:
    groups = {
        "k1": [_sample(0, 1.0, key="k1"), _sample(1, 0.5, key="k1")],
        "k2": [_sample(0, 0.3, key="k2")],
        "k3": [_sample(0, 0.95, key="k3", latency_s=3.0)],
    }
    stats = round_stats(groups, THRESHOLD)

    assert stats.requests == 3
    assert stats.samples == 4
    assert stats.kept == 2
    assert stats.keep_rate == pytest.approx(2 / 3)
    assert stats.mean_reward == pytest.approx((1.0 + 0.5 + 0.3 + 0.95) / 4)
    assert stats.mean_best_reward == pytest.approx((1.0 + 0.3 + 0.95) / 3)
    assert stats.mean_latency_s == pytest.approx((1.0 + 1.0 + 1.0 + 3.0) / 4)


def test_round_stats_counts_parse_and_valid() -> None:
    groups = {
        KEY: [
            _sample(0, -1.0, parsed=False, valid=False),
            _sample(1, 0.2, valid=False),
            _sample(2, 1.0),
        ]
    }
    stats = round_stats(groups, THRESHOLD)

    assert stats.parse_failures == 1
    assert stats.valid_samples == 1


def test_round_stats_sums_penalties_per_key_over_all_samples() -> None:
    groups = {
        "k1": [
            _sample(0, 0.5, key="k1", penalties={"unknown_place": -0.5, "below_stop_floor": -0.3}),
            _sample(1, 0.6, key="k1", penalties={"unknown_place": -0.5}),
        ],
        "k2": [_sample(0, 0.95, key="k2", penalties={"overloaded_day": -0.05})],
    }
    stats = round_stats(groups, THRESHOLD)

    assert stats.issue_totals == {
        "below_stop_floor": pytest.approx(-0.3),
        "overloaded_day": pytest.approx(-0.05),
        "unknown_place": pytest.approx(-1.0),
    }
    assert list(stats.issue_totals) == sorted(stats.issue_totals)


def test_round_stats_group_without_samples_counts_as_request_only() -> None:
    stats = round_stats({"k1": [], "k2": [_sample(0, 1.0, key="k2")]}, THRESHOLD)

    assert stats.requests == 2
    assert stats.samples == 1
    assert stats.kept == 1
    assert stats.keep_rate == pytest.approx(0.5)
    assert stats.mean_best_reward == pytest.approx(1.0)
