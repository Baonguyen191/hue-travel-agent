"""Measure query understanding on data/eval/query_eval_v2.jsonl.

Run from `backend/`:
    python -m app.understanding.evaluate --extractor rules|ollama --model qwen3.5:4b \
        --split dev|test|all --out ../reports/understanding/<name>.json

Scoring (per gold item; a field is scored only when the item's gold intent makes it apply):
- intent, clarify: right or wrong. clarify means the result carries a clarification question.
- plan_new: start_date and num_days must equal the gold (absent gold means None); categories
  must equal the gold set (absent means empty); people only when the gold states it.
- modify_plan: the kinds of changes must equal the gold kinds.
- place_info: the place must be one of the gold place_ids.
- All items: must_include and exclude (sets of poi ids), and exclude_categories (set), must equal
  the gold; an absent gold list means empty.
- soft_preferences: recall only. A gold phrase is found when a predicted phrase shares at least
  half of its words (after removing diacritics). Not part of full match.
- full_match: intent, clarify and every field above that applies to the item's gold intent.

Dates in the gold are resolved against EVAL_REF (2026-11-18), so results do not depend on today.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import statistics
import sys
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from app.core.config import PROJECT_ROOT, ollama_url, qu_model
from app.schemas.place import Place
from app.understanding.extract import OllamaExtractor
from app.understanding.models import Intent, ParsedQuery
from app.understanding.normalize import strip_diacritics
from app.understanding.understand import Extractor, load_places, understand

EVAL_FILE = PROJECT_ROOT / "data" / "eval" / "query_eval_v2.jsonl"
REPORT_DIR = PROJECT_ROOT / "reports" / "understanding"
EVAL_REF = dt.date(2026, 11, 18)
SOFT_OVERLAP = 0.5
SPLITS = ("dev", "test", "all")


class GoldItem(BaseModel):
    """One evaluation sentence with its gold values as written in the JSONL file."""

    id: str
    group: str
    split: str
    text: str
    gold: dict[str, Any]


class ItemScore(BaseModel):
    """Per-field results for one item. None means the field does not apply to this item."""

    intent_ok: bool
    clarify_ok: bool
    must_ok: bool
    exclude_ok: bool
    exclude_categories_ok: bool
    start_ok: bool | None = None
    num_days_ok: bool | None = None
    categories_ok: bool | None = None
    people_ok: bool | None = None
    changes_ok: bool | None = None
    place_ok: bool | None = None
    soft_hits: int = 0
    soft_total: int = 0
    full_match: bool = False


class EvalRecord(BaseModel):
    """Prediction, latency and scores for one item."""

    id: str
    group: str
    split: str
    text: str
    latency_ms: float
    error: str | None = None
    source: str | None = None
    pred: dict[str, Any] = Field(default_factory=dict)
    score: ItemScore


# ---------------------------------------------------------------------------
# Reading gold and choosing splits
# ---------------------------------------------------------------------------


def read_gold(path: Path) -> list[GoldItem]:
    """Read the JSONL gold file; blank lines are skipped."""
    lines = path.read_text(encoding="utf-8").splitlines()
    return [GoldItem.model_validate_json(line) for line in lines if line.strip()]


def select_split(items: Sequence[GoldItem], split: str) -> list[GoldItem]:
    """Items of one split; "all" keeps every item. Unknown split names are an error."""
    if split not in SPLITS:
        raise ValueError(f"split must be one of {SPLITS}, got {split!r}")
    if split == "all":
        return list(items)
    return [item for item in items if item.split == split]


def _gold_date(value: Any) -> dt.date | None:
    return dt.date.fromisoformat(value) if value else None


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


def _poi_ids(mentions: Sequence[Any]) -> set[str]:
    return {item.poi_id for item in mentions if item.poi_id is not None}


def _soft_found(gold_phrase: str, predicted: Sequence[str]) -> bool:
    gold_words = set(strip_diacritics(gold_phrase).split())
    if not gold_words:
        return True
    for phrase in predicted:
        words = set(strip_diacritics(phrase).split())
        if len(gold_words & words) / len(gold_words) >= SOFT_OVERLAP:
            return True
    return False


def _pred_categories(pred: ParsedQuery) -> set[str]:
    return {str(item) for item in pred.fields.get("categories", [])}


def _plan_scores(gold: dict[str, Any], pred: ParsedQuery) -> dict[str, bool]:
    people_ok = None
    if "people" in gold:
        people_ok = pred.fields.get("people") == gold["people"]
    return {
        "start_ok": pred.fields.get("start_date") == _gold_date(gold.get("start_date")),
        "num_days_ok": pred.fields.get("num_days") == gold.get("num_days"),
        "categories_ok": _pred_categories(pred) == set(gold.get("categories", [])),
        "people_ok": people_ok,
    }


def _modify_ok(gold: dict[str, Any], pred: ParsedQuery) -> bool:
    gold_kinds = sorted(item["kind"] for item in gold.get("changes", []))
    pred_kinds = sorted(change.kind.value for change in pred.changes)
    return gold_kinds == pred_kinds


def _place_ok(gold: dict[str, Any], pred: ParsedQuery) -> bool:
    if pred.place_query is None or pred.place_query.poi_id is None:
        return False
    return pred.place_query.poi_id in set(gold.get("place_ids", []))


def _soft_counts(gold: dict[str, Any], pred: ParsedQuery) -> tuple[int, int]:
    phrases = gold.get("soft_preferences", [])
    hits = sum(1 for phrase in phrases if _soft_found(phrase, pred.soft_preferences))
    return hits, len(phrases)


def _kind_fields(gold: dict[str, Any], pred: ParsedQuery, intent: str) -> dict[str, bool | None]:
    if intent == Intent.PLAN_NEW.value:
        return _plan_scores(gold, pred)
    if intent == Intent.MODIFY_PLAN.value:
        return {"changes_ok": _modify_ok(gold, pred)}
    if intent == Intent.PLACE_INFO.value:
        return {"place_ok": _place_ok(gold, pred)}
    return {}


def _full_match(fields: dict[str, bool | None], base: bool) -> bool:
    return base and all(value is not False for value in fields.values())


def score_item(item: GoldItem, pred: ParsedQuery | None) -> ItemScore:
    """Score one prediction against the item's gold. A missing prediction scores nothing."""
    gold = item.gold
    intent = gold.get("intent", Intent.PLAN_NEW.value)
    soft_total = len(gold.get("soft_preferences", []))
    if pred is None:
        return ItemScore(
            intent_ok=False,
            clarify_ok=False,
            must_ok=False,
            exclude_ok=False,
            exclude_categories_ok=False,
            soft_total=soft_total,
        )
    fields = _kind_fields(gold, pred, intent)
    base = (
        pred.intent.value == intent
        and (pred.clarification is not None) == bool(gold.get("clarify", False))
        and _poi_ids(pred.must_include) == set(gold.get("must_include", []))
        and _poi_ids(pred.exclude) == set(gold.get("exclude", []))
        and {str(item) for item in pred.exclude_categories} == set(gold.get("exclude_categories", []))
    )
    hits, total = _soft_counts(gold, pred)
    return ItemScore(
        intent_ok=pred.intent.value == intent,
        clarify_ok=(pred.clarification is not None) == bool(gold.get("clarify", False)),
        must_ok=_poi_ids(pred.must_include) == set(gold.get("must_include", [])),
        exclude_ok=_poi_ids(pred.exclude) == set(gold.get("exclude", [])),
        exclude_categories_ok=(
            {str(item) for item in pred.exclude_categories} == set(gold.get("exclude_categories", []))
        ),
        soft_hits=hits,
        soft_total=total,
        full_match=_full_match(fields, base),
        **fields,
    )


