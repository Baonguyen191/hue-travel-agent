"""Evaluation runner: the agents suite over the real chat service and the RAG suite over fakes."""

from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path

_BACKEND = _Path(__file__).resolve().parents[1] / "backend"
if str(_BACKEND) not in _sys.path:
    _sys.path.insert(0, str(_BACKEND))
_TESTS = _Path(__file__).resolve().parent
if str(_TESTS) not in _sys.path:
    _sys.path.insert(0, str(_TESTS))

from typing import Any  # noqa: E402

from app.core.config import hue_database_path  # noqa: E402
from app.evaluation.gold import RagItem, Scenario, ScenarioExpect  # noqa: E402
from app.evaluation.harness import build_harness  # noqa: E402
from app.evaluation.judge import JudgeError  # noqa: E402
from app.evaluation.run import run_agents_suite, run_rag_suite  # noqa: E402
from app.rag.answer import REFUSAL_TEXT, RagAnswer  # noqa: E402
from app.rag.retrieve import Retriever  # noqa: E402
from app.repositories.hue_places import HuePlacesRepository  # noqa: E402
from app.understanding.evaluate import EVAL_REF  # noqa: E402
from app.understanding.understand import understand  # noqa: E402
from test_rag_retrieve import PLACES  # noqa: E402

RAG_SUMMARY_KEYS = {
    "n",
    "context_precision",
    "context_recall",
    "faithfulness",
    "answer_correctness",
    "citation_hit_rate",
    "refusal_precision",
    "refusal_recall",
    "judge_errors",
    "errors",
    "refusal_count",
    "n_scored",
    "fallback_count",
    "mode_counts",
    "latency_p50_ms",
    "latency_p95_ms",
    "latency_mean_ms",
    "tokens_per_turn",
    "judge_tokens_total",
    "per_group",
}
AGENT_SUMMARY_KEYS = {
    "n",
    "task_success_rate",
    "routing_accuracy",
    "trace_accuracy",
    "tool_exact_rate",
    "tool_precision",
    "tool_recall",
    "budget_compliance_rate",
    "budget_n",
    "schedule_feasibility_rate",
    "plans_n",
    "unchecked_visits",
    "constraint_satisfaction_rate",
    "constraint_n",
    "constraint_by_type",
    "latency_p50_ms",
    "latency_p95_ms",
    "latency_mean_ms",
    "latency_by_handler",
    "tokens_per_turn",
    "errors",
}


def _rules(text: str, context: Any) -> Any:
    return understand(text, EVAL_REF, context)


def _scenarios() -> list[Scenario]:
    plan = Scenario(
        id="t1",
        split="dev",
        group="plan_full",
        turns=["Từ Hà Nội, 2 người, đi Huế 2 ngày từ 20/12"],
        expect=ScenarioExpect(
            handlers=["plan_new"],
            final_state="awaiting_approval",
            trace=["search", "itinerary", "budget", "validate", "approval"],
            tools_called=["poi_search", "hotel", "transport"],
        ),
    )
    refused = Scenario(
        id="t2",
        split="dev",
        group="out_of_scope",
        turns=["Mình muốn đi Hà Nội 3 ngày"],
        expect=ScenarioExpect(
            handlers=["out_of_scope"], final_state="refused", tools_not_called=["transport", "hotel"]
        ),
    )
    return [plan, refused]


def test_agents_suite_scores_a_plan_and_a_refusal() -> None:
    places = {p.id: p for p in HuePlacesRepository(hue_database_path()).list_all()}
    result = run_agents_suite(
        _scenarios(), lambda: build_harness(_rules, None), places, rag_enabled=False
    )
    summary, records = result["summary"], result["records"]
    assert AGENT_SUMMARY_KEYS <= set(summary)
    assert summary["n"] == 2
    assert summary["task_success_rate"] == 1.0
    assert summary["routing_accuracy"] == 1.0
    assert summary["trace_accuracy"] == 1.0
    assert summary["tool_exact_rate"] == 1.0
    assert summary["schedule_feasibility_rate"] is not None
    assert summary["errors"] == 0
    assert records[0]["turns"][0]["latency_ms"] > 0
    assert records[0]["final_state"] == "awaiting_approval"
    assert records[1]["tools_called"] == []


