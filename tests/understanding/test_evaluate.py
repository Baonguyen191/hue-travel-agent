"""Test harness đo QU với generator giả và bộ eval thật (chỉ đọc file, không gọi mạng)."""

import datetime as dt
import json
import random
from pathlib import Path
from typing import Any

import pytest

from travel_agent.domain.models import Category, PlanRequest
from travel_agent.training.generator import Generation, GenerationError
from travel_agent.understanding.evaluate import (
    DEV_SIZE,
    EVAL_REF,
    GoldItem,
    QuSplit,
    read_gold,
    run_eval,
    score_item,
    split_items,
    summarize,
)
from travel_agent.understanding.models import Intent, ParsedQuery, PlaceMention

EVAL_FILE = Path(__file__).parents[2] / "data" / "eval" / "query_eval_v1.jsonl"
requires_eval = pytest.mark.skipif(not EVAL_FILE.exists(), reason="thiếu bộ eval")


def _item(item_id: str, gold: dict[str, Any], text: str = "câu") -> GoldItem:
    return GoldItem(id=item_id, group="full", text=text, gold=gold)


def _request(**overrides: Any) -> PlanRequest:
    data: dict[str, Any] = {
        "start_date": dt.date(2026, 12, 20),
        "num_days": 2,
        "interests": ["food"],
    }
    data.update(overrides)
    return PlanRequest(**data)


class AnswerByText:
    """Generator giả: đọc câu trong tin nhắn cuối ("Câu: ...") rồi trả JSON đã map sẵn.

    Câu không có trong map trả chuỗi không phải JSON, nên parse_query báo ExtractionError.
    """

    def __init__(self, answers: dict[str, dict[str, Any]]) -> None:
        self._answers = answers

    def generate(
        self, messages: list[dict[str, str]], format_schema: dict[str, Any] | None = None
    ) -> Generation:
        last = messages[-1]["content"]
        text = last.split("Câu: ", 1)[1]
        if text not in self._answers:
            return Generation(content="không phải json")
        return Generation(content=json.dumps(self._answers[text], ensure_ascii=False))


def _answer(**overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "intent": "plan_new",
        "date_text": None,
        "duration_text": None,
        "travel_mode": None,
        "pace": None,
        "day_start": None,
        "day_end": None,
        "interest_phrases": [],
        "must_include_mentions": [],
        "exclude_mentions": [],
        "exclude_category_phrases": [],
        "soft_preferences": [],
        "city": None,
    }
    data.update(overrides)
    return data


# ---------------------------------------------------------------------------
# Chia dev/test
# ---------------------------------------------------------------------------


@requires_eval
def test_real_eval_set_splits_into_100_dev_and_50_test() -> None:
    items = read_gold(EVAL_FILE)
    assert len(items) == 150
    parts = split_items(items)
    assert len(parts[QuSplit.DEV]) == DEV_SIZE == 100
    assert len(parts[QuSplit.TEST]) == 50
    dev_ids = {item.id for item in parts[QuSplit.DEV]}
    test_ids = {item.id for item in parts[QuSplit.TEST]}
    assert dev_ids.isdisjoint(test_ids)
    assert dev_ids | test_ids == {item.id for item in items}


@requires_eval
def test_split_is_stable_across_calls_and_file_order() -> None:
    items = read_gold(EVAL_FILE)
    first = split_items(items)
    again = split_items(items)
    assert [item.id for item in first[QuSplit.TEST]] == [item.id for item in again[QuSplit.TEST]]

    shuffled = list(items)
    random.Random(7).shuffle(shuffled)
    other = split_items(shuffled)
    assert {item.id for item in other[QuSplit.DEV]} == {item.id for item in first[QuSplit.DEV]}


def test_split_keeps_file_order_within_each_part() -> None:
    items = [_item(f"x{index:03d}", {}) for index in range(150)]
    parts = split_items(items)
    for part in parts.values():
        positions = [items.index(item) for item in part]
        assert positions == sorted(positions)


def test_split_sizes_follow_dev_size_for_small_sets() -> None:
    items = [_item(f"s{index}", {}) for index in range(10)]
    parts = split_items(items)
    assert len(parts[QuSplit.DEV]) == 10
    assert parts[QuSplit.TEST] == []


# ---------------------------------------------------------------------------
# Chấm từng mục
# ---------------------------------------------------------------------------


def test_perfect_planned_item_is_full_match() -> None:
    gold = {
        "start_date": "2026-12-20",
        "num_days": 2,
        "interests": ["food"],
        "travel_mode": "motorbike",
    }
    pred = ParsedQuery(intent=Intent.PLAN_NEW, request=_request())
    score = score_item(_item("a", gold), pred)
    assert score.full_match is True
    assert score.intent_ok is True
    assert all(score.fields.values())