# ---------------------------------------------------------------------------
# Running and summarising
# ---------------------------------------------------------------------------


def _pred_summary(pred: ParsedQuery | None) -> dict[str, Any]:
    if pred is None:
        return {}
    return {
        "intent": pred.intent.value,
        "clarification": pred.clarification,
        "start_date": pred.fields.get("start_date"),
        "num_days": pred.fields.get("num_days"),
        "categories": sorted(_pred_categories(pred)),
        "people": pred.fields.get("people"),
        "must_include": [item.model_dump() for item in pred.must_include],
        "exclude": [item.model_dump() for item in pred.exclude],
        "exclude_categories": sorted(str(item) for item in pred.exclude_categories),
        "changes": [change.model_dump(mode="json") for change in pred.changes],
        "place_query": pred.place_query.model_dump() if pred.place_query else None,
        "soft_preferences": list(pred.soft_preferences),
        "notes": list(pred.notes),
    }


def run_items(
    items: Sequence[GoldItem],
    predict: Callable[[GoldItem], ParsedQuery],
) -> list[EvalRecord]:
    """Predict every item, timing each call; an exception is recorded and scored as a miss."""
    records: list[EvalRecord] = []
    for item in items:
        started = time.perf_counter()
        pred: ParsedQuery | None = None
        error: str | None = None
        try:
            pred = predict(item)
        except Exception as exc:  # noqa: BLE001 - the harness must keep going and report it
            error = f"{type(exc).__name__}: {exc}"
        latency = (time.perf_counter() - started) * 1000
        records.append(
            EvalRecord(
                id=item.id,
                group=item.group,
                split=item.split,
                text=item.text,
                latency_ms=round(latency, 1),
                error=error,
                source=pred.source.value if pred is not None else None,
                pred=_pred_summary(pred),
                score=score_item(item, pred),
            )
        )
    return records


