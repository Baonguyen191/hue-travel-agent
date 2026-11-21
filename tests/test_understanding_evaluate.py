"""Evaluation harness: gold reading, splits, scoring rules, metrics and the CLI (no network)."""

from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path

_BACKEND = _Path(__file__).resolve().parents[1] / "backend"
if str(_BACKEND) not in _sys.path:
    _sys.path.insert(0, str(_BACKEND))

import datetime as dt  # noqa: E402
import json  # noqa: E402

import pytest  # noqa: E402

from app.schemas.request import TripRequest  # noqa: E402
from app.understanding import evaluate  # noqa: E402
from app.understanding.evaluate import (  # noqa: E402
    GoldItem,
    _f1,
    _percentile,
    _soft_found,
    main,
    read_gold,
    run_eval,
    score_item,
    select_split,
    summarize,
)
from app.understanding.models import (  # noqa: E402
    Intent,
    ParsedQuery,
    PlaceMention,
    PlanChange,
    PlanChangeKind,
)


def _item(item_id: str, split: str = "dev", **gold: object) -> GoldItem:
    return GoldItem(id=item_id, group="full", split=split, text="x", gold=dict(gold))


def _plan_query(**overrides: object) -> ParsedQuery:
    request = TripRequest(
        origin="Huế",
        destination="Huế",
        start_date=dt.date(2026, 12, 20),
        end_date=dt.date(2026, 12, 21),
        people=1,
        categories=["religious"],
    )
    fields = {"start_date": dt.date(2026, 12, 20), "num_days": 2, "categories": ["religious"]}
    base: dict[str, object] = {"intent": Intent.PLAN_NEW, "request": request, "fields": fields}
    base.update(overrides)
    return ParsedQuery(**base)


GOLD_PLAN = {
    "intent": "plan_new",
    "clarify": False,
    "start_date": "2026-12-20",
    "num_days": 2,
    "categories": ["religious"],
}


def test_read_gold_parses_jsonl_and_skips_blank_lines(tmp_path: _Path) -> None:
    path = tmp_path / "eval.jsonl"
    row = {"id": "q1", "group": "full", "split": "dev", "text": "Đi Huế", "gold": {"clarify": True}}
    path.write_text(json.dumps(row, ensure_ascii=False) + "\n\n", encoding="utf-8")

    items = read_gold(path)

    assert [item.id for item in items] == ["q1"]
    assert items[0].gold == {"clarify": True}


def test_select_split_keeps_only_the_split_and_all_keeps_everything() -> None:
    items = [_item("a", "dev"), _item("b", "test")]

    assert [i.id for i in select_split(items, "dev")] == ["a"]
    assert [i.id for i in select_split(items, "test")] == ["b"]
    assert len(select_split(items, "all")) == 2


def test_select_split_rejects_unknown_names() -> None:
    with pytest.raises(ValueError):
        select_split([], "train")


def test_perfect_plan_prediction_is_a_full_match() -> None:
    score = score_item(_item("a", **GOLD_PLAN), _plan_query())

    assert score.full_match
    assert score.start_ok is True
    assert score.num_days_ok is True
    assert score.categories_ok is True
    assert score.people_ok is None


def test_wrong_start_date_breaks_full_match_only_on_that_field() -> None:
    pred = _plan_query(fields={"start_date": dt.date(2026, 12, 19), "num_days": 2, "categories": ["religious"]})

    score = score_item(_item("a", **GOLD_PLAN), pred)

    assert not score.full_match
    assert score.start_ok is False
    assert score.num_days_ok is True


def test_absent_gold_start_expects_none_for_clarification_items() -> None:
    gold = {"intent": "plan_new", "clarify": True, "num_days": 2}
    pred = ParsedQuery(intent=Intent.PLAN_NEW, clarification="Bạn muốn đi từ ngày nào?", fields={"num_days": 2})

    score = score_item(_item("a", **gold), pred)

    assert score.clarify_ok is True
    assert score.start_ok is True
    assert score.full_match


def test_clarification_mismatch_fails_the_item() -> None:
    gold = {"intent": "plan_new", "clarify": True}

    score = score_item(_item("a", **gold), _plan_query())

    assert not score.clarify_ok
    assert not score.full_match


def test_people_is_scored_only_when_gold_states_it() -> None:
    gold = {**GOLD_PLAN, "people": 10}
    pred = _plan_query(fields={"start_date": dt.date(2026, 12, 20), "num_days": 2, "categories": ["religious"], "people": 2})

    score = score_item(_item("a", **gold), pred)

    assert score.people_ok is False
    assert not score.full_match