def test_missing_gold_fields_expect_planrequest_defaults() -> None:
    # Gold không ghi pace/giờ/phương tiện: kỳ vọng là mặc định, request mặc định vẫn đúng.
    gold = {"start_date": "2026-12-20", "num_days": 2, "interests": ["food"]}
    pred = ParsedQuery(intent=Intent.PLAN_NEW, request=_request())
    assert score_item(_item("a", gold), pred).full_match is True


def test_wrong_pace_breaks_full_match_but_not_intent() -> None:
    gold = {"start_date": "2026-12-20", "num_days": 2, "interests": ["food"], "pace": "packed"}
    pred = ParsedQuery(intent=Intent.PLAN_NEW, request=_request())
    score = score_item(_item("a", gold), pred)
    assert score.intent_ok is True
    assert score.fields["pace"] is False
    assert score.full_match is False


def test_clarification_item_scores_fields_from_partial() -> None:
    gold = {"clarify": True, "num_days": 2, "start_date": "2026-12-20", "interests": ["history"]}
    pred = ParsedQuery(
        intent=Intent.PLAN_NEW,
        clarification="Bạn định đi Huế mấy ngày?",
        partial={"start_date": "2026-12-20", "interests": ["history"]},
    )
    score = score_item(_item("c", gold), pred)
    assert score.clarify_ok is True
    assert score.fields["start_date"] is True
    assert score.fields["num_days"] is False
    assert score.full_match is False


def test_missing_start_date_in_gold_expects_none() -> None:
    gold = {"clarify": True, "num_days": 3}
    pred = ParsedQuery(
        intent=Intent.PLAN_NEW,
        clarification="Bạn muốn đi từ ngày nào?",
        partial={"num_days": 3},
    )
    score = score_item(_item("c", gold), pred)
    assert score.fields["start_date"] is True


def test_non_planned_item_skips_request_fields() -> None:
    gold = {"intent": "place_info", "must_include": ["huetripo:531787"]}
    pred = ParsedQuery(
        intent=Intent.PLACE_INFO,
        must_include=[PlaceMention(text="Đại Nội", place_id="huetripo:531787", score=0.9)],
    )
    score = score_item(_item("p", gold), pred)
    assert score.planned is False
    assert score.fields == {}
    assert score.must_ok is True
    assert score.full_match is True


def test_must_include_requires_exact_place_id_set() -> None:
    gold = {"intent": "place_info", "must_include": ["huetripo:531787", "huetripo:197559"]}
    pred = ParsedQuery(
        intent=Intent.PLACE_INFO,
        must_include=[PlaceMention(text="Đại Nội", place_id="huetripo:531787", score=0.9)],
    )
    score = score_item(_item("p", gold), pred)
    assert score.must_ok is False


def test_unlinked_mention_does_not_count_as_a_place_id() -> None:
    gold = {"intent": "place_info", "must_include": ["huetripo:531787"]}
    pred = ParsedQuery(
        intent=Intent.PLACE_INFO,
        must_include=[PlaceMention(text="Đại Nội", place_id=None, score=0.2)],
    )
    assert score_item(_item("p", gold), pred).must_ok is False


def test_exclude_categories_compare_as_sets_of_values() -> None:
    gold = {"intent": "modify_plan", "exclude_categories": ["museum", "market"]}
    pred = ParsedQuery(
        intent=Intent.MODIFY_PLAN,
        exclude_categories=[Category.MARKET, Category.MUSEUM],
    )
    assert score_item(_item("m", gold), pred).exclude_categories_ok is True


def test_soft_preference_is_found_by_token_overlap_ignoring_diacritics() -> None:
    gold = {
        "start_date": "2026-12-20",
        "num_days": 2,
        "interests": ["food"],
        "soft_preferences": ["đi cùng bố mẹ già"],
    }
    pred = ParsedQuery(
        intent=Intent.PLAN_NEW,
        request=_request(),
        soft_preferences=["bo me gia di cung"],
    )
    score = score_item(_item("s", gold), pred)
    assert score.soft_gold == 1
    assert score.soft_found == 1
    assert score.full_match is True


def test_soft_preference_with_no_overlap_is_not_found() -> None:
    gold = {"soft_preferences": ["yên tĩnh"]}
    pred = ParsedQuery(intent=Intent.OUT_OF_SCOPE, soft_preferences=["ngân sách thấp"])
    assert score_item(_item("s", gold), pred).soft_found == 0


def test_error_item_counts_as_wrong_everywhere() -> None:
    gold = {"start_date": "2026-12-20", "num_days": 2, "soft_preferences": ["x y"]}
    score = score_item(_item("e", gold), None)
    assert score.full_match is False
    assert score.intent_ok is False
    assert score.soft_gold == 1
    assert score.soft_found == 0


# ---------------------------------------------------------------------------
# Chạy và tổng hợp
# ---------------------------------------------------------------------------