def test_agents_suite_ignores_the_rag_tool_when_rag_is_off() -> None:
    scenario = Scenario(
        id="t3",
        split="dev",
        group="out_of_scope",
        turns=["Mình muốn đi Hà Nội 3 ngày"],
        expect=ScenarioExpect(handlers=["out_of_scope"], final_state="refused", tools_called=["rag"]),
    )
    result = run_agents_suite([scenario], lambda: build_harness(_rules, None), {}, rag_enabled=False)
    assert result["summary"]["tool_exact_rate"] == 1.0


class FakeAnswerer:
    """Answers the first question with a cited place and refuses the second."""

    def __init__(self) -> None:
        self.retriever = Retriever(PLACES)

    def answer(self, question: str, parsed: Any = None) -> RagAnswer:
        retrieval = self.retriever.retrieve(question, None, 5)
        if "Thiên Mụ" in question:
            return RagAnswer("Chùa Thiên Mụ ở Huế.", "Chùa Thiên Mụ ở Huế [huetripo:3].", ["huetripo:3"], True, "llm", retrieval)
        return RagAnswer(REFUSAL_TEXT, REFUSAL_TEXT, [], False, "refusal", retrieval)


class FakeJudge:
    def claims(self, answer: str) -> list[str]:
        return ["c1", "c2"]

    def support(self, claims: list[str], context: str) -> list[bool]:
        return [True, False]

    def compare(self, claims: list[str], reference: str) -> tuple[int, int, int]:
        return (1, 1, 0)


def test_rag_suite_scores_an_answer_and_a_refusal() -> None:
    items = [
        RagItem(
            id="r1",
            split="dev",
            group="single_place",
            question="Chùa Thiên Mụ ở đâu?",
            relevant_poi_ids=["huetripo:3"],
            reference_answer="Chùa Thiên Mụ ở Huế.",
        ),
        RagItem(
            id="r2",
            split="dev",
            group="unanswerable",
            question="Giá vé máy bay đi Paris?",
            relevant_poi_ids=[],
            reference_answer="Không có thông tin.",
        ),
    ]
    result = run_rag_suite(items, FakeAnswerer(), FakeJudge(), lambda text, ctx: None)
    summary, records = result["summary"], result["records"]
    assert RAG_SUMMARY_KEYS <= set(summary)
    assert summary["n"] == 2
    assert summary["context_recall"] == 1.0
    assert summary["faithfulness"] == 0.5
    assert records[0]["citation_hit"] is True
    assert records[1]["answer_correctness"] == 1.0
    assert records[1]["faithfulness"] is None
    assert summary["refusal_precision"] == 1.0
    assert summary["refusal_recall"] == 1.0
    assert summary["per_group"]["single_place"]["context_recall"] == 1.0


def _item(item_id: str, question: str, group: str = "single_place", relevant: list[str] | None = None) -> RagItem:
    return RagItem(
        id=item_id,
        split="dev",
        group=group,  # type: ignore[arg-type]
        question=question,
        relevant_poi_ids=["huetripo:3"] if relevant is None else relevant,
        reference_answer="Chùa Thiên Mụ ở Huế.",
    )


def test_rag_suite_counts_judge_errors_and_leaves_them_out_of_the_means() -> None:
    class FlakyJudge(FakeJudge):
        def support(self, claims: list[str], context: str) -> list[bool]:
            if "bad" in self.current:
                raise JudgeError("two bad replies")
            return [True, False]

        current = ""

        def claims(self, answer: str) -> list[str]:
            self.current = answer
            return ["c1", "c2"]

    class TwoAnswers(FakeAnswerer):
        def answer(self, question: str, parsed: Any = None) -> RagAnswer:
            retrieval = self.retriever.retrieve(question, None, 5)
            text = "bad answer" if "hỏng" in question else "good answer"
            return RagAnswer(text, text, ["huetripo:3"], True, "llm", retrieval)

    items = [_item("ok", "Chùa Thiên Mụ ở đâu?"), _item("bad", "Chùa Thiên Mụ hỏng?")]
    result = run_rag_suite(items, TwoAnswers(), FlakyJudge(), lambda text, ctx: None)
    summary, records = result["summary"], result["records"]
    assert summary["judge_errors"] == 1
    assert records[1]["judge_error"] is True
    assert records[1]["faithfulness"] is None and records[1]["answer_correctness"] is None
    assert summary["faithfulness"] == records[0]["faithfulness"] == 0.5
    assert summary["n_scored"]["faithfulness"] == 1
    assert summary["n_scored"]["context_recall"] == 2


