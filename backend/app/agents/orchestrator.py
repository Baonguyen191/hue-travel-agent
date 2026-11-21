"""LangGraph trip workflow with validation retries and a durable approval interrupt.

Graph: search -> itinerary -> budget -> validate -> approval -> await_approval -> END.
- validate sends a failing plan back to itinerary, at most MAX_RETRIES times, then to failed.
- approval saves the plan version once; await_approval only waits and answers, so a
  resume never saves a second version.
- an edit answer at await_approval goes back to search.

State holds plain JSON-compatible dicts so the checkpointer never pickles pydantic models.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any, TypedDict

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from app.agents.search import SearchAgent
from app.db.store import DEFAULT_OWNER, PlanStore
from app.schemas.booking import ApprovalResult
from app.schemas.itinerary import ItineraryResult
from app.schemas.request import TripRequest
from app.schemas.search import SearchResult
from app.services.budget_optimizer import BudgetAgent
from app.services.itinerary_optimizer import ItineraryAgent, ItineraryConfig
from app.services.quote import UnknownOptionError, approve_option

MAX_RETRIES = 3
AWAITING = "AWAITING_APPROVAL"
APPROVED = "APPROVED"
FAILED = "FAILED_VALIDATION"
_AWAIT_NODE = "await_approval"


class StalePlanError(ValueError):
    """The approval names a plan version that is no longer the latest."""


class NotWaitingError(ValueError):
    """The thread has no plan waiting for approval."""


class WorkflowState(TypedDict, total=False):
    request: dict[str, Any]
    owner_id: str
    thread_id: str
    search: dict[str, Any]
    itinerary: dict[str, Any]
    budget: dict[str, Any]
    retries: int
    attempts: list[str]
    verdict: str
    decision: str
    status: str
    warnings: list[str]
    trace: list[str]
    plan_id: str | None
    version: int | None
    approval: dict[str, Any] | None


def validate_plan(itinerary: dict[str, Any], budget: dict[str, Any]) -> list[str]:
    """Return why a plan is not ready for approval; an empty list means it is ready."""
    problems = list(itinerary["validation"]["warnings"])
    if not budget["options"]:
        problems.append("no budget option")
    return problems


def itinerary_config_for(retries: int) -> ItineraryConfig:
    """Relax the itinerary on each retry: fewer visits, then no cafe break, then two visits a day."""
    base = ItineraryConfig()
    if retries == 0:
        return base
    max_visits = 2 if retries >= 3 else base.max_visits_per_day - 1
    return replace(base, max_visits_per_day=max_visits, cafe_break=retries < 2)


def _config(thread_id: str) -> dict[str, Any]:
    return {"configurable": {"thread_id": thread_id}}


def _initial_state(thread_id: str, request: TripRequest, owner_id: str) -> dict[str, Any]:
    return {
        "request": request.model_dump(mode="json"),
        "owner_id": owner_id,
        "thread_id": thread_id,
        "retries": 0,
        "attempts": [],
        "trace": [],
        "warnings": [],
        "status": "RUNNING",
        "decision": "",
        "verdict": "",
        "approval": None,
        "plan_id": None,
        "version": None,
    }


def _visit(state: WorkflowState, name: str) -> list[str]:
    return [*state.get("trace", []), name]


def _request(state: WorkflowState) -> TripRequest:
    return TripRequest.model_validate(state["request"])


def _search(state: WorkflowState) -> SearchResult:
    return SearchResult.model_validate(state["search"])


def _labels(values: dict[str, Any]) -> list[str]:
    budget = values.get("budget") or {}
    return [option["label"] for option in budget.get("options", []) if option.get("label")]


def _route_validation(state: WorkflowState) -> str:
    return {"ok": "approval", "retry": "itinerary", "failed": "failed"}[state["verdict"]]


def _route_decision(state: WorkflowState) -> str:
    return "search" if state["decision"] == "edit" else END


def _check_answer(answer: Any, values: dict[str, Any]) -> None:
    """Refuse a bad answer before the graph sees it.

    LangGraph records a resume value even when the node then raises, so a bad answer
    must never reach the node: the next resume would get the same bad value back.
    """
    if not isinstance(answer, dict):
        raise ValueError("Resume value must be an object.")
    if answer.get("user_id") != values.get("owner_id"):
        raise PermissionError("owner: plan belongs to another user")
    if answer.get("action") == "approve":
        _check_approve(answer, values)
        return
    if answer.get("action") == "edit":
        TripRequest.model_validate(answer.get("request"))
        return
    raise ValueError(f"Unknown resume action: {answer.get('action')!r}")


def _check_approve(answer: dict[str, Any], values: dict[str, Any]) -> None:
    if answer.get("version") != values.get("version"):
        raise StalePlanError("Plan version is stale; approve the latest version.")
    if answer.get("option") not in _labels(values):
        raise UnknownOptionError(f"Plan has no budget option labelled {answer.get('option')}.")


def _edit(state: WorkflowState, answer: dict[str, Any]) -> dict[str, Any]:
    request = TripRequest.model_validate(answer["request"])
    return {
        "request": request.model_dump(mode="json"),
        "retries": 0,
        "attempts": [],
        "decision": "edit",
        "status": "EDITING",
        "trace": _visit(state, _AWAIT_NODE),
    }


class Orchestrator:
    """Runs the trip workflow for one thread at a time; state lives in the checkpointer."""

    def __init__(
        self,
        search: SearchAgent,
        budget: BudgetAgent,
        itinerary: ItineraryAgent,
        store: PlanStore,
        checkpointer: BaseCheckpointSaver,
    ) -> None:
        self.search = search
        self.budget = budget
        self.itinerary = itinerary
        self.store = store
        self.graph = self._build_graph().compile(checkpointer=checkpointer)

    def _build_graph(self) -> StateGraph:
        graph = StateGraph(WorkflowState)
        graph.add_node("search", self._search)
        graph.add_node("itinerary", self._itinerary)
        graph.add_node("budget", self._budget)
        graph.add_node("validate", self._validate)
        graph.add_node("approval", self._approval)
        graph.add_node(_AWAIT_NODE, self._await_approval)
        graph.add_node("failed", self._failed)
        graph.add_edge(START, "search")
        graph.add_edge("search", "itinerary")
        graph.add_edge("itinerary", "budget")
        graph.add_edge("budget", "validate")
        graph.add_conditional_edges("validate", _route_validation)
        graph.add_edge("approval", _AWAIT_NODE)
        graph.add_conditional_edges(_AWAIT_NODE, _route_decision)
        graph.add_edge("failed", END)
        return graph

    async def start(self, thread_id: str, request: TripRequest, owner_id: str = DEFAULT_OWNER) -> dict[str, Any]:
        """Run from search until the plan is waiting for approval, or until it fails."""
        self._refuse_other_owner(thread_id, owner_id)
        await self.graph.ainvoke(_initial_state(thread_id, request, owner_id), _config(thread_id))
        return await self.state(thread_id)

    async def resume(self, thread_id: str, value: dict[str, Any]) -> dict[str, Any]:
        """Answer the pending approval: `approve` (with option, user_id, version) or `edit` (with request)."""
        snapshot = await self.graph.aget_state(_config(thread_id))
        if _AWAIT_NODE not in snapshot.next:
            raise NotWaitingError("Plan is not waiting for approval.")
        _check_answer(value, snapshot.values)
        await self.graph.ainvoke(Command(resume=value), _config(thread_id))
        return await self.state(thread_id)

    async def state(self, thread_id: str) -> dict[str, Any] | None:
        """Return the checkpointed workflow summary, or None when the thread has no checkpoint."""
        snapshot = await self.graph.aget_state(_config(thread_id))
        if not snapshot.values:
            return None
        values = snapshot.values
        return {
            "thread_id": thread_id,
            "status": values.get("status"),
            "plan_id": values.get("plan_id"),
            "version": values.get("version"),
            "options": _labels(values),
            "warnings": values.get("warnings", []),
            "trace": values.get("trace", []),
            "retries": values.get("retries", 0),
            "attempts": values.get("attempts", []),
            "approval": values.get("approval"),
            "waiting": _AWAIT_NODE in snapshot.next,
        }

    def _refuse_other_owner(self, thread_id: str, owner_id: str) -> None:
        plan = self.store.latest(thread_id)
        if plan is not None and plan["owner_id"] != owner_id:
            raise PermissionError("owner: plan belongs to another user")

    async def _search(self, state: WorkflowState) -> dict[str, Any]:
        result = await self.search.search(_request(state))
        return {"search": result.model_dump(mode="json"), "trace": _visit(state, "search")}

    def _itinerary(self, state: WorkflowState) -> dict[str, Any]:
        agent = ItineraryAgent(config=itinerary_config_for(state["retries"]), places=self.itinerary.places)
        plan = agent.plan(_request(state), _search(state))
        return {"itinerary": plan.model_dump(mode="json"), "trace": _visit(state, "itinerary")}

    def _budget(self, state: WorkflowState) -> dict[str, Any]:
        itinerary = ItineraryResult.model_validate(state["itinerary"])
        result = self.budget.build(_request(state), _search(state), visit_poi_ids=itinerary.poi_ids())
        return {"budget": result.model_dump(mode="json"), "trace": _visit(state, "budget")}

    def _validate(self, state: WorkflowState) -> dict[str, Any]:
        problems = validate_plan(state["itinerary"], state["budget"])
        trace = _visit(state, "validate")
        if not problems:
            return {"verdict": "ok", "warnings": list(state["budget"]["warnings"]), "trace": trace}
        attempts = [*state.get("attempts", []), "; ".join(problems)]
        if state["retries"] < MAX_RETRIES:
            return {"verdict": "retry", "retries": state["retries"] + 1, "attempts": attempts, "trace": trace}
        return {"verdict": "failed", "attempts": attempts, "trace": trace}

    def _approval(self, state: WorkflowState) -> dict[str, Any]:
        payload = {
            "request": state["request"],
            "search": state["search"],
            "budget": state["budget"],
            "itinerary": state["itinerary"],
        }
        plan_id, version = self.store.save_plan(state["thread_id"], payload, state["owner_id"])
        return {
            "plan_id": plan_id,
            "version": version,
            "status": AWAITING,
            "trace": _visit(state, "approval"),
        }

    async def _await_approval(self, state: WorkflowState) -> dict[str, Any]:
        answer = interrupt(
            {
                "plan_id": state["plan_id"],
                "version": state["version"],
                "options": _labels(state),
                "status": AWAITING,
            }
        )
        if answer["action"] == "approve":
            return self._approve(state, answer)
        return _edit(state, answer)

    def _approve(self, state: WorkflowState, answer: dict[str, Any]) -> dict[str, Any]:
        plan = self.store.latest(state["thread_id"])
        if plan is None or plan["version"] != state["version"]:
            raise StalePlanError("Plan version is stale; approve the latest version.")
        approval: ApprovalResult = approve_option(self.store, plan, answer["option"])
        return {
            "approval": approval.model_dump(mode="json"),
            "status": APPROVED,
            "decision": "approve",
            "trace": _visit(state, _AWAIT_NODE),
        }

    def _failed(self, state: WorkflowState) -> dict[str, Any]:
        return {"status": FAILED, "warnings": list(state.get("attempts", [])), "trace": _visit(state, "failed")}
