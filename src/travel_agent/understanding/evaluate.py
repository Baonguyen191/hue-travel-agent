"""Đo chất lượng hiểu câu (QU) trên data/eval/query_eval_v1.jsonl.

Chia dev/test theo hash của id: sắp theo SHA-256 rồi lấy DEV_SIZE đầu làm dev, phần còn lại test.
Cố định, không phụ thuộc thứ tự file, nên thêm dòng mới không làm đổi các mục cũ.

Quy ước chấm (mỗi mục gold):
- intent, clarify: so đúng/sai. clarify = có clarification trong dự đoán.
- Trường yêu cầu (start_date, num_days, travel_mode, pace, day_start, day_end, interests) chỉ chấm
  khi gold là plan_new. Lấy từ request nếu có, không thì từ partial. Gold thiếu trường thì kỳ
  vọng là mặc định của PlanRequest (ngày và số ngày không có mặc định: thiếu nghĩa là None).
- must_include, exclude: tập place_id phải bằng nhau (mention không liên kết không tính).
- exclude_categories: tập loại phải bằng nhau.
- soft_preferences: thu hồi lỏng. Một cụm gold được tính là tìm thấy nếu có cụm dự đoán mà
  tỉ lệ từ chung (sau khi bỏ dấu) so với số từ của cụm gold ≥ 0.5.
- full_match: intent, clarify, must, exclude, exclude_categories đều đúng; với plan_new thêm các
  trường yêu cầu và interests. Không tính soft_preferences.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import statistics
from collections.abc import Callable, Mapping, Sequence
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from travel_agent.domain.models import Pace, Place, TravelMode
from travel_agent.training.generator import PlanGenerator
from travel_agent.understanding.extract import (
    Extraction,
    ExtractionError,
    build_parsed_query,
    extract,
)
from travel_agent.understanding.models import Intent, ParsedQuery
from travel_agent.understanding.normalize import strip_diacritics

EVAL_FILE = Path("data/eval/query_eval_v1.jsonl")
EVAL_REF = dt.date(2026, 11, 18)  # ngày tham chiếu cố định để kết quả tái lập
DEV_SIZE = 100
SOFT_OVERLAP = 0.5
PLANNED_FIELDS = ("start_date", "num_days", "travel_mode", "pace", "day_start", "day_end")
_GOLD_DEFAULTS: dict[str, str] = {
    "travel_mode": TravelMode.MOTORBIKE.value,
    "pace": Pace.MODERATE.value,
    "day_start": "08:00",
    "day_end": "21:00",
}


class QuSplit(StrEnum):
    DEV = "dev"
    TEST = "test"


class GoldItem(BaseModel):
    id: str = Field(min_length=1)
    group: str = Field(min_length=1)
    text: str = Field(min_length=1)
    gold: dict[str, Any]


class ItemScore(BaseModel):
    id: str
    group: str
    intent_ok: bool
    clarify_gold: bool
    clarify_pred: bool
    clarify_ok: bool
    planned: bool
    # Chỉ có khi gold là plan_new: từng trường yêu cầu và interests.
    fields: dict[str, bool] = Field(default_factory=dict)
    interests_gold: list[str] = Field(default_factory=list)
    interests_pred: list[str] = Field(default_factory=list)
    must_ok: bool
    exclude_ok: bool
    exclude_categories_ok: bool
    soft_gold: int
    soft_found: int
    full_match: bool


class EvalRecord(BaseModel):
    id: str
    group: str
    text: str
    gold: dict[str, Any]
    # JSON LLM trả về (trước khi code xử lý); None nếu lỗi trích. Giữ để phân tích lỗi sau này.
    extraction: dict[str, Any] | None = None
    pred: ParsedQuery | None
    error: str | None
    latency_s: float
    score: ItemScore


class GroupSummary(BaseModel):
    n: int
    intent_acc: float | None
    full_match_rate: float | None


class QuSummary(BaseModel):
    n: int
    errors: int
    intent_acc: float | None
    clarify_precision: float | None
    clarify_recall: float | None
    n_planned: int
    field_acc: dict[str, float | None]
    interests_exact_acc: float | None
    interests_micro_f1: float | None
    must_include_exact_acc: float | None
    exclude_exact_acc: float | None
    exclude_categories_exact_acc: float | None
    soft_recall: float | None
    full_match_rate: float | None
    latency_p50_s: float | None
    per_group: dict[str, GroupSummary]


# ---------------------------------------------------------------------------
# Dữ liệu và chia tập
# ---------------------------------------------------------------------------


def read_gold(path: Path) -> list[GoldItem]:
    lines = path.read_text(encoding="utf-8").splitlines()
    return [GoldItem.model_validate_json(line) for line in lines if line.strip()]


def _hash_key(item_id: str) -> str:
    return hashlib.sha256(item_id.encode("utf-8")).hexdigest()


def split_items(items: Sequence[GoldItem]) -> dict[QuSplit, list[GoldItem]]:
    """DEV_SIZE mục có hash nhỏ nhất là dev, phần còn lại là test. Giữ thứ tự trong file."""
    dev_ids = {item.id for item in sorted(items, key=lambda item: _hash_key(item.id))[:DEV_SIZE]}
    return {
        QuSplit.DEV: [item for item in items if item.id in dev_ids],
        QuSplit.TEST: [item for item in items if item.id not in dev_ids],
    }


# ---------------------------------------------------------------------------
# Chấm từng mục
# ---------------------------------------------------------------------------


def _str_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]


def _as_date(value: object) -> dt.date | None:
    if isinstance(value, str):
        return dt.date.fromisoformat(value)
    return None


def _as_time(value: object) -> dt.time:
    return dt.time.fromisoformat(str(value))


def _gold_fields(gold: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "start_date": _as_date(gold.get("start_date")),
        "num_days": gold.get("num_days"),
        "travel_mode": gold.get("travel_mode", _GOLD_DEFAULTS["travel_mode"]),
        "pace": gold.get("pace", _GOLD_DEFAULTS["pace"]),
        "day_start": _as_time(gold.get("day_start", _GOLD_DEFAULTS["day_start"])),
        "day_end": _as_time(gold.get("day_end", _GOLD_DEFAULTS["day_end"])),
        "interests": sorted(_str_list(gold.get("interests"))),
    }


def _pred_fields(pred: ParsedQuery) -> dict[str, Any]:
    if pred.request is not None:
        request = pred.request
        return {
            "start_date": request.start_date,
            "num_days": request.num_days,
            "travel_mode": request.travel_mode.value,
            "pace": request.pace.value,
            "day_start": request.day_start,
            "day_end": request.day_end,
            "interests": sorted(request.interests),
        }
    partial = pred.partial
    num_days = partial.get("num_days")
    return {
        "start_date": _as_date(partial.get("start_date")),
        "num_days": num_days if isinstance(num_days, int) else None,
        "travel_mode": partial.get("travel_mode", _GOLD_DEFAULTS["travel_mode"]),
        "pace": partial.get("pace", _GOLD_DEFAULTS["pace"]),
        "day_start": _as_time(partial.get("day_start", _GOLD_DEFAULTS["day_start"])),
        "day_end": _as_time(partial.get("day_end", _GOLD_DEFAULTS["day_end"])),
        "interests": sorted(_str_list(partial.get("interests"))),
    }


def _tokens(text: str) -> set[str]:
    return set(strip_diacritics(text).split())


def _soft_found(gold_phrase: str, predicted: Sequence[str]) -> bool:
    gold_tokens = _tokens(gold_phrase)
    if not gold_tokens:
        return True
    for phrase in predicted:
        overlap = len(gold_tokens & _tokens(phrase)) / len(gold_tokens)
        if overlap >= SOFT_OVERLAP:
            return True
    return False


def score_item(item: GoldItem, pred: ParsedQuery | None) -> ItemScore:
    """Chấm một mục. pred None (lỗi trích) thì mọi tiêu chí sai, trừ số phần tử gold."""
    gold = item.gold
    gold_intent = Intent(gold.get("intent", Intent.PLAN_NEW.value))
    gold_clarify = bool(gold.get("clarify", False))
    planned = gold_intent is Intent.PLAN_NEW
    gold_soft = _str_list(gold.get("soft_preferences"))
    gold_must = set(_str_list(gold.get("must_include")))
    gold_exclude = set(_str_list(gold.get("exclude")))
    gold_categories = set(_str_list(gold.get("exclude_categories")))

    if pred is None:
        return ItemScore(
            id=item.id,
            group=item.group,
            intent_ok=False,
            clarify_gold=gold_clarify,
            clarify_pred=False,
            clarify_ok=False,
            planned=planned,
            fields={name: False for name in (*PLANNED_FIELDS, "interests")} if planned else {},
            interests_gold=sorted(_str_list(gold.get("interests"))) if planned else [],
            must_ok=False,
            exclude_ok=False,
            exclude_categories_ok=False,
            soft_gold=len(gold_soft),
            soft_found=0,
            full_match=False,
        )

    intent_ok = pred.intent is gold_intent
    clarify_pred = pred.clarification is not None
    clarify_ok = clarify_pred == gold_clarify
    pred_must = {item.place_id for item in pred.must_include if item.place_id is not None}
    pred_exclude = {item.place_id for item in pred.exclude if item.place_id is not None}
    pred_categories = {category.value for category in pred.exclude_categories}
    must_ok = pred_must == gold_must
    exclude_ok = pred_exclude == gold_exclude
    categories_ok = pred_categories == gold_categories

    fields: dict[str, bool] = {}
    interests_gold: list[str] = []
    interests_pred: list[str] = []
    fields_ok = True
    if planned:
        expected = _gold_fields(gold)
        actual = _pred_fields(pred)
        for name in PLANNED_FIELDS:
            fields[name] = actual[name] == expected[name]
        fields["interests"] = actual["interests"] == expected["interests"]
        interests_gold = list(expected["interests"])
        interests_pred = list(actual["interests"])
        fields_ok = all(fields.values())

    soft_found = sum(1 for phrase in gold_soft if _soft_found(phrase, pred.soft_preferences))
    full_match = intent_ok and clarify_ok and must_ok and exclude_ok and categories_ok and fields_ok
    return ItemScore(
        id=item.id,
        group=item.group,
        intent_ok=intent_ok,
        clarify_gold=gold_clarify,
        clarify_pred=clarify_pred,
        clarify_ok=clarify_ok,
        planned=planned,
        fields=fields,
        interests_gold=interests_gold,
        interests_pred=interests_pred,
        must_ok=must_ok,
        exclude_ok=exclude_ok,
        exclude_categories_ok=categories_ok,
        soft_gold=len(gold_soft),
        soft_found=soft_found,
        full_match=full_match,
    )


# ---------------------------------------------------------------------------
# Chạy và tổng hợp
# ---------------------------------------------------------------------------


def run_eval(
    items: Sequence[GoldItem],
    places: Sequence[Place],
    generator: PlanGenerator,
    ref: dt.date,
    clock: Callable[[], float],
    on_record: Callable[[EvalRecord], None] | None = None,
) -> list[EvalRecord]:
    """Chạy parse_query trên từng mục. Lỗi trích (ExtractionError) ghi thành mục sai, không dừng.

    Lỗi hạ tầng (GenerationError) để nổi lên, không che.
    """
    records: list[EvalRecord] = []
    for item in items:
        started = clock()
        extraction: Extraction | None = None
        pred: ParsedQuery | None = None
        error: str | None = None
        try:
            extraction = extract(item.text, ref, generator)
            pred = build_parsed_query(item.text, ref, extraction, places)
        except ExtractionError as exc:
            error = str(exc)
        latency = clock() - started
        record = EvalRecord(
            id=item.id,
            group=item.group,
            text=item.text,
            gold=item.gold,
            extraction=extraction.model_dump(mode="json") if extraction is not None else None,
            pred=pred,
            error=error,
            latency_s=round(latency, 3),
            score=score_item(item, pred),
        )
        records.append(record)
        if on_record is not None:
            on_record(record)
    return records


def _rate(hits: int, total: int) -> float | None:
    return hits / total if total else None


def _group_summary(scores: Sequence[ItemScore]) -> GroupSummary:
    return GroupSummary(
        n=len(scores),
        intent_acc=_rate(sum(s.intent_ok for s in scores), len(scores)),
        full_match_rate=_rate(sum(s.full_match for s in scores), len(scores)),
    )


def summarize(records: Sequence[EvalRecord]) -> QuSummary:
    scores = [record.score for record in records]
    n = len(scores)
    planned = [score for score in scores if score.planned]
    clarify_pred = sum(score.clarify_pred for score in scores)
    clarify_gold = sum(score.clarify_gold for score in scores)
    clarify_hits = sum(score.clarify_pred and score.clarify_gold for score in scores)

    tp = fp = fn = 0
    for score in planned:
        gold_set = set(score.interests_gold)
        pred_set = set(score.interests_pred)
        tp += len(gold_set & pred_set)
        fp += len(pred_set - gold_set)
        fn += len(gold_set - pred_set)
    micro_f1 = _rate(2 * tp, 2 * tp + fp + fn)

    soft_total = sum(score.soft_gold for score in scores)
    soft_hits = sum(score.soft_found for score in scores)
    latencies = [record.latency_s for record in records]

    groups: dict[str, list[ItemScore]] = {}
    for score in scores:
        groups.setdefault(score.group, []).append(score)

    field_acc: dict[str, float | None] = {
        name: _rate(sum(score.fields[name] for score in planned), len(planned))
        for name in PLANNED_FIELDS
    }
    return QuSummary(
        n=n,
        errors=sum(record.error is not None for record in records),
        intent_acc=_rate(sum(score.intent_ok for score in scores), n),
        clarify_precision=_rate(clarify_hits, clarify_pred),
        clarify_recall=_rate(clarify_hits, clarify_gold),
        n_planned=len(planned),
        field_acc=field_acc,
        interests_exact_acc=_rate(
            sum(score.fields["interests"] for score in planned), len(planned)
        ),
        interests_micro_f1=micro_f1,
        must_include_exact_acc=_rate(sum(score.must_ok for score in scores), n),
        exclude_exact_acc=_rate(sum(score.exclude_ok for score in scores), n),
        exclude_categories_exact_acc=_rate(sum(score.exclude_categories_ok for score in scores), n),
        soft_recall=_rate(soft_hits, soft_total),
        full_match_rate=_rate(sum(score.full_match for score in scores), n),
        latency_p50_s=round(statistics.median(latencies), 3) if latencies else None,
        per_group={name: _group_summary(items) for name, items in sorted(groups.items())},
    )