def _rate(hits: int, total: int) -> float | None:
    return round(hits / total, 4) if total else None


def _percentile(values: Sequence[float], fraction: float) -> float | None:
    if not values:
        return None
    if len(values) == 1:
        return values[0]
    return round(statistics.quantiles(values, n=100, method="inclusive")[int(fraction * 100) - 1], 1)


def _f1(tp: int, fp: int, fn: int) -> float | None:
    if tp == 0 and fp == 0 and fn == 0:
        return None
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    return round(2 * precision * recall / (precision + recall), 4) if precision + recall else 0.0


def _category_counts(records: Sequence[EvalRecord], items: dict[str, GoldItem]) -> tuple[int, int, int]:
    tp = fp = fn = 0
    for record in records:
        if items[record.id].gold.get("intent", "plan_new") != Intent.PLAN_NEW.value:
            continue
        gold = set(items[record.id].gold.get("categories", []))
        pred = set(record.pred.get("categories", []))
        tp += len(gold & pred)
        fp += len(pred - gold)
        fn += len(gold - pred)
    return tp, fp, fn


def _clarify_counts(records: Sequence[EvalRecord], by_id: dict[str, GoldItem]) -> tuple[int, int, int]:
    """(true positives, predicted clarifications, gold clarifications) for precision and recall."""
    predicted = [r for r in records if r.pred.get("clarification")]
    gold_positive = [r for r in records if by_id[r.id].gold.get("clarify", False)]
    tp = sum(1 for r in predicted if by_id[r.id].gold.get("clarify", False))
    return tp, len(predicted), len(gold_positive)


def _group_full(records: Sequence[EvalRecord]) -> dict[str, float | None]:
    groups: dict[str, list[bool]] = {}
    for record in records:
        groups.setdefault(record.group, []).append(record.score.full_match)
    return {name: _rate(sum(values), len(values)) for name, values in sorted(groups.items())}