def test_must_include_compares_poi_id_sets() -> None:
    gold = {**GOLD_PLAN, "must_include": ["huetripo:197559"]}
    pred = _plan_query(must_include=[PlaceMention(text="chùa", poi_id="huetripo:197559", score=0.9)])

    assert score_item(_item("a", **gold), pred).must_ok
    assert not score_item(_item("a", **GOLD_PLAN), pred).must_ok


def test_modify_plan_compares_change_kinds() -> None:
    gold = {"intent": "modify_plan", "changes": [{"kind": "add_days", "value": 1}]}
    pred = ParsedQuery(
        intent=Intent.MODIFY_PLAN,
        changes=[PlanChange(kind=PlanChangeKind.ADD_DAYS, value=1)],
    )

    score = score_item(_item("a", **gold), pred)

    assert score.changes_ok is True
    assert score.full_match


def test_place_info_needs_one_of_the_gold_place_ids() -> None:
    gold = {"intent": "place_info", "place_ids": ["huetripo:483480", "huetripo:531787"]}
    pred = ParsedQuery(
        intent=Intent.PLACE_INFO,
        place_query=PlaceMention(text="Đại Nội", poi_id="huetripo:531787", score=0.9),
    )

    assert score_item(_item("a", **gold), pred).full_match


def test_missing_prediction_scores_nothing() -> None:
    score = score_item(_item("a", **GOLD_PLAN), None)

    assert not score.full_match
    assert not score.intent_ok


@pytest.mark.parametrize(
    ("gold_phrase", "predicted", "expected"),
    [
        ("đi với bố mẹ già", ["bố mẹ già đi cùng"], True),
        ("yên tĩnh", ["chỗ yên tĩnh"], True),
        ("ăn chay", ["đi chùa"], False),
    ],
)
def test_soft_match_shares_half_of_the_words(gold_phrase: str, predicted: list[str], expected: bool) -> None:
    assert _soft_found(gold_phrase, predicted) is expected


def test_f1_and_percentile_handle_empty_and_single_values() -> None:
    assert _f1(0, 0, 0) is None
    assert _f1(2, 0, 0) == 1.0
    assert _f1(1, 1, 1) == 0.5
    assert _percentile([], 0.5) is None
    assert _percentile([7.0], 0.95) == 7.0


def test_summarize_reports_denominators_and_clarify_precision() -> None:
    items = [_item("a", **GOLD_PLAN), _item("b", intent="out_of_scope")]
    records, summary = run_eval(items, lambda item: _plan_query() if item.id == "a" else ParsedQuery(intent=Intent.OUT_OF_SCOPE))

    assert summary["n"] == 2
    assert summary["full_match"] == 1.0
    assert summary["intent_acc"] == 1.0
    assert summary["clarify_precision"] is None
    assert summary["latency_p50_ms"] is not None
    assert len(records) == 2


def test_exception_in_predict_is_recorded_and_scored_as_a_miss() -> None:
    def broken(item: GoldItem) -> ParsedQuery:
        raise RuntimeError("boom")

    records, summary = run_eval([_item("a", **GOLD_PLAN)], broken)

    assert records[0].error is not None
    assert summary["errors"] == 1
    assert summary["full_match"] == 0.0


def test_summarize_counts_clarify_recall_from_gold() -> None:
    items = [_item("a", intent="plan_new", clarify=True)]
    _, summary = run_eval(
        items,
        lambda item: ParsedQuery(intent=Intent.PLAN_NEW, clarification="Bạn đi ngày nào?"),
    )

    assert summary["clarify_recall"] == 1.0
    assert summary["clarify_precision"] == 1.0


def test_cli_writes_a_report_with_the_rules_extractor(tmp_path: _Path, capsys: pytest.CaptureFixture[str]) -> None:
    eval_path = tmp_path / "eval.jsonl"
    rows = [
        {"id": "q1", "group": "full", "split": "dev", "text": "Đi Huế 2 ngày từ 20/12, thích chùa", "gold": GOLD_PLAN},
        {"id": "q2", "group": "full", "split": "test", "text": "Đi Huế", "gold": {"clarify": True}},
    ]
    eval_path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows), encoding="utf-8")
    out = tmp_path / "report.json"

    code = main(["--extractor", "rules", "--split", "dev", "--eval", str(eval_path), "--out", str(out)])

    assert code == 0
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["meta"]["split"] == "dev"
    assert report["meta"]["extractor"] == "rules"
    assert report["summary"]["n"] == 1
    assert report["records"][0]["id"] == "q1"
    assert '"n": 1' in capsys.readouterr().out


def test_eval_constants_match_the_spec() -> None:
    assert evaluate.EVAL_REF == dt.date(2026, 11, 18)
    assert evaluate.EVAL_FILE.name == "query_eval_v2.jsonl"