class _Clock:
    def __init__(self) -> None:
        self._now = 0.0

    def __call__(self) -> float:
        self._now += 0.25
        return self._now


def test_run_eval_scores_and_records_errors_without_stopping() -> None:
    items = [
        _item(
            "ok",
            {"intent": "out_of_scope"},
            text="Thời tiết Huế thế nào?",
        ),
        _item("bad", {"intent": "out_of_scope"}, text="Câu không có đáp án"),
    ]
    generator = AnswerByText(
        {"Thời tiết Huế thế nào?": _answer(intent="out_of_scope")},
    )
    records = run_eval(items, [], generator, EVAL_REF, _Clock())
    assert len(records) == 2
    assert records[0].score.full_match is True
    assert records[0].error is None
    assert records[1].error is not None
    assert records[1].pred is None
    assert summarize(records).errors == 1


def test_run_eval_lets_infrastructure_errors_through() -> None:
    class Broken:
        def generate(
            self, messages: list[dict[str, str]], format_schema: dict[str, Any] | None = None
        ) -> Generation:
            raise GenerationError("Ollama chết")

    with pytest.raises(GenerationError):
        run_eval([_item("x", {})], [], Broken(), EVAL_REF, _Clock())


def test_run_eval_marks_bad_json_as_error_item() -> None:
    class Garbage:
        def generate(
            self, messages: list[dict[str, str]], format_schema: dict[str, Any] | None = None
        ) -> Generation:
            return Generation(content="không phải json")

    records = run_eval([_item("x", {})], [], Garbage(), EVAL_REF, _Clock())
    assert records[0].pred is None
    assert records[0].error is not None
    assert records[0].score.full_match is False


def test_run_eval_calls_on_record_for_each_item() -> None:
    seen: list[str] = []
    generator = AnswerByText({"câu": _answer(intent="out_of_scope")})
    run_eval(
        [_item("x", {"intent": "out_of_scope"}, text="câu")],
        [],
        generator,
        EVAL_REF,
        _Clock(),
        on_record=lambda record: seen.append(record.id),
    )
    assert seen == ["x"]


def test_summary_metrics_on_small_run() -> None:
    items = [
        _item(
            "p1",
            {"start_date": "2026-12-20", "num_days": 2, "interests": ["food", "history"]},
            text="A",
        ),
        _item(
            "p2",
            {"start_date": "2026-12-21", "num_days": 2, "interests": ["food"]},
            text="B",
        ),
        _item("c1", {"clarify": True, "num_days": 2}, text="C"),
    ]
    generator = AnswerByText(
        {
            "A": _answer(
                date_text="20/12",
                duration_text="2 ngày",
                interest_phrases=["ăn uống", "lăng"],
            ),
            # Sai ngày: 21/12 gold, đoán 22/12.
            "B": _answer(date_text="22/12", duration_text="2 ngày", interest_phrases=["ăn uống"]),
            "C": _answer(duration_text="2 ngày"),
        }
    )
    records = run_eval(items, [], generator, EVAL_REF, _Clock())
    summary = summarize(records)
    assert summary.n == 3
    assert summary.errors == 0
    assert summary.field_acc["num_days"] == pytest.approx(1.0)
    assert summary.n_planned == 3
    assert summary.field_acc["start_date"] == pytest.approx(2 / 3)
    assert summary.interests_exact_acc == pytest.approx(1.0)
    # TP = food(p1) + history(p1) + food(p2) = 3; FP = 0; FN = 0. F1 = 1.0.
    assert summary.interests_micro_f1 == pytest.approx(1.0)
    assert summary.clarify_precision == pytest.approx(1.0)
    assert summary.clarify_recall == pytest.approx(1.0)
    assert summary.intent_acc == pytest.approx(1.0)
    # p1 và c1 đúng hoàn toàn; p2 sai ngày.
    assert summary.full_match_rate == pytest.approx(2 / 3)
    assert summary.latency_p50_s == pytest.approx(0.25)
    assert summary.per_group["full"].n == 3


def test_micro_f1_counts_false_positives_and_negatives() -> None:
    items = [_item("f", {"start_date": "2026-12-20", "num_days": 1, "interests": ["food"]}, "F")]
    generator = AnswerByText(
        {"F": _answer(date_text="20/12", duration_text="1 ngày", interest_phrases=["lăng"])}
    )
    summary = summarize(run_eval(items, [], generator, EVAL_REF, _Clock()))
    # TP 0, FP 1 (history), FN 1 (food): F1 = 0.
    assert summary.interests_micro_f1 == pytest.approx(0.0)
    assert summary.interests_exact_acc == pytest.approx(0.0)


def test_empty_run_has_no_rates() -> None:
    summary = summarize([])
    assert summary.n == 0
    assert summary.intent_acc is None
    assert summary.latency_p50_s is None
