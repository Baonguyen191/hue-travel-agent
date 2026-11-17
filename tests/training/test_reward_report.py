import json
from pathlib import Path

import pytest

from tests.planning.factories import make_pool
from tests.validation.factories import (
    DAY1,
    FixedTravelTime,
    make_day,
    make_itinerary,
    make_request,
)
from travel_agent.cli import main
from travel_agent.data.place_repository import SqlitePlaceRepository
from travel_agent.domain.models import Place, PlanRequest
from travel_agent.planning.candidates import select_candidates
from travel_agent.training.metrics import PlanOutcome
from travel_agent.training.requests import EvalEntry, Split, read_eval_set
from travel_agent.training.reward import RewardBreakdown
from travel_agent.training.reward_report import (
    RewardSummary,
    ScoredOutcome,
    check_report,
    score_outcomes,
    summarize_rewards,
)
from travel_agent.training.runner import candidate_seed

PLACES: list[Place] = make_pool(per_category=6)
TRAVEL = FixedTravelTime(minutes=10.0)
BROKEN = "không phải json"


def _entry(index: int, request: PlanRequest | None = None) -> EvalEntry:
    # candidate_seed đọc 8 ký tự đầu của key dưới dạng hex, nên key phải là hex.
    return EvalEntry(
        key=f"{index:08x}",
        split=Split.DEV,
        request=request or make_request(),
    )


def _raw_with_places(*place_ids: str) -> str:
    stops = [(pid, f"{8 + i:02d}:00", f"{8 + i:02d}:30") for i, pid in enumerate(place_ids)]
    return make_itinerary(make_day(stops, DAY1)).model_dump_json()


def _breakdown(
    total: float, valid: bool, penalties: dict[str, float] | None = None
) -> RewardBreakdown:
    return RewardBreakdown(total=total, parsed=True, valid=valid, penalties=penalties or {})


def _scored(
    key: str,
    valid: bool,
    total: float,
    *,
    penalties: dict[str, float] | None = None,
    breakdown_valid: bool | None = None,
) -> ScoredOutcome:
    breakdown = _breakdown(total, valid if breakdown_valid is None else breakdown_valid, penalties)
    return ScoredOutcome(key=key, valid=valid, breakdown=breakdown)


def _summary(
    mean: float, valid: float | None, invalid: float | None, mismatch: int = 0
) -> RewardSummary:
    return RewardSummary(
        n=2,
        mean_reward=mean,
        mean_reward_valid=valid,
        mean_reward_invalid=invalid,
        n_valid=0 if valid is None else 1,
        n_invalid=0 if invalid is None else 1,
        valid_mismatch=mismatch,
        penalty_totals={},
        below_floor_days=0,
    )


# score_outcomes


def test_broken_output_scores_minus_one_and_keeps_outcome_flag() -> None:
    entries = [_entry(1)]
    outcomes = [PlanOutcome(key=entries[0].key, parsed=False, valid=False, raw=BROKEN)]
    [scored] = score_outcomes(entries, outcomes, PLACES, TRAVEL)
    assert scored.key == entries[0].key
    assert scored.valid is False
    assert scored.breakdown.total == -1.0


def test_unknown_place_is_scored_against_rebuilt_candidates() -> None:
    entries = [_entry(2)]
    outcomes = [
        PlanOutcome(key=entries[0].key, parsed=True, valid=False, raw=_raw_with_places("x:404"))
    ]
    [scored] = score_outcomes(entries, outcomes, PLACES, TRAVEL)
    assert scored.breakdown.penalties["unknown_place"] == -0.5


def test_candidates_match_runner_seed_so_candidate_ids_are_known() -> None:
    entry = _entry(3)
    candidates = select_candidates(entry.request, PLACES, candidate_seed(entry.key))
    known_id = candidates[0].id
    outcomes = [
        PlanOutcome(key=entry.key, parsed=True, valid=False, raw=_raw_with_places(known_id))
    ]
    [scored] = score_outcomes([entry], outcomes, PLACES, TRAVEL)
    assert "unknown_place" not in scored.breakdown.penalties


def test_outcome_without_entry_is_an_error() -> None:
    outcomes = [PlanOutcome(key="ffffffff", parsed=False, valid=False, raw=BROKEN)]
    with pytest.raises(ValueError, match="ffffffff"):
        score_outcomes([_entry(4)], outcomes, PLACES, TRAVEL)


