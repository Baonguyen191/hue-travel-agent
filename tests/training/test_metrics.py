import pytest

from tests.training.factories import PLACES, REQUEST, UNKNOWN_PLACE_RAW, VALID_RAW
from tests.validation.factories import FixedTravelTime
from travel_agent.training.metrics import (
    EvalSummary,
    PlanOutcome,
    regressions,
    score_output,
    summarize,
)


def score(raw: str) -> PlanOutcome:
    return score_output("k1", REQUEST, raw, PLACES, FixedTravelTime(), latency_s=2.0)


def test_valid_plan_is_scored_valid() -> None:
    outcome = score(VALID_RAW)
    assert (outcome.parsed, outcome.valid) == (True, True)
    assert (outcome.day_count, outcome.stop_count) == (1, 3)
    assert outcome.place_ids == ["t:museum", "t:lunch", "t:dinner"]
    assert outcome.unknown_place_count == 0
    assert outcome.latency_s == 2.0


def test_place_outside_candidates_is_unknown() -> None:
    outcome = score(UNKNOWN_PLACE_RAW)
    assert (outcome.parsed, outcome.valid) == (True, False)
    assert outcome.unknown_place_count == 1
    assert "unknown_place" in outcome.issue_codes


def test_unparseable_output_is_not_valid() -> None:
    outcome = score("không phải json")
    assert (outcome.parsed, outcome.valid) == (False, False)
    assert outcome.stop_count == 0


def test_summarize_rates() -> None:
    outcomes = [
        PlanOutcome(
            key="a",
            parsed=True,
            valid=True,
            day_count=1,
            stop_count=4,
            place_ids=["p1", "p2", "p3", "p4"],
            issue_codes=["opening_hours_unknown"],
            latency_s=1.0,
        ),
        PlanOutcome(
            key="b",
            parsed=True,
            valid=False,
            day_count=2,
            stop_count=6,
            unknown_place_count=3,
            place_ids=["p1", "p5", "x1", "x2", "x3", "p6"],
            issue_codes=["unknown_place", "unknown_place", "unknown_place", "stop_overlap"],
            latency_s=3.0,
        ),
        PlanOutcome(key="c", parsed=False, valid=False, latency_s=5.0),
        PlanOutcome(key="d", parsed=False, valid=False, latency_s=7.0),
    ]
    summary = summarize(outcomes)
    assert summary.n == 4
    assert summary.first_pass_valid_rate == 0.25
    assert summary.parse_error_rate == 0.5
    assert summary.unknown_place_rate == 0.3  # 3 trên 10 stop
    assert summary.avg_stops_per_day == pytest.approx(10 / 3)
    assert summary.distinct_place_count == 9
    assert summary.latency_p50_s == 4.0
    assert summary.issue_code_distribution == {
        "opening_hours_unknown": 1,
        "stop_overlap": 1,
        "unknown_place": 3,
    }


def test_summarize_all_unparsed_has_zero_rates() -> None:
    summary = summarize([PlanOutcome(key="a", parsed=False, valid=False)])
    assert summary.unknown_place_rate == 0.0
    assert summary.avg_stops_per_day == 0.0


def test_summarize_rejects_empty_input() -> None:
    with pytest.raises(ValueError, match="không có kết quả"):
        summarize([])


def _summary(valid_rate: float) -> EvalSummary:
    return EvalSummary(
        n=10,
        first_pass_valid_rate=valid_rate,
        parse_error_rate=0.0,
        unknown_place_rate=0.0,
        avg_stops_per_day=4.0,
        distinct_place_count=20,
        latency_p50_s=1.0,
        issue_code_distribution={},
    )


def test_regression_when_valid_rate_drops() -> None:
    problems = regressions(_summary(0.4), _summary(0.5))
    assert len(problems) == 1
    assert "first_pass_valid_rate" in problems[0]


def test_no_regression_when_equal_or_better() -> None:
    assert regressions(_summary(0.5), _summary(0.5)) == []
    assert regressions(_summary(0.6), _summary(0.5)) == []
