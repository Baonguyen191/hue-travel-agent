"""Runs the system evaluation: RAG answer quality and multi-agent chat scenarios.

    python -m app.evaluation.run --suite agents --split dev --no-llm

Each suite returns {"summary": {...}, "records": [...]}; `main` writes
{"config", "summary", "records"} to reports/system/<suite>_<split>.json. The RAG suite and the
LLM-backed agents run need a local Ollama; without one only the rules-based agents suite runs.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx

from app.chat import texts
from app.chat.cards import phone_of
from app.core.config import (
    PROJECT_ROOT,
    hue_database_path,
    ollama_url,
    qu_model,
    rag_embed_model,
    rag_gen_model,
    rag_index_path,
)
from app.core.usage import record_usage
from app.evaluation import rag_metrics
from app.evaluation.agent_metrics import handler_hits, tool_counts, tools_exact
from app.evaluation.gold import RAG_EVAL_FILE, SCENARIO_FILE, RagItem, Scenario, load_jsonl
from app.evaluation.harness import USER, EvalHarness, build_harness, final_state
from app.evaluation.judge import Judge, JudgeError
from app.evaluation.planning_metrics import budget_compliant, constraint_checks, schedule_feasible
from app.evaluation.spies import spy_poi_search
from app.evaluation.stats import mean, percentile, rate
from app.rag.answer import RagAnswerer, build_context
from app.rag.facts import _phones, _times, check_facts
from app.rag.index import EmbedClient, EmbeddingStore
from app.rag.retrieve import Retriever
from app.repositories.hue_places import HuePlacesRepository
from app.schemas.place import Place
from app.services.poi_search import normalize_vietnamese
from app.understanding.evaluate import EVAL_REF
from app.understanding.extract import OllamaExtractor
from app.understanding.understand import understand

DEFAULT_OUT_DIR = PROJECT_ROOT / "reports" / "system"
DEFAULT_K = 5
COUNTED_COMPONENTS = ("extractor", "rag_generator")
RAG_METRICS = ("context_precision", "context_recall", "faithfulness", "answer_correctness")


def _ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 1)


def _usage_dict(usage: Mapping[str, Any]) -> dict[str, dict[str, int]]:
    return {component: item.to_dict() for component, item in usage.items()}


def _latency_stats(values: Sequence[float]) -> dict[str, float | None]:
    return {
        "latency_p50_ms": percentile(values, 0.5),
        "latency_p95_ms": percentile(values, 0.95),
        "latency_mean_ms": mean(values),
    }


def _tokens_per_turn(usages: Sequence[Mapping[str, Mapping[str, int]]]) -> dict[str, Any]:
    """Mean tokens per turn; prompt/completion/total count the extractor and the answer generator only."""

    def counted(usage: Mapping[str, Mapping[str, int]], field: str) -> int:
        return sum(usage.get(component, {}).get(field, 0) for component in COUNTED_COMPONENTS)

    components = sorted({component for usage in usages for component in usage})
    return {
        "prompt": mean(counted(u, "prompt_tokens") for u in usages),
        "completion": mean(counted(u, "completion_tokens") for u in usages),
        "total": mean(counted(u, "total_tokens") for u in usages),
        "by_component": {
            component: mean(u.get(component, {}).get("total_tokens", 0) for u in usages)
            for component in components
        },
    }


def _ratio(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 4) if denominator else None


# ---------------------------------------------------------------------------
# RAG suite
# ---------------------------------------------------------------------------


def run_rag_suite(
    items: Sequence[RagItem],
    answerer: Any,
    judge: Any,
    understand_fn: Callable[[str, Any], Any],
) -> dict[str, Any]:
    """Answer every gold question, then score retrieval, faithfulness and correctness."""
    records = [_rag_record(item, answerer, judge, understand_fn) for item in items]
    return {"summary": _rag_summary(records), "records": records}


def _rag_record(
    item: RagItem, answerer: Any, judge: Any, understand_fn: Callable[[str, Any], Any]
) -> dict[str, Any]:
    k = getattr(answerer, "k", DEFAULT_K)
    try:
        with record_usage() as usage:
            started = time.perf_counter()
            parsed = understand_fn(item.question, None)
            result = answerer.answer(item.question, parsed)
            latency_ms = _ms(started)
    except Exception as exc:  # one bad item must not stop the suite
        return _rag_error_record(item, f"{type(exc).__name__}: {exc}")
    retrieved = [hit.poi_id for hit in result.retrieval.hits]
    gold_answerable = item.group != "unanswerable"
    citation_hit = bool(set(result.cited_poi_ids) & set(item.relevant_poi_ids)) if gold_answerable else None
    claims: list[str] = []
    supported: list[bool] = []
    faithfulness: float | None = None
    correctness: float | None = None
    judge_error = False
    with record_usage() as judge_usage:
        if result.source == "refusal":
            correctness = 0.0 if gold_answerable else 1.0
        else:
            try:
                claims = judge.claims(result.text)
                context = build_context(result.retrieval.hits, answerer.retriever.by_id)
                supported = _apply_fact_overrides(
                    claims, judge.support(claims, context), result, answerer.retriever.by_id
                )
                faithfulness = rag_metrics.faithfulness(supported)
                correctness = 0.0 if not gold_answerable else rag_metrics.claim_f1(
                    *judge.compare(claims, item.reference_answer)
                )
            except JudgeError:
                judge_error, faithfulness, correctness = True, None, None
    return {
        "id": item.id,
        "group": item.group,
        "split": item.split,
        "question": item.question,
        "retrieved": retrieved,
        "relevant": list(item.relevant_poi_ids),
        "mode": result.retrieval.mode,
        "source": result.source,
        "cited": list(result.cited_poi_ids),
        "answerable": result.answerable,
        "text": result.text,
        "claims": claims,
        "supported": supported,
        "context_precision": rag_metrics.context_precision(retrieved, item.relevant_poi_ids),
        "context_recall": rag_metrics.context_recall(retrieved, item.relevant_poi_ids, k),
        "faithfulness": faithfulness,
        "answer_correctness": correctness,
        "citation_hit": citation_hit,
        "judge_error": judge_error,
        "error": None,
        "latency_ms": latency_ms,
        "usage": _usage_dict(usage),
        "judge_usage": _usage_dict(judge_usage),
    }


def _rag_error_record(item: RagItem, error: str) -> dict[str, Any]:
    """A record for an item whose retrieval or answering crashed: every metric is missing."""
    return {
        "id": item.id,
        "group": item.group,
        "split": item.split,
        "question": item.question,
        "retrieved": [],
        "relevant": list(item.relevant_poi_ids),
        "mode": None,
        "source": None,
        "cited": [],
        "answerable": None,
        "text": "",
        "claims": [],
        "supported": [],
        "context_precision": None,
        "context_recall": None,
        "faithfulness": None,
        "answer_correctness": None,
        "citation_hit": None,
        "judge_error": False,
        "error": error,
        "latency_ms": None,
        "usage": {},
        "judge_usage": {},
    }


def _claim_states(claim: str, mismatch: Any) -> bool:
    """Does the claim state the wrong fact? Times and phones compare parsed values, the rest folded text."""
    value = str(mismatch.value)
    if mismatch.kind == "time":
        hour, _, minute = value.partition(":")
        return (int(hour), int(minute)) in _times(claim)
    if mismatch.kind == "phone":
        return value in _phones(claim)
    folded = normalize_vietnamese(value)
    return bool(folded) and folded in normalize_vietnamese(claim)


def _apply_fact_overrides(
    claims: Sequence[str], supported: Sequence[bool], result: Any, by_id: Mapping[str, Place]
) -> list[bool]:
    """A fact the checker finds wrong makes every claim stating it unsupported, whatever the judge said.

    A wrong fact no claim states adds one False verdict per distinct (kind, value).
    """
    verdicts = list(supported)
    cited = [by_id[poi_id] for poi_id in result.cited_poi_ids if poi_id in by_id]
    seen: set[tuple[str, str]] = set()
    for mismatch in check_facts(result.raw_text, cited):
        key = (mismatch.kind, str(mismatch.value))
        if key in seen:
            continue
        seen.add(key)
        matched = [i for i, claim in enumerate(claims) if _claim_states(claim, mismatch)]
        for index in matched:
            verdicts[index] = False
        if not matched:
            verdicts.append(False)
    return verdicts


def _rag_summary(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    refusals = [r for r in records if r["source"] == "refusal"]
    unanswerable = [r for r in records if r["group"] == "unanswerable"]
    correct_refusals = [r for r in refusals if r["group"] == "unanswerable"]
    usages = [r["usage"] for r in records]
    judge_tokens = sum(c["total_tokens"] for r in records for c in r["judge_usage"].values())
    latencies = [r["latency_ms"] for r in records if r["latency_ms"] is not None]
    groups = sorted({r["group"] for r in records})
    return {
        "n": len(records),
        **{name: mean(r[name] for r in records) for name in RAG_METRICS},
        "citation_hit_rate": rate(r["citation_hit"] for r in records),
        "refusal_precision": _ratio(len(correct_refusals), len(refusals)),
        "refusal_recall": _ratio(len(correct_refusals), len(unanswerable)),
        "judge_errors": sum(1 for r in records if r["judge_error"]),
        "errors": sum(1 for r in records if r["error"] is not None),
        "refusal_count": len(refusals),
        "n_scored": {name: sum(1 for r in records if r[name] is not None) for name in RAG_METRICS},
        "fallback_count": sum(1 for r in records if r["source"] == "fallback"),
        "mode_counts": dict(Counter(r["mode"] for r in records if r["mode"] is not None)),
        **_latency_stats(latencies),
        "tokens_per_turn": _tokens_per_turn(usages),
        "judge_tokens_total": judge_tokens,
        "per_group": {
            group: {
                name: mean(r[name] for r in records if r["group"] == group) for name in RAG_METRICS
            }
            for group in groups
        },
    }


# ---------------------------------------------------------------------------
# Agents suite
# ---------------------------------------------------------------------------


def run_agents_suite(
    scenarios: Sequence[Scenario],
    make_harness: Callable[[], EvalHarness],
    places_by_id: Mapping[str, Place],
    rag_enabled: bool = True,
) -> dict[str, Any]:
    """Play every scenario on a fresh harness and score routing, tools, state and the saved plans.

    With `rag_enabled` False the "rag" tool is dropped from the expectations, since the place
    answerer is not wired in and could never be called.
    """
    records = [_agents_record(s, make_harness, places_by_id, rag_enabled) for s in scenarios]
    return {"summary": _agents_summary(records), "records": records}


def _agents_record(
    scenario: Scenario,
    make_harness: Callable[[], EvalHarness],
    places_by_id: Mapping[str, Place],
    rag_enabled: bool,
) -> dict[str, Any]:
    expect = scenario.expect
    if not rag_enabled:
        expect = expect.model_copy(
            update={
                "tools_called": [t for t in expect.tools_called if t != "rag"],
                "tools_not_called": [t for t in expect.tools_not_called if t != "rag"],
            }
        )
    h = make_harness()
    conversation = f"eval-{scenario.id}"
    with spy_poi_search(h.log):
        played = asyncio.run(_play(h, scenario, conversation))
    handlers = [turn["handler"] for turn in played["turns"]]
    hits, gold_turns = handler_hits(expect.handlers, handlers)
    error = played["error"]
    final = played["final_state"] if error is None else "failed"
    called = h.log.called()
    plans: dict[tuple[str, int], dict[str, Any]] = played["plans"]
    final_payload: dict[str, Any] | None = played["final_payload"]
    trace = played["trace"]
    tp, fp, fn = tool_counts(called, expect)
    return {
        "id": scenario.id,
        "group": scenario.group,
        "split": scenario.split,
        "handlers": handlers,
        "expected_handlers": list(expect.handlers),
        "handler_hits": [hits, gold_turns],
        "final_state": final,
        "expected_final_state": expect.final_state,
        "task_success": final == expect.final_state and error is None,
        "trace": trace,
        "trace_ok": None if expect.trace is None else trace == expect.trace,
        "tools_called": sorted(called),
        "tools_exact": tools_exact(called, expect),
        "tool_counts": [tp, fp, fn],
        "budget_ok": _budget_ok(final_payload, expect.budget),
        "feasibility": [
            _feasibility(plan_id, version, payload, places_by_id) for (plan_id, version), payload in plans.items()
        ],
        "constraints": _constraints(final_payload, expect.constraints),
        "turns": played["turns"],
        "error": error,
    }


async def _play(h: EvalHarness, scenario: Scenario, conversation: str) -> dict[str, Any]:
    """Send each turn, log handler/latency/usage, and keep every saved plan version."""
    turns: list[dict[str, Any]] = []
    plans: dict[tuple[str, int], dict[str, Any]] = {}
    final_payload: dict[str, Any] | None = None
    reply = None
    handler = "none"
    error: str | None = None
    log = h.service.handler_log
    assert log is not None
    for text in scenario.turns:
        before = len(log)
        started = time.perf_counter()
        try:
            with record_usage() as usage:
                reply = await h.service.handle(conversation, USER, text)
                latency_ms = _ms(started)
        except Exception as exc:  # a crashing turn is a failed scenario, not a failed run
            error = f"{type(exc).__name__}: {exc}"
            turns.append({"text": text, "handler": "none", "latency_ms": _ms(started), "usage": {}, "error": error})
            break
        handler = log[before] if len(log) > before else "none"
        turns.append(
            {"text": text, "handler": handler, "latency_ms": latency_ms, "usage": _usage_dict(usage), "error": None}
        )
        thread_id = h.chats.context(conversation).thread_id
        plan = h.store.latest(thread_id) if thread_id else None
        if plan is not None:
            plans[(plan["plan_id"], plan["version"])] = plan["payload"]
            final_payload = plan["payload"]
    thread_id = h.chats.context(conversation).thread_id
    state = None
    if thread_id and error is None:
        try:
            state = await h.service.orchestrator.state(thread_id)
        except Exception as exc:  # keep the scenario's other results
            error = f"{type(exc).__name__}: {exc}"
    outcome = final_state(handler, reply, h, conversation) if reply is not None and error is None else "failed"
    return {
        "turns": turns,
        "plans": plans,
        "final_payload": final_payload,
        "trace": state["trace"] if state else None,
        "final_state": outcome,
        "error": error,
    }


def _budget_ok(payload: Mapping[str, Any] | None, expect: Any) -> bool | None:
    if expect is None:
        return None
    if payload is None:
        return False
    return budget_compliant(payload.get("budget") or {}, expect)


def _feasibility(
    plan_id: str, version: int, payload: Mapping[str, Any], places_by_id: Mapping[str, Place]
) -> dict[str, Any]:
    ok, unchecked, problems = schedule_feasible(payload.get("itinerary") or {}, places_by_id)
    return {"plan_id": plan_id, "version": version, "ok": ok, "unchecked": unchecked, "problems": problems}


def _constraints(payload: Mapping[str, Any] | None, expect: Any) -> dict[str, bool]:
    if expect is None:
        return {}
    if payload is None:
        return {name: False for name in constraint_checks({}, expect)}
    return constraint_checks(payload.get("itinerary") or {}, expect)


def _agents_summary(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    hits = sum(r["handler_hits"][0] for r in records)
    gold_turns = sum(r["handler_hits"][1] for r in records)
    tp = sum(r["tool_counts"][0] for r in records)
    fp = sum(r["tool_counts"][1] for r in records)
    fn = sum(r["tool_counts"][2] for r in records)
    plans = [item for r in records for item in r["feasibility"]]
    with_constraints = [r for r in records if r["constraints"]]
    types = sorted({name for r in with_constraints for name in r["constraints"]})
    turns = [turn for r in records for turn in r["turns"] if turn["error"] is None]
    by_handler: dict[str, list[float]] = {}
    for turn in turns:
        by_handler.setdefault(turn["handler"], []).append(turn["latency_ms"])
    budgets = [r["budget_ok"] for r in records if r["budget_ok"] is not None]
    return {
        "n": len(records),
        "task_success_rate": rate(r["task_success"] for r in records),
        "routing_accuracy": _ratio(hits, gold_turns),
        "trace_accuracy": rate(r["trace_ok"] for r in records),
        "tool_exact_rate": rate(r["tools_exact"] for r in records),
        "tool_precision": _ratio(tp, tp + fp),
        "tool_recall": _ratio(tp, tp + fn),
        "budget_compliance_rate": rate(budgets),
        "budget_n": len(budgets),
        "schedule_feasibility_rate": rate(item["ok"] for item in plans),
        "plans_n": len(plans),
        "unchecked_visits": sum(item["unchecked"] for item in plans),
        "constraint_satisfaction_rate": rate(all(r["constraints"].values()) for r in with_constraints),
        "constraint_n": len(with_constraints),
        "constraint_by_type": {
            name: rate(r["constraints"][name] for r in with_constraints if name in r["constraints"])
            for name in types
        },
        **_latency_stats([turn["latency_ms"] for turn in turns]),
        "latency_by_handler": {
            handler: {"n": len(values), **_latency_stats(values)} for handler, values in sorted(by_handler.items())
        },
        "tokens_per_turn": _tokens_per_turn([turn["usage"] for turn in turns]),
        "errors": sum(1 for r in records if r["error"] is not None),
    }


# ---------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------


def _ollama_up() -> bool:
    try:
        return httpx.get(f"{ollama_url()}/api/tags", timeout=5).status_code == 200
    except httpx.HTTPError:
        return False


def _build_answerer(places: Sequence[Place]) -> RagAnswerer:
    """The production answerer, built the way api.chat._rag builds it."""
    client = EmbedClient(ollama_url(), rag_embed_model())
    retriever = Retriever(places, EmbeddingStore(rag_index_path()), client)
    return RagAnswerer(
        retriever, lambda place: texts.place_text(place, phone_of(place)), ollama_url(), rag_gen_model()
    )


def _write(out_dir: Path, name: str, config: dict[str, Any], result: Mapping[str, Any]) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{name}.json"
    document = {"config": config, "summary": result["summary"], "records": result["records"]}
    path.write_text(json.dumps(document, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return path


def main(argv: Sequence[str] | None = None) -> int:
    """Run the chosen suites; 2 when the only requested suite could not run."""
    parser = argparse.ArgumentParser(description="System metrics for the Hue travel chat.")
    parser.add_argument("--suite", choices=["rag", "agents", "all"], default="all")
    parser.add_argument("--split", choices=["dev", "test", "all"], default="dev")
    parser.add_argument("--judge-model", default="qwen3.5:9b")
    parser.add_argument("--no-llm", action="store_true", help="rules-based understanding, no Ollama")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    llm = not args.no_llm and _ollama_up()
    suites = ["rag", "agents"] if args.suite == "all" else [args.suite]
    places = HuePlacesRepository(hue_database_path()).list_all()
    places_by_id = {place.id: place for place in places}
    config: dict[str, Any] = {
        "models": {
            "extractor": qu_model() if llm else None,
            "generator": rag_gen_model() if llm else None,
            "embedding": rag_embed_model() if llm else None,
            "judge": args.judge_model if llm else None,
        },
        "k": DEFAULT_K,
        "split": args.split,
        "date": date.today().isoformat(),
        "eval_ref": EVAL_REF.isoformat(),
        "extractor": "ollama" if llm else "rules",
    }

    answerer: RagAnswerer | None = None
    if llm:
        extractor = OllamaExtractor(ollama_url(), qu_model())
        understand_fn: Callable[[str, Any], Any] = lambda text, ctx: understand(  # noqa: E731
            text, EVAL_REF, ctx, extractor=extractor
        )
        answerer = _build_answerer(places)
    else:
        understand_fn = lambda text, ctx: understand(text, EVAL_REF, ctx)  # noqa: E731

    ran = 0
    for suite in suites:
        if suite == "rag":
            if answerer is None:
                print(f"RAG suite needs Ollama at {ollama_url()}", file=sys.stderr)
                continue
            items = load_jsonl(RAG_EVAL_FILE, RagItem, args.split)
            result = run_rag_suite(items, answerer, Judge(ollama_url(), args.judge_model), understand_fn)
        else:
            scenarios = load_jsonl(SCENARIO_FILE, Scenario, args.split)
            shared = answerer

            def make_harness() -> EvalHarness:
                rag = SimpleNamespace(answer=shared.answer, retriever=shared.retriever) if shared else None
                return build_harness(understand_fn, rag)

            result = run_agents_suite(scenarios, make_harness, places_by_id, rag_enabled=shared is not None)
        path = _write(args.out_dir, f"{suite}_{args.split}", config, result)
        print(f"{suite} suite ({args.split}) -> {path}")
        print(json.dumps(result["summary"], ensure_ascii=False, indent=2, default=str))
        ran += 1
    return 0 if ran else 2


if __name__ == "__main__":
    raise SystemExit(main())