def test_duplicate_outcome_is_an_error() -> None:
    entry = _entry(5)
    outcome = PlanOutcome(key=entry.key, parsed=False, valid=False, raw=BROKEN)
    with pytest.raises(ValueError, match="nhiều lần"):
        score_outcomes([entry], [outcome, outcome], PLACES, TRAVEL)


def test_valid_flag_disagreement_is_reported_as_mismatch() -> None:
    entry = _entry(6)
    # Outcome ghi valid=True nhưng output không parse được: breakdown phải ghi valid=False.
    outcomes = [PlanOutcome(key=entry.key, parsed=True, valid=True, raw=BROKEN)]
    [scored] = score_outcomes([entry], outcomes, PLACES, TRAVEL)
    assert scored.breakdown.valid is False
    assert summarize_rewards([scored]).valid_mismatch == 1


# summarize_rewards


def test_summary_splits_means_by_outcome_validity() -> None:
    scored = [
        _scored("a", True, 1.0),
        _scored("b", True, 0.6),
        _scored("c", False, -1.0),
        _scored("d", False, 0.0),
    ]
    summary = summarize_rewards(scored)
    assert summary.n == 4
    assert summary.mean_reward == pytest.approx(0.15)
    assert summary.mean_reward_valid == pytest.approx(0.8)
    assert summary.mean_reward_invalid == pytest.approx(-0.5)
    assert (summary.n_valid, summary.n_invalid) == (2, 2)
    assert summary.valid_mismatch == 0


def test_summary_group_means_are_none_when_group_is_empty() -> None:
    only_valid = summarize_rewards([_scored("a", True, 0.5)])
    assert only_valid.mean_reward_invalid is None
    assert only_valid.mean_reward_valid == 0.5
    only_invalid = summarize_rewards([_scored("b", False, -1.0)])
    assert only_invalid.mean_reward_valid is None
    assert only_invalid.mean_reward_invalid == -1.0


def test_summary_of_nothing_is_an_error() -> None:
    with pytest.raises(ValueError):
        summarize_rewards([])


def test_penalty_totals_sum_per_key_and_below_floor_days_count_days() -> None:
    scored = [
        _scored("a", False, 0.1, penalties={"below_stop_floor": -0.6, "unknown_place": -0.5}),
        _scored("b", False, 0.4, penalties={"below_stop_floor": -0.3, "overloaded_day": -0.05}),
    ]
    summary = summarize_rewards(scored)
    assert summary.penalty_totals == {
        "below_stop_floor": -0.9,
        "overloaded_day": -0.05,
        "unknown_place": -0.5,
    }
    assert summary.below_floor_days == 3


def test_mismatch_counts_rows_where_breakdown_disagrees_with_outcome() -> None:
    scored = [
        _scored("a", True, 1.0, breakdown_valid=False),
        _scored("b", False, 0.0),
        _scored("c", True, 1.0, breakdown_valid=False),
    ]
    assert summarize_rewards(scored).valid_mismatch == 2


# check_report


def test_check_report_passes_when_ordering_holds() -> None:
    summaries = {
        "sft": _summary(0.2, 0.9, -0.4),
        "baseline": _summary(-0.1, 0.5, -0.8),
    }
    assert check_report(summaries, better="sft", worse="baseline") == []


def test_check_report_fails_when_better_is_not_higher() -> None:
    summaries = {"sft": _summary(0.2, None, 0.2), "baseline": _summary(0.2, None, 0.2)}
    [failure] = check_report(summaries, better="sft", worse="baseline")
    assert "sft" in failure and "baseline" in failure


def test_check_report_fails_when_valid_mean_not_above_invalid_mean() -> None:
    summaries = {
        "sft": _summary(0.5, 0.3, 0.6),
        "baseline": _summary(-0.5, -0.4, -0.6),
    }
    failures = check_report(summaries, better="sft", worse="baseline")
    assert len(failures) == 1
    assert "sft" in failures[0] and "hợp lệ" in failures[0]


def test_check_report_skips_ordering_when_a_group_is_missing() -> None:
    summaries = {"sft": _summary(0.5, 0.5, None), "baseline": _summary(0.0, None, 0.0)}
    assert check_report(summaries, better="sft", worse="baseline") == []