def test_rag_fact_override_flips_the_claim_stating_a_wrong_time() -> None:
    class WrongTime(FakeAnswerer):
        def answer(self, question: str, parsed: Any = None) -> RagAnswer:
            retrieval = self.retriever.retrieve(question, None, 5)
            return RagAnswer("Mở cửa 05:00.", "Mở cửa 05:00 [huetripo:3].", ["huetripo:3"], True, "llm", retrieval)

    class Lenient(FakeJudge):
        def claims(self, answer: str) -> list[str]:
            return ["Mở cửa 05h00"]

        def support(self, claims: list[str], context: str) -> list[bool]:
            return [True]

    result = run_rag_suite([_item("t", "Chùa Thiên Mụ mở cửa lúc nào?")], WrongTime(), Lenient(), lambda t, c: None)
    record = result["records"][0]
    assert record["supported"] == [False]
    assert record["faithfulness"] == 0.0


def test_rag_fact_override_adds_one_false_when_no_claim_states_the_fact() -> None:
    class WrongTime(FakeAnswerer):
        def answer(self, question: str, parsed: Any = None) -> RagAnswer:
            retrieval = self.retriever.retrieve(question, None, 5)
            raw = "Mở cửa 05:00 [huetripo:3]. Đóng cửa 05:00 [huetripo:3]."
            return RagAnswer("x", raw, ["huetripo:3"], True, "llm", retrieval)

    result = run_rag_suite([_item("t", "Chùa Thiên Mụ mở cửa?")], WrongTime(), FakeJudge(), lambda t, c: None)
    assert result["records"][0]["supported"] == [True, False, False]


def test_rag_item_that_raises_is_recorded_and_the_suite_continues() -> None:
    class Crashing(FakeAnswerer):
        def answer(self, question: str, parsed: Any = None) -> RagAnswer:
            if "nổ" in question:
                raise RuntimeError("boom")
            return super().answer(question, parsed)

    items = [_item("boom", "Chùa nổ?"), _item("ok", "Chùa Thiên Mụ ở đâu?")]
    result = run_rag_suite(items, Crashing(), FakeJudge(), lambda t, c: None)
    summary, records = result["summary"], result["records"]
    assert "RuntimeError" in records[0]["error"] and records[0]["context_recall"] is None
    assert summary["errors"] == 1 and summary["n"] == 2
    assert summary["context_recall"] == 1.0
    assert summary["n_scored"]["context_recall"] == 1


def test_agents_suite_records_a_crashing_turn_and_scores_the_next_scenario() -> None:
    calls = {"n": 0}

    def make_harness():  # type: ignore[no-untyped-def]
        h = build_harness(_rules, None)
        calls["n"] += 1
        if calls["n"] == 1:

            async def boom(conversation: str, user: str, text: str) -> Any:
                raise RuntimeError("provider down")

            h.service.handle = boom  # type: ignore[method-assign]
        return h

    places = {p.id: p for p in HuePlacesRepository(hue_database_path()).list_all()}
    result = run_agents_suite(_scenarios(), make_harness, places, rag_enabled=False)
    first, second = result["records"]
    assert first["turns"][0]["error"] and "provider down" in first["turns"][0]["error"]
    assert first["task_success"] is False and first["final_state"] == "failed"
    assert result["summary"]["errors"] == 1
    assert second["task_success"] is True
    assert result["summary"]["latency_p50_ms"] is not None
    assert "none" not in result["summary"]["latency_by_handler"]