def summarize(records: Sequence[EvalRecord], items: Sequence[GoldItem]) -> dict[str, Any]:
    """Headline metrics for a run. Denominators are shown next to each rate."""
    by_id = {item.id: item for item in items}
    latencies = [record.latency_ms for record in records]
    plan = [r for r in records if by_id[r.id].gold.get("intent", "plan_new") == "plan_new"]
    modify = [r for r in records if by_id[r.id].gold.get("intent") == "modify_plan"]
    place = [r for r in records if by_id[r.id].gold.get("intent") == "place_info"]
    people = [r for r in records if "people" in by_id[r.id].gold]
    soft_hits = sum(r.score.soft_hits for r in records)
    soft_total = sum(r.score.soft_total for r in records)
    tp, fp, fn = _category_counts(records, by_id)
    clarify_tp, clarify_pred, clarify_gold = _clarify_counts(records, by_id)
    rules_source = sum(1 for r in records if r.source == "RULES")
    return {
        "n": len(records),
        "errors": sum(1 for r in records if r.error),
        "source_rules_count": rules_source,
        "intent_acc": _rate(sum(r.score.intent_ok for r in records), len(records)),
        "full_match": _rate(sum(r.score.full_match for r in records), len(records)),
        "clarify_precision": _rate(clarify_tp, clarify_pred),
        "clarify_recall": _rate(clarify_tp, clarify_gold),
        "start_acc": _rate(sum(bool(r.score.start_ok) for r in plan), len(plan)),
        "num_days_acc": _rate(sum(bool(r.score.num_days_ok) for r in plan), len(plan)),
        "categories_exact": _rate(sum(bool(r.score.categories_ok) for r in plan), len(plan)),
        "category_f1": _f1(tp, fp, fn),
        "people_acc": _rate(sum(bool(r.score.people_ok) for r in people), len(people)),
        "must_exact": _rate(sum(r.score.must_ok for r in records), len(records)),
        "exclude_exact": _rate(sum(r.score.exclude_ok for r in records), len(records)),
        "exclude_categories_exact": _rate(
            sum(r.score.exclude_categories_ok for r in records), len(records)
        ),
        "changes_acc": _rate(sum(bool(r.score.changes_ok) for r in modify), len(modify)),
        "place_acc": _rate(sum(bool(r.score.place_ok) for r in place), len(place)),
        "soft_recall": _rate(soft_hits, soft_total),
        "latency_p50_ms": _percentile(latencies, 0.5),
        "latency_p95_ms": _percentile(latencies, 0.95),
        "per_group_full_match": _group_full(records),
    }


def _ollama_predict(extractor: Extractor, places: Sequence[Place]) -> Callable[[GoldItem], ParsedQuery]:
    def predict(item: GoldItem) -> ParsedQuery:
        return understand(item.text, EVAL_REF, extractor=extractor, places=places)

    return predict


def _rules_predict(places: Sequence[Place]) -> Callable[[GoldItem], ParsedQuery]:
    def predict(item: GoldItem) -> ParsedQuery:
        return understand(item.text, EVAL_REF, extractor=None, places=places)

    return predict


def run_eval(
    items: Sequence[GoldItem],
    predict: Callable[[GoldItem], ParsedQuery],
) -> tuple[list[EvalRecord], dict[str, Any]]:
    """Run the predictions and return the per-item records and the summary."""
    records = run_items(items, predict)
    return records, summarize(records, items)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Evaluate query understanding.")
    parser.add_argument("--extractor", choices=("rules", "ollama"), default="rules")
    parser.add_argument("--model", default=qu_model())
    parser.add_argument("--ollama-url", default=ollama_url())
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--split", choices=SPLITS, default="dev")
    parser.add_argument("--eval", type=Path, default=EVAL_FILE)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--limit", type=int, default=None)
    return parser


def _predictor(args: argparse.Namespace, places: Sequence[Place]) -> Callable[[GoldItem], ParsedQuery]:
    if args.extractor == "rules":
        return _rules_predict(places)
    extractor = OllamaExtractor(args.ollama_url, args.model, timeout=args.timeout)
    return _ollama_predict(extractor, places)


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point: run one extractor on one split, print the summary, optionally write JSON."""
    args = _build_parser().parse_args(argv)
    items = select_split(read_gold(args.eval), args.split)
    if args.limit is not None:
        items = items[: args.limit]
    records, summary = run_eval(items, _predictor(args, load_places()))
    report = {
        "meta": {
            "extractor": args.extractor,
            "model": args.model if args.extractor == "ollama" else None,
            "split": args.split,
            "eval_file": str(args.eval),
            "ref_date": EVAL_REF.isoformat(),
            "generated_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        },
        "summary": summary,
        "records": [record.model_dump(mode="json") for record in records],
    }
    if args.out is not None:
        target = args.out
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