def test_check_report_fails_on_any_valid_mismatch() -> None:
    summaries = {
        "sft": _summary(0.5, 0.9, 0.1, mismatch=1),
        "baseline": _summary(0.0, 0.5, -0.5),
    }
    failures = check_report(summaries, better="sft", worse="baseline")
    assert len(failures) == 1
    assert "valid" in failures[0]


def test_check_report_reports_missing_name() -> None:
    summaries = {"sft": _summary(0.5, None, 0.5)}
    [failure] = check_report(summaries, better="sft", worse="baseline")
    assert "baseline" in failure


# CLI


@pytest.fixture
def db(tmp_path: Path) -> Path:
    path = tmp_path / "hue.sqlite"
    repo = SqlitePlaceRepository(path)
    repo.upsert_many(make_pool(per_category=6))
    repo.close()
    return path


@pytest.fixture
def evalset(tmp_path: Path) -> Path:
    path = tmp_path / "eval.jsonl"
    assert main(["make-evalset", "--out", str(path), "--seed", "11"]) == 0
    return path


def _write_outcomes(path: Path, evalset: Path, raw: str, valid: bool = False) -> Path:
    lines = [
        PlanOutcome(key=entry.key, parsed=raw != BROKEN, valid=valid, raw=raw).model_dump_json()
        for entry in read_eval_set(evalset, Split.DEV)
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _cli(db: Path, evalset: Path, out: Path, outcomes: list[str], better: str, worse: str) -> int:
    args = ["reward-report", "--db", str(db), "--evalset", str(evalset)]
    for item in outcomes:
        args += ["--outcomes", item]
    return main([*args, "--better", better, "--worse", worse, "--out", str(out)])


def test_cli_passes_and_writes_json_when_better_model_scores_higher(
    db: Path, evalset: Path, tmp_path: Path
) -> None:
    # Output có một stop ở địa điểm lạ: reward > -1. Output hỏng: reward = -1.
    better = _write_outcomes(tmp_path / "sft.jsonl", evalset, _raw_with_places("x:404"))
    worse = _write_outcomes(tmp_path / "baseline.jsonl", evalset, BROKEN)
    out = tmp_path / "reports" / "dev_check.json"
    code = _cli(db, evalset, out, [f"sft={better}", f"baseline={worse}"], "sft", "baseline")
    assert code == 0
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["failures"] == []
    assert report["summaries"]["baseline"]["mean_reward"] == -1.0
    assert report["summaries"]["sft"]["n"] == 70


def test_cli_exits_4_and_lists_failures_when_ordering_fails(
    db: Path, evalset: Path, tmp_path: Path
) -> None:
    same = _write_outcomes(tmp_path / "a.jsonl", evalset, BROKEN)
    out = tmp_path / "dev_check.json"
    code = _cli(db, evalset, out, [f"sft={same}", f"baseline={same}"], "sft", "baseline")
    assert code == 4
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["failures"]
    assert "sft" in report["summaries"] and "baseline" in report["summaries"]


def test_cli_rejects_outcome_key_outside_eval_set(db: Path, evalset: Path, tmp_path: Path) -> None:
    path = tmp_path / "bad.jsonl"
    path.write_text(
        PlanOutcome(key="ffffffff", parsed=False, valid=False, raw=BROKEN).model_dump_json() + "\n",
        encoding="utf-8",
    )
    code = _cli(
        db, evalset, tmp_path / "out.json", [f"sft={path}", f"baseline={path}"], "sft", "baseline"
    )
    assert code == 2
    assert not (tmp_path / "out.json").exists()


def test_cli_rejects_better_or_worse_without_outcomes(
    db: Path, evalset: Path, tmp_path: Path
) -> None:
    path = _write_outcomes(tmp_path / "a.jsonl", evalset, BROKEN)
    code = _cli(db, evalset, tmp_path / "out.json", [f"sft={path}"], "sft", "baseline")
    assert code == 2


def test_cli_rejects_malformed_outcomes_item(db: Path, evalset: Path, tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        main(
            [
                "reward-report",
                "--db",
                str(db),
                "--evalset",
                str(evalset),
                "--outcomes",
                "sem_dau_bang",
                "--better",
                "sft",
                "--worse",
                "baseline",
                "--out",
                str(tmp_path / "out.json"),
            ]
        )
